"""
Zynd Network MCP tools — discovery, networking, and messaging on the Zynd AI network.

Tools:
  - search_zynd_personas: Search the registry for persona agents
  - get_persona_profile: Fetch a specific persona's full profile
  - list_my_connections: List the user's existing DM threads/connections
  - request_connection: Initiate a new DM thread with a persona
  - check_connection_status: Check if connected to a specific agent
  - message_zynd_agent: Send a message to another persona (A2A v3 — signed JSON-RPC
                       over the receiver's `{base}/a2a/v1` endpoint, with the signed
                       card discoverable at `{base}/.well-known/agent-card.json`)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

import config
from mcp.tools.error_utils import friendly_error, friendly_error_message

logger = logging.getLogger(__name__)

# The registry's /v1/search applies `max_results` to the raw candidate
# pool BEFORE it applies the `tags`/`entity_type` filter. So a filtered
# search with max_results=25 can return far fewer than 25 matching rows
# (e.g. entity_type=agent max=25 → 5, even though 20 agents exist),
# because most of the 25-row pool gets filtered out server-side. To
# surface the real catalog we widen the pool to this floor whenever a
# filter is active, then trim to the caller's top_k locally.
_REGISTRY_POOL_FLOOR = 60

# ── In-process cache for the People discovery surface ────────────────
# The dashboard's People page calls /api/persona/search on every
# keystroke (debounced 300ms). The registry is sometimes slow or
# unavailable, and rapid keystrokes were hammering it for nothing.
# A small TTL cache here turns repeated identical queries into a
# memory lookup, which is what users typing "founder" → "founders"
# → "found" → "founder" do all the time.
_DISCOVER_CACHE: dict[tuple[str, int], tuple[float, dict]] = {}
_DISCOVER_CACHE_LOCK = threading.Lock()
_DISCOVER_CACHE_TTL = 30.0  # seconds

# Avatar lookup cache. Avatars rarely change, but we hit the Supabase
# admin API to read auth.users.user_metadata which the python client
# doesn't expose nicely. We cache the (agent_id → avatar_url) map for
# 5 minutes so the People page never pays this cost per keystroke.
_AVATAR_CACHE: dict[str, tuple[float, dict[str, str]]] = {}
_AVATAR_CACHE_LOCK = threading.Lock()
_AVATAR_CACHE_TTL = 300.0  # 5 minutes

def _build_avatar_map() -> dict[str, str]:
    """
    Return a fresh ``{agent_id → avatar_url}`` map.

    We pull persona_agents to get the (user_id, agent_id, name) rows we
    care about (one query), then fetch the auth.users admin page to
    map user_id → avatar_url (one paginated HTTP call to the Supabase
    Admin API). The result is intersected so we only carry mappings for
    agents that exist locally — the registry returns agents from across
    the network, but only locally-deployed personas have avatar metadata
    we can resolve.
    """
    try:
        sb = _get_supabase()
        rows = (
            sb.table("persona_agents")
            .select("user_id,agent_id")
            .eq("active", True)
            .execute()
        )
        agent_to_user: dict[str, str] = {
            r["agent_id"]: r["user_id"]
            for r in (rows.data or [])
            if r.get("agent_id") and r.get("user_id")
        }
        if not agent_to_user:
            return {}

        # Paginated admin API. Default page size is 50; we collect all
        # pages until empty. Capped at 10 pages (500 users) which is
        # plenty headroom for current install sizes.
        user_avatars: dict[str, str] = {}
        page = 1
        admin_url = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users"
        headers = {
            "apikey": config.SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        }
        while page <= 10:
            r = requests.get(
                admin_url,
                headers=headers,
                params={"page": page, "per_page": 100},
                timeout=4,
            )
            if not r.ok:
                break
            users = (r.json() or {}).get("users") or []
            if not users:
                break
            for u in users:
                md = u.get("user_metadata") or {}
                pic = md.get("avatar_url") or md.get("picture")
                if isinstance(pic, str) and pic:
                    user_avatars[u["id"]] = pic
            if len(users) < 100:
                break
            page += 1

        return {
            aid: user_avatars[uid]
            for aid, uid in agent_to_user.items()
            if uid in user_avatars
        }
    except Exception as e:
        logger.warning(f"[discover] avatar map build failed: {e}")
        return {}

def _get_avatar_map() -> dict[str, str]:
    """Cached accessor for the avatar map. 5-minute TTL."""
    now = time.time()
    with _AVATAR_CACHE_LOCK:
        cached = _AVATAR_CACHE.get("global")
        if cached and cached[0] > now:
            return cached[1]
    # Build outside the lock so a slow admin-API call doesn't block other
    # requests — they'll all see the stale value until the rebuild lands.
    fresh = _build_avatar_map()
    with _AVATAR_CACHE_LOCK:
        _AVATAR_CACHE["global"] = (now + _AVATAR_CACHE_TTL, fresh)
    return fresh

def _discover_cache_get(key: tuple[str, int]) -> dict | None:
    with _DISCOVER_CACHE_LOCK:
        hit = _DISCOVER_CACHE.get(key)
        if not hit:
            return None
        expires_at, value = hit
        if expires_at < time.time():
            _DISCOVER_CACHE.pop(key, None)
            return None
        return value

def _discover_cache_put(key: tuple[str, int], value: dict) -> None:
    with _DISCOVER_CACHE_LOCK:
        _DISCOVER_CACHE[key] = (time.time() + _DISCOVER_CACHE_TTL, value)
        # Bound the cache size — keep the 64 freshest entries.
        if len(_DISCOVER_CACHE) > 64:
            oldest = sorted(_DISCOVER_CACHE.items(), key=lambda kv: kv[1][0])[: len(_DISCOVER_CACHE) - 64]
            for k, _ in oldest:
                _DISCOVER_CACHE.pop(k, None)

def _discover_local(q: str, top_k: int, avatars: dict[str, str]) -> list[dict]:
    """
    Query local persona_agents using Postgres FTS (ranked) or a broad
    ORDER BY updated_at for empty/catchall queries.

    Returns a list of {name, agent_id, description, avatar_url} dicts.
    Falls back to ILIKE when the FTS RPC fails (e.g. migration not yet applied).
    """
    sb = _get_supabase()
    broad = not q or q.lower() in (
        "persona", "all", "any", "everyone", "personas", "agents", "network", "list", "",
    )

    rows_data: list[dict] = []

    if broad:
        result = (
            sb.table("persona_agents")
            .select("agent_id,name,description")
            .eq("active", True)
            .order("updated_at", desc=True)
            .limit(top_k)
            .execute()
        )
        rows_data = result.data or []
    else:
        try:
            result = sb.rpc(
                "search_personas_fts",
                {"query_text": q, "result_limit": top_k},
            ).execute()
            rows_data = result.data or []
        except Exception as fts_err:
            logger.warning(f"[discover] FTS RPC failed ({fts_err!r}), falling back to ILIKE")
            pattern = f"%{q}%"
            result = (
                sb.table("persona_agents")
                .select("agent_id,name,description")
                .eq("active", True)
                .or_(f"name.ilike.{pattern},description.ilike.{pattern},brief_content.ilike.{pattern}")
                .limit(top_k)
                .execute()
            )
            rows_data = result.data or []

    return [
        {
            "name": r.get("name") or "",
            "agent_id": r.get("agent_id") or "",
            "description": r.get("description") or "",
            "avatar_url": avatars.get(r.get("agent_id") or ""),
        }
        for r in rows_data
        if r.get("agent_id")
    ]

def _discover_registry(q: str, top_k: int, avatars: dict[str, str]) -> list[dict]:
    """
    Query the Zynd registry for personas matching `q`.
    Returns same {name, agent_id, description, avatar_url} shape as _discover_local.
    Returns [] on any error — callers treat registry as best-effort supplement.
    """
    registry_q = q if (q and q.lower() not in ("", "persona")) else "persona"
    try:
        resp = requests.post(
            f"{config.ZYND_REGISTRY_URL}/v1/search",
            json={
                "query": registry_q,
                "tags": ["persona"],
                "max_results": max(int(top_k), _REGISTRY_POOL_FLOOR),
                "status": "any",
            },
            timeout=4,
        )
        resp.raise_for_status()
        raw = resp.json().get("results", [])
    except requests.exceptions.Timeout:
        logger.warning("[discover] registry timed out")
        return []
    except Exception as e:
        logger.warning(f"[discover] registry call failed ({e!r})")
        return []

    out: list[dict] = []
    for a in raw:
        tags = a.get("tags") or []
        if "persona" not in tags:
            caps = a.get("capability_summary") or a.get("capabilities") or {}
            if isinstance(caps, str):
                try:
                    caps = json.loads(caps)
                except Exception:
                    caps = {}
            if isinstance(caps, dict):
                if "persona" not in caps.get("services", []) and "persona" not in caps.get("skills", []):
                    continue
            else:
                continue
        aid = a.get("entity_id") or a.get("agent_id") or ""
        if not aid:
            continue
        out.append({
            "name": a.get("name") or "",
            "agent_id": aid,
            "description": a.get("summary") or a.get("description") or "",
            "avatar_url": avatars.get(aid),
        })
    return out

def discover_personas(query: str, top_k: int = 20) -> dict:
    """
    Local-first people discovery for the dashboard People page.

    Strategy:
      1. Query local persona_agents via Postgres FTS (ranked by relevance).
         Broad/empty queries return all active personas ordered by recency.
      2. If local results don't fill top_k, supplement with the Zynd registry
         (deduped by agent_id so a persona that's both local and in the registry
         only appears once — with the richer local description).
      3. 30s in-process cache keyed by (query, top_k) — typing fast no
         longer slams the DB or the registry.

    Returns: ``{status, count, results: [{name, agent_id, description, avatar_url}],
               from_cache, source}``
    """
    q = (query or "").strip()
    key = (q.lower(), int(top_k))

    cached = _discover_cache_get(key)
    if cached is not None:
        return {**cached, "from_cache": True}

    avatars = _get_avatar_map()

    try:
        local = _discover_local(q, top_k, avatars)
    except Exception as e:
        logger.error(f"[discover] local query failed: {e}")
        local = []

    seen_ids: set[str] = {p["agent_id"] for p in local}
    combined = list(local)

    if len(combined) < top_k:
        needed = top_k - len(combined)
        registry = _discover_registry(q, needed + 10, avatars)
        for p in registry:
            if p["agent_id"] not in seen_ids:
                combined.append(p)
                seen_ids.add(p["agent_id"])
                if len(combined) >= top_k:
                    break

    results = combined[:top_k]
    source = (
        "local+registry" if len(combined) > len(local)
        else "local" if local
        else "registry"
    )

    if not results:
        return {
            "status": "error",
            "error": "No personas found",
            "error_message": "I couldn't find any personas matching that request.",
            "hint": "Try a broader or differently-worded query.",
            "results": [],
            "count": 0,
            "source": "none",
        }

    out = {
        "status": "success",
        "count": len(results),
        "total_available": len(combined),
        "results": results,
        "source": source,
    }
    _discover_cache_put(key, out)
    return out

def _fetch_agent_card(agent_id: str) -> dict | None:
    """Fetch an agent's full card from the registry. Card contains endpoints, capabilities, metadata."""
    try:
        resp = requests.get(
            f"{config.ZYND_REGISTRY_URL}/v1/entities/{agent_id}/card",
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None

def _agent_url_from_card(card: dict | None) -> str:
    """Extract the persona's A2A endpoint URL from a card.

    Handles both the v0.3 shape (top-level `url`, advertised when
    `preferredTransport=JSONRPC`) and the legacy v2 shape
    (`endpoints.invoke`). For v2 URLs we don't transform — callers
    use resolve_a2a_url to derive the v3 form when sending.
    """
    if not card:
        return ""
    if isinstance(card.get("url"), str) and card.get("preferredTransport") == "JSONRPC":
        return card["url"]
    endpoints = card.get("endpoints") or {}
    return endpoints.get("invoke") or endpoints.get("websocket") or ""

def _get_supabase():
    return config.get_supabase()

# ── Discovery Tools ──────────────────────────────────────────────────

# Stop-words to strip when broadening a literal user query into something
# the registry's keyword search can match. The registry indexes agent
# names + tags + category, all single-domain keywords — so verbose
# user phrases like "competitors of Zynd AI" return zero unless we trim
# the connective scaffolding.
_QUERY_STOPWORDS: set[str] = {
    "a", "an", "the", "of", "for", "to", "with", "from", "on", "in", "by",
    "at", "and", "or", "is", "are", "as", "any", "some",
    # Common LLM/user verbs that aren't part of the topic
    "find", "search", "search-for", "look", "look-for", "show", "show-me",
    "get", "give", "give-me", "tell", "tell-me", "list", "fetch", "discover",
    "want", "need", "please", "can", "could", "would",
    # Pronouns / fillers
    "me", "my", "i", "you", "your", "us", "we", "they", "them", "it", "this", "that",
    # Domain noise common in agent-ask phrasing
    "agent", "agents", "service", "services", "tool", "tools", "thing", "things",
    "something", "someone", "anyone", "anything",
}

def _normalize_query(q: str) -> str:
    """Strip stop-words and trim verbose user prose into 1–4 keyword tokens.

    Registry search is keyword-substring + tag-match; multi-word phrases
    that don't share lexical content with a real entity's name/tags
    return zero. We pre-clean to give the registry something it can
    actually find.

    Examples:
      "competitors of Zynd AI"   -> "competitors zynd ai"
      "find me a translation agent" -> "translation"
      "search for influencer discovery agents" -> "influencer discovery"
    """
    import re as _re
    if not q:
        return ""
    # Lowercase + split on non-word chars (keeps hyphens by re-splitting).
    tokens = [t for t in _re.split(r"[^\w-]+", q.lower()) if t]
    filtered = [t for t in tokens if t not in _QUERY_STOPWORDS and len(t) > 1]
    if not filtered:
        return q.strip()
    # Keep the first 4 content tokens — registry full-text search uses
    # OR semantics, so the first few words drive recall.
    return " ".join(filtered[:4])

def _call_registry_search(query: str, kind: str, top_k: int) -> tuple[list[dict], Optional[str]]:
    """Single round-trip to the registry's /v1/search. Returns
    (raw_results, error_message_or_None).

    When a server-side filter (`tags`/`entity_type`) is active, we widen
    `max_results` to `_REGISTRY_POOL_FLOOR` so the pre-filter pool cap
    (see the constant's docstring) doesn't starve the result set. The
    caller is responsible for trimming the returned rows to its own
    top_k after any further client-side filtering.
    """
    filtered = kind in ("persona", "agent", "service")
    requested = max(int(top_k), _REGISTRY_POOL_FLOOR) if filtered else int(top_k)
    body: dict[str, Any] = {
        "query": query,
        "max_results": requested,
        "status": "any",
        "enrich": True,
    }
    # The registry honors `entity_type` (exactly "agent"|"service") as a
    # server-side filter; it ignores the legacy `type` key. Personas are a
    # tag, not an entity_type, so filter those by tag.
    if kind == "persona":
        body["tags"] = ["persona"]
    elif kind in ("agent", "service"):
        body["entity_type"] = kind
    try:
        resp = requests.post(
            f"{config.ZYND_REGISTRY_URL}/v1/search",
            json=body,
            timeout=8,
        )
        resp.raise_for_status()
        return (resp.json() or {}).get("results") or [], None
    except requests.exceptions.Timeout:
        return [], "Registry timed out."
    except Exception as e:
        return [], f"Registry search failed: {e}"

# ── Deployer fallback ────────────────────────────────────────────────
# Agents/services run on the deployer but don't always make it into the
# registry's search index (entityId stays null). So a registry-only
# search under-reports what's actually live. We supplement registry
# results with the deployer's *running* deployments. The deployment list
# is heavy (800+ rows) and changes slowly, so cache it briefly.
_DEPLOYER_CACHE: dict[str, tuple[float, list[dict]]] = {}
_DEPLOYER_CACHE_LOCK = threading.Lock()
_DEPLOYER_CACHE_TTL = 60.0  # seconds

def _deployer_running_entities() -> list[dict]:
    """Fetch the deployer's RUNNING agents/services as search-result rows.

    Each row mirrors the shape `search_zynd_network` emits. We build the
    A2A url + a kind from the cheap deployment row (name/slug/entityType/
    hostUrl) — NO per-entity card fetch (that's an 800-way N+1). The full
    card is resolved lazily later, at call time, by the existing
    get_zynd_service_card / call paths.
    """
    with _DEPLOYER_CACHE_LOCK:
        hit = _DEPLOYER_CACHE.get("running")
        if hit is not None and (time.time() - hit[0]) < _DEPLOYER_CACHE_TTL:
            return hit[1]

    rows: list[dict] = []
    try:
        resp = requests.get(f"{config.ZYND_DEPLOYER_URL}/api/deployments", timeout=6)
        resp.raise_for_status()
        deployments = (resp.json() or {}).get("deployments") or []
        for d in deployments:
            if d.get("status") != "running":
                continue
            etype = (d.get("entityType") or "").lower()
            if etype not in ("agent", "service"):
                continue
            name = d.get("name") or d.get("slug") or ""
            slug = d.get("slug") or ""
            host = (d.get("hostUrl") or "").rstrip("/")
            if not (name and host):
                continue
            # The card's A2A endpoint is always <hostUrl>/a2a/v1 on the
            # deployer. We use the slug as a stable entity_id when the
            # deployment row carries no registry entityId.
            rows.append({
                "name": name,
                "entity_id": d.get("entityId") or slug,
                "kind": etype,
                "entity_type": etype,
                "summary": "",  # not on the cheap row; filled from card at call time
                "category": "",
                "tags": [],
                "url": f"{host}/a2a/v1",
                "status": "active",
                "avatar_url": None,
                "source": "deployer",
            })
    except Exception as e:
        logger.warning(f"[deployer] running-entities fetch failed: {e!r}")
        return []

    with _DEPLOYER_CACHE_LOCK:
        _DEPLOYER_CACHE["running"] = (time.time(), rows)
    return rows

def _merge_deployer_entities(
    results: list[dict], kind: str, query: str
) -> list[dict]:
    """Supplement registry `results` with deployer running entities that
    the registry didn't surface. Dedupes by entity_id and by name (the
    same agent can carry a registry id AND a deployer slug). Honors the
    requested `kind` and a cheap name/substring filter for keyword asks."""
    deployer = _deployer_running_entities()
    if not deployer:
        return results

    seen_ids = {r.get("entity_id") for r in results if r.get("entity_id")}
    seen_names = {(r.get("name") or "").lower() for r in results}
    q = (query or "").strip().lower()

    for d in deployer:
        if kind == "agent" and d["kind"] != "agent":
            continue
        if kind == "service" and d["kind"] != "service":
            continue
        if kind == "persona":
            continue  # personas never live on the deployer
        if d["entity_id"] in seen_ids or d["name"].lower() in seen_names:
            continue
        # For keyword (non-broad) asks, only include deployer rows whose
        # name actually matches — we have no summary/tags to match on.
        if q and q not in ("persona",) and q not in d["name"].lower():
            continue
        results.append(d)
        seen_ids.add(d["entity_id"])
        seen_names.add(d["name"].lower())
    return results

def _caller_agent_id(user_id: str) -> str:
    """Resolve the caller's own persona agent_id so discovery can exclude self —
    a user must never be recommended their own persona. Best-effort; returns ""
    if unknown so search never breaks on it."""
    if not user_id:
        return ""
    try:
        from agent import persona_manager
        status = persona_manager.get_persona_status(user_id)
        return (status or {}).get("agent_id") or ""
    except Exception:
        return ""

def search_zynd_network(query: str, top_k: int = 8, kind: str = "any", user_id: str = "") -> dict:
    """
    Find ANY callable thing on the Zynd Network — personas, services, and
    agents — in one search. Use this when you don't yet know whether the
    target is a human's persona or a standalone agent/service, or when
    the ask explicitly wants a mix ("what's on the network", "show me
    everything").

    IMPORTANT — when the ask is clearly about PEOPLE (a role, a topic of
    interest, "founders", "designers", "who should I meet", "someone who
    does X"), pass ``kind="persona"`` explicitly rather than the "any"
    default. Leaving `kind` at "any" for a people-only ask lets unrelated
    internal agents/services leak into the results — the registry's
    keyword match is shallow (name/tags/category only) and a query like
    "AI founders" can loosely match an unrelated "AI" service. For
    topical/role people-search specifically, ``search_zynd_personas`` is
    an even better first call — it ranks against each persona's actual
    bio via full-text search, not just name/tag keyword matching.

    Each result carries a ``kind`` field so the caller can decide the
    right next step:
      * ``persona`` — a human's AI persona. Requires ``request_connection``
        (the receiver must accept) before ``message_zynd_agent`` will
        deliver. Signed Ed25519 A2A.
      * ``service`` / ``agent`` — a standalone agent / service. Skip the
        connection flow entirely. Call ``get_zynd_service_card`` to read
        its input schema, then ``call_zynd_service`` to invoke it.

    The query is auto-normalized before hitting the registry (stop-words
    stripped, trimmed to ~4 keyword tokens). If the literal query yields
    zero hits, a broadened retry runs with just the first content token
    so verbose user phrases ("find competitors of Zynd AI") still match
    catalog entries (``competitor-monitor``).

    Args:
        query: Natural-language description ("competitor research",
               "translate text", "Alice", "find influencers on TikTok").
               Empty string returns a broad sample of active entities.
        top_k: Max results (1–25, default 8).
        kind:  Restrict to one kind: ``persona`` | ``service`` | ``agent``
               | ``any`` (default). Use ``persona`` for any people-seeking
               ask — see above. Pick ``any`` only for genuinely mixed or
               unclear asks — the result rows are tagged so the caller
               can branch.

    Returns ``{status, count, results: [{name, entity_id, kind, summary,
    category, tags, url, status, match_reason}], source, query_used}``.
    ``query_used`` echoes the actual string sent to the registry
    (post-normalization or post-broadening) so callers can show the user
    what was searched. ``match_reason`` is a short, grounded note on why
    a persona result matched (e.g. "matched on: founder, ai") — present
    it to the principal instead of inventing a reason.
    """
    raw_query = (query or "").strip()
    top_k = max(1, min(int(top_k or 8), 25))
    kind = (kind or "any").lower().strip()

    if kind == "persona":
        # Delegate straight to search_zynd_personas rather than duplicating
        # its full-catalog ranking logic here — two independent
        # implementations of "persona search" is exactly what let this tool
        # and search_zynd_personas silently drift apart and behave
        # inconsistently (one bio-aware, one registry-keyword-only) for the
        # same kind of ask. Delegating makes that impossible by construction.
        inner = search_zynd_personas(query=raw_query, top_k=top_k, user_id=user_id)
        if inner.get("status") == "error":
            return {
                "status": "error",
                "error": inner.get("error", "Persona search failed"),
                "error_message": inner.get("error_message") or "I couldn't complete the persona search.",
                "hint": inner.get("hint") or "Try a different phrasing.",
                "results": [],
                "count": 0,
                "query_used": raw_query,
            }
        results = [
            {
                "name": p.get("name") or "",
                "entity_id": p.get("agent_id") or "",
                "kind": "persona",
                "entity_type": "persona",
                "summary": p.get("description") or "",
                "category": "persona",
                "tags": ["persona"],
                "url": p.get("webhook_url") or "",
                "status": "active",
                "avatar_url": p.get("avatar_url"),
                "match_reason": p.get("match_reason", ""),
            }
            for p in inner.get("results", [])
        ]
        return {
            "status": "success",
            "count": len(results),
            "total_available": inner.get("total_available", len(results)),
            "by_kind": {"persona": inner.get("total_available", len(results))} if results else {},
            "results": results,
            "source": inner.get("source", "registry"),
            "query_used": raw_query,
        }

    # Catch-all asks ("what agents are on the network", "show me everything",
    # "list all agents") carry no real keyword — the registry's keyword search
    # returns ~nothing for them, but an EMPTY query returns the broad catalog.
    # Detect these and search broad instead of normalizing the prose to junk.
    q_lower = raw_query.lower()
    _CATCHALL = {
        "", "*", "all", "any", "anything", "everything", "everyone",
        "agents", "agent", "services", "service", "personas", "network",
        "list", "catalog", "directory",
    }
    _CATCHALL_TOKENS = {
        "agents", "agent", "services", "service", "everything", "anything",
        "all", "available", "network", "catalog", "directory", "list",
    }
    is_catchall = (
        q_lower in _CATCHALL
        or set(re.findall(r"[a-z]+", q_lower)).issubset(_CATCHALL_TOKENS | {"on", "the", "what", "are", "is", "show", "me", "find", "get"})
    )

    if is_catchall:
        # Empty query → broad catalog; skip the keyword fallbacks below.
        cleaned = ""
        raw, err = _call_registry_search("", kind, top_k)
        query_used = ""
    else:
        # Try the normalized form first.
        cleaned = _normalize_query(raw_query)
        query_used = cleaned or raw_query
        raw, err = _call_registry_search(query_used, kind, top_k)

    # Fallback 1: if normalization produced zero hits but the raw query
    # was different, try the raw form (sometimes the user typed an exact
    # agent name and we shouldn't have trimmed it).
    if not raw and not err and cleaned and cleaned != raw_query:
        raw, err = _call_registry_search(raw_query, kind, top_k)
        if raw:
            query_used = raw_query

    # Fallback 2: if still zero, try the FIRST content token alone —
    # broadest meaningful query, catches cases like "competitors" → match
    # "competitor".
    if not raw and not err and cleaned:
        first_token = cleaned.split()[0]
        if first_token and first_token != query_used:
            raw, err = _call_registry_search(first_token, kind, top_k)
            if raw:
                query_used = first_token

    # A registry error is no longer fatal: the deployer can still serve
    # the live catalog. Note the error and fall through to the merge.
    registry_error = err or None

    avatars = _get_avatar_map()
    results: list[dict] = []
    for a in raw:
        aid = a.get("entity_id") or a.get("agent_id") or ""
        if not aid:
            continue
        tags = a.get("tags") or []
        category = a.get("category") or ""
        # The registry's authoritative type field is `entity_type` —
        # exactly "agent" | "service". `category` ("general", "marketing")
        # is a topic label, NOT the entity type, so we must not derive kind
        # from it. Personas are surfaced via the persona tag/category.
        entity_type = (a.get("entity_type") or a.get("type") or "").lower()
        is_persona = "persona" in tags or category == "persona" or entity_type == "persona"
        if is_persona:
            row_kind = "persona"
        elif entity_type in ("agent", "service"):
            row_kind = entity_type
        else:
            # Registry didn't tag a type — fall back to a neutral "agent".
            row_kind = "agent"

        # Enforce the caller's requested kind against the real type.
        #
        # `kind="agent"` is a colloquial "show me the autonomous things on
        # the network" ask. Human personas come back as entity_type=agent +
        # category=persona, so a strict `row_kind == "agent"` test silently
        # dropped every persona — the bug behind "only 2 agents". We keep
        # personas here (still tagged kind="persona" so the caller knows
        # they need a connection) and only exclude genuine services.
        if kind == "persona" and not is_persona:
            continue
        if kind == "agent" and row_kind == "service":
            continue
        if kind == "service" and row_kind != "service":
            continue
        # The card URL is in `url` on the search row (with enrich=True);
        # fall back to the older fields for backward compat.
        endpoint = a.get("url") or _agent_url_from_card(a.get("card")) or a.get("service_endpoint") or a.get("entity_url") or ""
        name = a.get("name") or ""
        summary = a.get("summary") or a.get("description") or ""
        results.append({
            "name": name,
            "entity_id": aid,
            "kind": row_kind,
            "entity_type": entity_type or row_kind,
            "summary": summary,
            "category": category,
            "tags": tags[:10],
            "url": endpoint,
            "status": a.get("status") or "",
            "avatar_url": avatars.get(aid),
            "match_reason": _match_reason(query_used or raw_query, name, summary, tags),
        })

    # Supplement with the deployer's running entities. The registry's
    # search index misses agents/services that are live on the deployer
    # but never registered (entityId null), so a registry-only result
    # under-reports the network. `kind` can never be "persona" here — that
    # case returns early via the search_zynd_personas delegation above.
    results = _merge_deployer_entities(results, kind, query_used or raw_query)

    # Never surface the caller's own persona back to them (self-match).
    self_id = _caller_agent_id(user_id)
    if self_id:
        results = [r for r in results if r.get("entity_id") != self_id]

    # `_call_registry_search` widens the pool past top_k for filtered
    # queries, so `results` may exceed what the caller asked for. Report
    # the real catalog size (total_available) so the model can say "I
    # found 20 agents" truthfully, then return at most top_k rows.
    total_available = len(results)
    by_kind: dict[str, int] = {}
    for r in results:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1

    # If the registry errored AND the deployer gave us nothing, surface
    # the error. Otherwise we have live results — report success.
    if registry_error and not results:
        err = friendly_error_message("search the network", registry_error)
        return {
            "status": "error",
            "error": err["error"],
            "error_message": err["error_message"],
            "hint": err["hint"],
            "results": [],
            "count": 0,
            "query_used": query_used,
        }

    has_deployer = any(r.get("source") == "deployer" for r in results)
    source = "registry+deployer" if has_deployer else "registry"

    return {
        "status": "success",
        "count": min(len(results), top_k),
        "total_available": total_available,
        "by_kind": by_kind,
        "results": results[:top_k],
        "source": source,
        "query_used": query_used,
    }

def search_zynd_personas(query: str, top_k: int = 5, user_id: str = "", resolve_webhooks: bool = True) -> dict:
    """
    Search for other people's personas by topic, role, or interest — e.g.
    "AI founders", "product designers", "someone into climate tech".
    Ranked by full-text relevance over each persona's actual bio (title,
    organization, capabilities, interests), not just their name.

    Ranks against the FULL persona catalog (including personas hosted on
    other Zynd deployments, not just this one) — not just whatever the
    registry's own keyword filter happens to surface.

    Use this for topical/role asks about PEOPLE. For a literal name lookup
    ("find Alice") or when you don't know yet whether the target is a
    person or a standalone agent/service, `search_zynd_network` is usually
    the better first call. This tool only ever returns `kind=persona` rows
    — never internal agents or services.

    Args:
        query: Name, keyword, or topic to search for (e.g., 'Alice', 'ZyndAI', 'AI founders').
        top_k: Max results to return.
        user_id: Injected automatically by the orchestrator — do not pass it.
        resolve_webhooks: When False, skip per-candidate agent-card fetches
            for missing webhook_urls (results keep whatever URL the registry
            embedded for free). Public/browsing callers that can't message
            personas pass False to cut ~5s of latency; internal callers
            leave True.

    Returns ``{status, count, total_available, results: [{name, agent_id,
    description, webhook_url, avatar_url, match_reason, match_score}],
    source}``. ``match_reason`` is a short, grounded note on why each
    result matched (e.g. "matched on: founder, ai") — use it when
    explaining results to the principal instead of inventing a reason. If
    it ends with "— missing: <concept>", the candidate only matched PART
    of a multi-concept query (e.g. matched "ai" but not "founder") — say
    so plainly ("he's in AI but I don't see him described as a founder")
    rather than presenting it as a solid match. ``match_score`` ranks
    candidates by how much of the query they cover — someone matching
    every concept in the query always scores above someone matching only
    one, regardless of raw keyword-count (0 for a catchall/broad browse,
    where every result "matches" by definition). An empty `results` list
    with `status="success"` means a real, complete search came back with
    no relevant match — not a broken search; tell the principal that
    plainly rather than padding the answer with loose matches.
    """
    self_id = _caller_agent_id(user_id)
    catchall_phrases = {
        "", "*", "all", "any", "anyone", "everybody", "everyone",
        "people", "person", "persons", "personas", "agents", "agent",
        "network", "list", "users", "user", "members", "member",
        "available", "anyone available", "who is available", "who's available",
    }
    catchall_tokens = {
        "people", "person", "persons", "personas", "everyone", "anyone",
        "everybody", "agents", "users", "members", "network", "available",
    }
    original_query = query
    q_norm = (query or "").lower().strip()
    is_catchall = q_norm in catchall_phrases or bool(
        set(re.findall(r"[a-z]+", q_norm)) & catchall_tokens
    )

    avatars = _get_avatar_map()

    # Local full-text search — the best signal for OUR own locally-hosted
    # personas' bios (search_personas_fts is weighted over name,
    # description, title, organization, capabilities, and interests).
    try:
        local_matches = [] if is_catchall else _local_persona_fallback(original_query, top_k, avatars)
    except Exception as e:
        logger.warning(f"[zynd_network] local persona search failed: {e!r}")
        local_matches = []
    if self_id:
        local_matches = [p for p in local_matches if p.get("agent_id") != self_id]

    # Registry pass — ALWAYS fetches the broad/full persona catalog rather
    # than sending it the topical query. The registry only keyword-matches
    # name/tags/category (see `_normalize_query`'s docstring); it has no
    # visibility into bio content, so a filtered query like "AI founders"
    # silently drops every persona hosted on OTHER Zynd deployments — we
    # have no local copy of their bio to fall back on the way we do for
    # our own users. `enrich=True` gives each candidate's `summary`
    # though, so instead we fetch everyone tagged persona and rank them
    # ourselves against the query below.
    registry_matched: list[dict] = []
    registry_error: str | None = None
    try:
        resp = requests.post(
            f"{config.ZYND_REGISTRY_URL}/v1/search",
            json={
                "query": "persona",
                "tags": ["persona"],
                "max_results": max(int(top_k), _REGISTRY_POOL_FLOOR),
                "enrich": True,  # include summary + the full AgentCard inline
                "status": "any",  # don't filter out agents whose heartbeat is mid-cycle
            },
            timeout=10,
        )
        resp.raise_for_status()
        for a in resp.json().get("results", []):
            caps = a.get("capability_summary") or a.get("capabilities") or {}
            if isinstance(caps, str):
                try:
                    caps = json.loads(caps)
                except Exception:
                    caps = {}
            tags = a.get("tags", [])
            is_persona = "persona" in tags
            if not is_persona and isinstance(caps, dict):
                is_persona = "persona" in caps.get("services", []) or "persona" in caps.get("skills", [])
            if not is_persona:
                continue
            aid = a.get("entity_id") or a.get("agent_id") or ""
            if not aid or (self_id and aid == self_id):
                continue
            registry_matched.append(a)
    except requests.exceptions.Timeout:
        registry_error = "Registry timed out."
        logger.warning("[zynd_network] persona registry search timed out")
    except Exception as e:
        registry_error = f"Registry search failed: {e}"
        logger.warning(f"[zynd_network] persona registry search failed: {e!r}")

    # Score every candidate (local + registry) against the query with the
    # same keyword-overlap logic, so ranking is apples-to-apples regardless
    # of source — the registry's own ordering doesn't apply once we bypass
    # its keyword filter above. Catchall/broad asks ("show me everyone")
    # skip scoring entirely: everyone qualifies, order doesn't matter.
    # scored items: (score, reason, raw_dict, is_already_shaped)
    scored: list[tuple[int, str, dict, bool]] = []
    seen_ids: set[str] = set()

    for p in local_matches:
        aid = p.get("agent_id") or ""
        if not aid or aid in seen_ids:
            continue
        if is_catchall:
            score, reason = 0, ""
        else:
            score, reason = _match_score(original_query, p.get("name", ""), p.get("description", ""))
        scored.append((score, reason, p, True))
        seen_ids.add(aid)

    for a in registry_matched:
        aid = a.get("entity_id") or a.get("agent_id") or ""
        if not aid or aid in seen_ids:
            continue
        name = a.get("name") or ""
        description = a.get("summary") or a.get("description") or ""
        if is_catchall:
            score, reason = 0, ""
        else:
            score, reason = _match_score(original_query, name, description, a.get("tags"))
            if score == 0:
                continue  # no textual relevance — drop rather than pad with noise
        scored.append((score, reason, a, False))
        seen_ids.add(aid)

    if not is_catchall:
        scored.sort(key=lambda t: t[0], reverse=True)

    # Resolve webhooks only for the rows we're actually about to return.
    combined: list[dict] = []
    for score, reason, item, is_local in scored[:top_k]:
        if is_local:
            item["match_reason"] = reason
            item["match_score"] = score
            combined.append(item)
            continue
        a = item
        aid = a.get("entity_id") or a.get("agent_id") or ""
        webhook = _agent_url_from_card(a.get("card")) or a.get("service_endpoint") or a.get("entity_url") or ""
        # Resolving a missing webhook costs one network round-trip PER
        # candidate (agent-card fetch, 10s timeout each) — that's the
        # dominant latency of this search (~5s for 5 results). Callers
        # that can't message personas anyway (public API, browsing) pass
        # resolve_webhooks=False and skip it entirely.
        if not webhook and resolve_webhooks:
            webhook = _agent_url_from_card(_fetch_agent_card(aid))
        if not webhook and resolve_webhooks:
            try:
                sb = _get_supabase()
                local_row = sb.table("persona_agents").select("webhook_url").eq("agent_id", aid).execute()
                if local_row.data:
                    webhook = local_row.data[0].get("webhook_url", "")
            except Exception:
                pass
        combined.append({
            "name": a.get("name") or "",
            "agent_id": aid,
            "description": a.get("summary") or a.get("description", ""),
            "webhook_url": webhook,
            "avatar_url": avatars.get(aid),
            "match_reason": reason,
            "match_score": score,
        })

    if not combined:
        if registry_error and not local_matches:
            err = friendly_error_message("search for personas", registry_error)
            return {
                "status": "error",
                "error": err["error"],
                "error_message": err["error_message"],
                "hint": err["hint"],
                "results": [],
                "count": 0,
            }
        return {"status": "success", "count": 0, "results": [], "source": "none"}

    source = (
        "local+registry" if local_matches and registry_matched
        else "local_db" if local_matches
        else "registry"
    )
    return {
        "status": "success",
        "count": len(combined),
        "total_available": len(scored),
        "results": combined,
        "source": source,
    }

def _interest_stems(persona_row: dict) -> set[str]:
    """Stemmed keyword set for a persona row's capabilities ∪ interests.

    Mirrors api/matches.py's interest extraction, but tokenized + stemmed
    so it can be matched against a free-text query by the same
    _stem/_QUERY_STOPWORDS machinery _match_score uses.
    """
    caps = persona_row.get("capabilities") or []
    profile = persona_row.get("profile") or {}
    raw = profile.get("interests")
    if isinstance(raw, str):
        ints = [s.strip() for s in raw.split(",") if s.strip()]
    elif isinstance(raw, list):
        ints = [str(s).strip() for s in raw if s]
    else:
        ints = []
    stems: set[str] = set()
    for item in [str(x) for x in (list(caps) + ints)]:
        for w in re.findall(r"[a-z]+", item.lower()):
            if w not in _QUERY_STOPWORDS and len(w) >= 2:
                stems.add(_stem(w))
    return stems


def search_similar_people(query: str, top_k: int = 10) -> dict:
    """
    Find personas SIMILAR to a free-text description of a person or focus
    area — e.g. "AI startup founder building agent infrastructure".

    The query text IS the comparison basis (no logged-in user required):
    each active persona is ranked by how much of the query their declared
    capabilities + profile.interests cover, with bio/name text-relevance
    (_match_score) as a tiebreaker and a fallback when nothing overlaps.

    Args:
        query: Free-text description of the kind of person to find.
        top_k: Max results to return (1–40).

    Returns ``{status, count, total_available, results: [{name, agent_id,
    description, avatar_url, match_reason, match_score}], source}`` —
    the same shape as search_zynd_personas so API + MCP consumers handle
    both identically. ``match_reason`` says what overlapped (e.g.
    "similar focus: ai, founder") or falls back to text-match reasons.
    """
    top_k = max(1, min(int(top_k or 10), 40))

    q_tokens = {
        _stem(t) for t in re.findall(r"[a-z]+", (query or "").lower())
        if t not in _QUERY_STOPWORDS and len(t) >= 2
    }
    if not q_tokens:
        return {"status": "success", "count": 0, "total_available": 0, "results": [], "source": "local_db"}

    sb = _get_supabase()
    try:
        rows = (
            sb.table("persona_agents")
            .select("agent_id,name,description,capabilities,profile")
            .eq("active", True)
            .execute()
        ).data or []
    except Exception as e:
        logger.warning(f"[zynd_network] similar-people query failed: {e!r}")
        err = friendly_error_message("search for similar people", str(e))
        return {
            "status": "error",
            "error": err["error"],
            "error_message": err["error_message"],
            "hint": err["hint"],
            "results": [],
            "count": 0,
        }

    avatars = _get_avatar_map()

    scored: list[tuple[float, int, list[str], dict]] = []
    for r in rows:
        aid = r.get("agent_id") or ""
        if not aid:
            continue
        interests = _interest_stems(r)
        hits = sorted(q_tokens & interests)
        coverage = len(hits) / len(q_tokens)
        text_score, text_reason = _match_score(query, r.get("name", ""), r.get("description", ""))
        if coverage == 0.0 and text_score == 0:
            continue
        scored.append((coverage, text_score, hits, r))

    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)

    results = []
    for coverage, text_score, hits, r in scored[:top_k]:
        if coverage > 0:
            reason = f"similar focus: {', '.join(hits)}"
            if coverage < 1.0:
                missing = sorted(q_tokens - set(hits))
                if missing:
                    reason += f" — missing: {', '.join(missing[:2])}"
            score = round(coverage * 100) + text_score
        else:
            _, reason = _match_score(query, r.get("name", ""), r.get("description", ""))
            score = text_score
        results.append({
            "name": r.get("name") or "",
            "agent_id": r.get("agent_id") or "",
            "description": r.get("description") or "",
            "avatar_url": avatars.get(r.get("agent_id") or ""),
            "match_reason": reason,
            "match_score": score,
        })

    return {
        "status": "success",
        "count": len(results),
        "total_available": len(scored),
        "results": results,
        "source": "local_db",
    }

def _local_persona_fallback(query: str, top_k: int, avatars: dict[str, str]) -> list[dict]:
    """Read active personas from the local DB. Returned shape mirrors
    search_zynd_personas results.

    Tries `search_personas_fts` first — the same weighted, ranked
    full-text search (name/description/title/organization/capabilities/
    interests/brief_content) that powers the dashboard's People page.
    This is the ONLY search path that can match topical/role asks like
    "AI founders" against a bio that says "Co-founder at Lattice Labs" —
    the registry only keyword-matches name/tags/category (see
    `_normalize_query`'s docstring), so it can't see bio content at all.
    Falls back to a plain ILIKE substring match when the RPC errors
    (e.g. migration not yet applied).
    """
    q = (query or "").strip()
    catchall = {"", "*", "persona", "people", "person", "all", "any", "everyone", "anyone", "available"}
    is_specific = bool(q) and q.lower() not in catchall
    try:
        sb = _get_supabase()
        rows_data: list[dict] = []
        if is_specific:
            try:
                result = sb.rpc(
                    "search_personas_fts",
                    {"query_text": q, "result_limit": top_k},
                ).execute()
                rows_data = result.data or []
            except Exception as fts_err:
                logger.warning(f"[zynd_network] persona FTS RPC failed ({fts_err!r}), falling back to ILIKE")

        if not rows_data:
            builder = (
                sb.table("persona_agents")
                .select("agent_id,name,description")
                .eq("active", True)
                .limit(top_k)
            )
            if is_specific:
                pattern = f"%{q}%"
                builder = builder.or_(f"name.ilike.{pattern},description.ilike.{pattern}")
            rows_data = builder.execute().data or []

        if not rows_data:
            return []

        # search_personas_fts doesn't return webhook_url — resolve it with
        # one follow-up query keyed on the agent_ids we actually matched.
        agent_ids = [r["agent_id"] for r in rows_data if r.get("agent_id")]
        webhooks: dict[str, str] = {}
        if agent_ids:
            wh_rows = (
                sb.table("persona_agents")
                .select("agent_id,webhook_url")
                .in_("agent_id", agent_ids)
                .execute()
            )
            webhooks = {r["agent_id"]: r.get("webhook_url") or "" for r in (wh_rows.data or [])}

        return [
            {
                "name": r.get("name") or "",
                "agent_id": r.get("agent_id") or "",
                "description": r.get("description") or "",
                "webhook_url": webhooks.get(r.get("agent_id") or "", ""),
                "avatar_url": avatars.get(r.get("agent_id") or ""),
            }
            for r in rows_data
            if r.get("agent_id")
        ]
    except Exception as e:
        logger.warning(f"[zynd_network] local fallback failed: {e}")
        return []

def _stem(word: str) -> str:
    """Naive plural stripping so "founders" matches a bio's "founder"."""
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def _match_score(query: str, name: str, description: str, tags: list[str] | None = None) -> tuple[int, str]:
    """Score + explain how well `query` matches a candidate's name/bio/tags.

    A multi-concept query like "AI founders" has two independent concepts
    (topic "ai", role "founder"). The old version scored purely by raw
    keyword-overlap count, so a developer whose bio just says "AI" (1 hit)
    could out-rank — or at least crowd the top_k alongside — an actual
    founder (also potentially just 1 hit, if their bio never repeats "AI").
    Neither ever needed to match BOTH concepts to place well.

    This version ranks primarily by *coverage* — the fraction of the
    query's distinct concepts a candidate actually matches — so someone
    matching every concept in the query always outranks someone matching
    only one, however many times that one concept appears in their bio.
    Hits inside `name`/`tags` (curated, higher-signal fields) count for
    more than incidental hits buried in free-text `description`, as a
    tiebreaker within the same coverage tier.

    Returns (score, reason_string). `score` is 0 when nothing textually
    overlaps at all. reason_string is "" in that case too — callers should
    fall back to summarizing the result's own description, not claim a
    keyword match that didn't happen. When coverage is partial (only some
    query concepts matched), the reason notes what's missing so the caller
    can be honest about it being a loose match instead of overselling it.
    """
    # Filter by the same stopword list used for registry-query normalization
    # rather than a raw length cutoff — a length filter would drop short but
    # meaningful domain tokens like "ai" or "vc".
    q_tokens = {
        _stem(t) for t in re.findall(r"[a-z]+", (query or "").lower())
        if t not in _QUERY_STOPWORDS and len(t) >= 2
    }
    if not q_tokens:
        return 0, ""

    name_stems = {_stem(w) for w in re.findall(r"[a-z]+", (name or "").lower())}
    tag_stems = {_stem(w) for w in re.findall(r"[a-z]+", " ".join(tags or []).lower())}
    haystack_words = re.findall(r"[a-z]+", f"{name} {description} {' '.join(tags or [])}".lower())
    stem_to_word: dict[str, str] = {}
    for w in haystack_words:
        stem_to_word.setdefault(_stem(w), w)

    hits: list[str] = []
    hit_stems: list[str] = []
    weight = 0
    for t in q_tokens:
        w = stem_to_word.get(t)
        if not w and len(t) >= 4:
            # Compound-word fallback. Real bios say "cofounder"/"co-founder"
            # far more often than the bare word "founder" — and someone
            # explicitly describing themselves as a cofounder is exactly
            # who a "founders" search is looking for. An exact-stem lookup
            # misses this entirely (the stem of "cofounder" is "cofounder",
            # never "founder"), which was silently zeroing out the
            # strongest candidates in real data. Length-gated to 4+ chars
            # so short/noisy tokens like "ai" or "vc" can't suffix-match
            # into unrelated words (e.g. "ai" inside "mumbai").
            w = next((word for stem, word in stem_to_word.items() if stem != t and stem.endswith(t)), None)
        if not w:
            continue
        hits.append(w)
        hit_stems.append(t)
        weight += 3 if (t in name_stems or t in tag_stems) else 1

    if not hits:
        return 0, ""

    coverage = len(hit_stems) / len(q_tokens)
    # Coverage dominates: each full coverage-tier is worth more than any
    # amount of same-tier weight, so it can only ever act as a tiebreaker
    # between candidates that matched the same fraction of concepts.
    score = round(coverage * 100) + weight

    reason = f"matched on: {', '.join(hits[:3])}"
    if coverage < 1.0 and len(q_tokens) > 1:
        missing = sorted(q_tokens - set(hit_stems))
        if missing:
            reason += f" — missing: {', '.join(missing[:2])}"
    return score, reason


def _match_reason(query: str, name: str, description: str, tags: list[str] | None = None) -> str:
    """Best-effort, honest one-line explanation of why a result matched
    `query` — see `_match_score`."""
    return _match_score(query, name, description, tags)[1]


def get_persona_profile(agent_id: str) -> dict:
    """
    Fetch the full profile of a specific persona from the Zynd Network.
    Use this after discovering a persona to get more details about them.

    Args:
        agent_id: The agent_id of the persona (e.g., 'zns:abc123...').
    """
    # First check if they're a local persona (on our platform) with rich profile
    sb = _get_supabase()
    local = sb.table("persona_agents").select("*").eq("agent_id", agent_id).eq("active", True).execute()
    if local.data:
        p = local.data[0]
        return {
            "status": "success",
            "source": "local",
            "name": p["name"],
            "agent_id": p["agent_id"],
            "description": p["description"],
            "capabilities": p["capabilities"],
            "profile": p.get("profile", {}),
            "webhook_url": p["webhook_url"],
        }

    # Otherwise fetch the full card from the registry
    try:
        card = _fetch_agent_card(agent_id)
        if not card:
            return {
                "error": "Profile not found",
                "error_message": "I couldn't find that persona on the network.",
                "hint": "Double-check the agent ID or run a search.",
            }

        metadata = card.get("metadata") or {}
        return {
            "status": "success",
            "source": "registry",
            "name": metadata.get("name") or card.get("name"),
            "agent_id": card.get("agent_id", agent_id),
            "description": metadata.get("description") or card.get("summary") or "",
            "capabilities": card.get("capabilities") or [],
            "webhook_url": _agent_url_from_card(card),
            "status_text": card.get("status"),
            "last_heartbeat": card.get("last_heartbeat"),
        }
    except Exception as e:
        err = friendly_error("fetch the persona profile", e)
        return {"error": err["error"], "error_message": err["error_message"], "hint": err["hint"]}

# ── Connection Tools ─────────────────────────────────────────────────

def list_my_connections(user_id: str) -> dict:
    """
    List the user's existing network connections (DM threads).
    Shows accepted connections, pending requests, and blocked agents.

    Args:
        user_id: The ID of the user (injected automatically).
    """
    from agent.persona_manager import get_persona_status
    persona = get_persona_status(user_id)
    my_agent_id = persona.get("agent_id")

    sb = _get_supabase()

    identifiers = [user_id]
    if my_agent_id:
        identifiers.append(my_agent_id)

    # Fetch all threads where user participates
    threads = []
    for ident in identifiers:
        r1 = sb.table("dm_threads").select("*").eq("initiator_id", ident).execute()
        r2 = sb.table("dm_threads").select("*").eq("receiver_id", ident).execute()
        threads.extend(r1.data or [])
        threads.extend(r2.data or [])

    # Deduplicate by thread id
    seen = set()
    unique = []
    for t in threads:
        if t["id"] not in seen:
            seen.add(t["id"])
            partner_id = t["receiver_id"] if t["initiator_id"] in identifiers else t["initiator_id"]
            partner_name = t["receiver_name"] if t["initiator_id"] in identifiers else t["initiator_name"]
            unique.append({
                "thread_id": t["id"],
                "partner_agent_id": partner_id,
                "partner_name": partner_name or "Unknown",
                "status": t["status"],
                "initiated_by_me": t["initiator_id"] in identifiers,
                "created_at": t["created_at"],
            })

    accepted = [c for c in unique if c["status"] == "accepted"]
    pending = [c for c in unique if c["status"] == "pending"]

    return {
        "status": "success",
        "my_agent_id": my_agent_id,
        "connections": accepted,
        "pending_requests": pending,
        "total_accepted": len(accepted),
        "total_pending": len(pending),
    }

def request_connection(user_id: str, target_agent_id: str, target_name: str = "Network Agent") -> dict:
    """
    Initiate a new connection (DM thread) with another persona on the Zynd Network.
    This sends a connection request that the other persona can accept or decline.

    Args:
        user_id: The ID of the user (injected automatically).
        target_agent_id: The agent_id of the persona you want to connect with.
        target_name: The display name of the target persona.
    """
    from agent.persona_manager import get_persona_status
    persona = get_persona_status(user_id)
    my_agent_id = persona.get("agent_id")
    my_name = persona.get("name", "Zynd Agent")

    if not my_agent_id:
        return {
            "error": "No deployed persona",
            "error_message": "You need a persona before you can request connections.",
            "hint": "Finish onboarding in the Zynd dashboard first.",
        }

    sb = _get_supabase()

    # Check if thread already exists
    r1 = sb.table("dm_threads").select("*").eq("initiator_id", my_agent_id).eq("receiver_id", target_agent_id).execute()
    r2 = sb.table("dm_threads").select("*").eq("initiator_id", target_agent_id).eq("receiver_id", my_agent_id).execute()
    existing = (r1.data or []) + (r2.data or [])

    if existing:
        t = existing[0]
        return {
            "status": "already_exists",
            "thread_id": t["id"],
            "connection_status": t["status"],
            "message": f"You already have a {t['status']} Zynd Network connection with {target_name}.",
        }

    # Create new thread in 'agent' mode — the AI initiated it, so the AI
    # should keep handling replies until the user explicitly takes over.
    result = sb.table("dm_threads").insert({
        "initiator_id": my_agent_id,
        "receiver_id": target_agent_id,
        "initiator_name": my_name,
        "receiver_name": target_name,
        "status": "pending",
        "initiator_mode": "agent",
    }).execute()

    if result.data:
        # Broadcast notification
        sb_anon = config.get_supabase_anon()
        try:
            sb_anon.channel("system_pings").send({
                "type": "broadcast",
                "event": "new_thread",
                "payload": {
                    "receiver_id": target_agent_id,
                    "initiator_id": my_agent_id,
                },
            })
        except Exception:
            pass

        return {
            "status": "success",
            "thread_id": result.data[0]["id"],
            "thread_mode": "agent",
            "partner_name": target_name,
            "partner_agent_id": target_agent_id,
            "message": f"Zynd Network connection request sent to {target_name}. They'll need to accept it on the Zynd Network — note this is a Zynd connection, not a LinkedIn invitation.",
        }

    return {
        "error": "Couldn't send the connection request",
        "error_message": "Something went wrong while creating the connection thread.",
        "hint": "Please try again in a moment.",
    }

def check_connection_status(user_id: str, target_agent_id: str) -> dict:
    """
    Check if the user is connected to a specific persona.

    Args:
        user_id: The ID of the user (injected automatically).
        target_agent_id: The agent_id of the persona to check.
    """
    from agent.persona_manager import get_persona_status
    persona = get_persona_status(user_id)
    my_agent_id = persona.get("agent_id")

    if not my_agent_id:
        return {"connected": False, "status": "no_persona", "message": "You haven't deployed a persona yet."}

    sb = _get_supabase()
    r1 = sb.table("dm_threads").select("*").eq("initiator_id", my_agent_id).eq("receiver_id", target_agent_id).execute()
    r2 = sb.table("dm_threads").select("*").eq("initiator_id", target_agent_id).eq("receiver_id", my_agent_id).execute()
    threads = (r1.data or []) + (r2.data or [])

    if not threads:
        return {"connected": False, "status": "no_thread", "message": "No connection exists with this agent."}

    t = threads[0]
    return {
        "connected": t["status"] == "accepted",
        "status": t["status"],
        "thread_id": t["id"],
        "initiated_by_me": t["initiator_id"] == my_agent_id,
    }

# ── Messaging Tool ───────────────────────────────────────────────────

def _persona_signer(user_id: str):
    """Return ``(keypair, agent_id, developer_proof)`` for the user's active
    persona, or ``None`` when there's no active persona.

    Reconstructs the keypair via the same HD-derivation path
    persona_manager.startup uses on rehydration (microseconds — nothing is
    persisted). Used by every signed outbound call so the x-zynd-auth block
    is built from one place.
    """
    from agent.persona_manager import _derive_agent_keypair, _load_developer_seed
    from agent.zynd_identity import keypair_from_seed, build_derivation_proof

    sb = _get_supabase()
    row = (
        sb.table("persona_agents")
        .select("agent_id,derivation_index")
        .eq("user_id", user_id)
        .eq("active", True)
        .execute()
    )
    if not row.data:
        return None
    index = row.data[0]["derivation_index"]
    agent_id = row.data[0]["agent_id"]

    dev_seed = _load_developer_seed()
    private_seed, public_key_bytes = _derive_agent_keypair(dev_seed, index)
    keypair = keypair_from_seed(private_seed)
    # Carry developer_proof on every send for now — bytes are cheap and the
    # receiver may require it on first contact within a context.
    developer_proof = build_derivation_proof(dev_seed, public_key_bytes, index)
    return keypair, agent_id, developer_proof

def _classify_transport_error(e: Exception) -> str:
    """Turn a raw transport exception into a specific, plain-language reason
    instead of the generic "network request failed" every transport failure
    used to collapse into regardless of what actually happened — a timeout,
    an offline peer, and a 500 from their server all need different things
    said to the user (and possibly different next steps), not one blanket
    "couldn't be delivered, try again"."""
    import httpx

    if isinstance(e, httpx.ConnectTimeout):
        return "timed out trying to connect to their persona's server"
    if isinstance(e, httpx.ReadTimeout):
        return "connected, but their persona's server didn't respond in time"
    if isinstance(e, httpx.TimeoutException):
        return "timed out waiting on their persona's server"
    if isinstance(e, httpx.ConnectError):
        return "couldn't reach their persona's server — it may be offline or unreachable"
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status >= 500:
            return f"their persona's server returned an error (HTTP {status})"
        if status == 404:
            return "their persona's server endpoint wasn't found (HTTP 404) — it may have moved or been taken down"
        if status in (401, 403):
            return f"their persona's server rejected the request (HTTP {status})"
        return f"their persona's server returned HTTP {status}"
    if isinstance(e, httpx.RemoteProtocolError):
        return "the connection was interrupted mid-request"
    if isinstance(e, httpx.HTTPError):
        return f"a network error ({type(e).__name__})"
    return f"an unexpected error ({type(e).__name__}: {e})"


def _signed_a2a_send(
    *,
    sender_agent_id: str,
    sender_user_id: str,
    target_agent_id: str,
    peer_a2a_url: str,
    peer_card_url: Optional[str],
    context_id: str,
    text: str = "",
    data: "Any" = None,
    intent=None,
    hints=None,
    origin_kind: str = "mcp_tool",
    origin_ref: Optional[dict] = None,
) -> dict:
    """Sign one A2A v3 message with the sender persona's derived keypair and
    dispatch it to `peer_a2a_url`. Wire-only — the caller owns URL
    resolution, DB writes, and prompt shaping.

    Returns one of:
      * ``{"error": ...}`` — pre-flight failure (no persona keypair).
      * ``{"status": "delivery_failed", ...}`` — A2A reject / transport error.
      * success base ``{"task", "task_state", "reply_text", "transport"}``,
        plus ``callback_id``/``pending``/``message`` when transport was PUSH.

    `mcp_server._call` runs tools synchronously, so the async client is
    hosted in asyncio.run() per call (fresh event loop, microsecond overhead).
    """
    from agent.a2a.client import A2AClient, A2AError, extract_reply_text
    from agent.a2a.transport import dispatch, Intent, Transport, infer_intent

    signer = _persona_signer(sender_user_id)
    if signer is None:
        return {"error": "Sender persona not found or inactive."}
    keypair, _signer_agent_id, developer_proof = signer

    client = A2AClient(
        keypair=keypair,
        entity_id=sender_agent_id,
        developer_proof=developer_proof,
    )

    if intent is None:
        intent = infer_intent(target_agent_id)

    async def _go() -> tuple[dict, Transport, Optional[str]]:
        result = await dispatch(
            client,
            peer_entity_id=target_agent_id,
            peer_a2a_url=peer_a2a_url,
            peer_card_url=peer_card_url,
            user_id=sender_user_id,
            thread_id=context_id,
            context_id=context_id,
            text=text,
            data=data,
            intent=intent,
            hints=hints,
            origin_kind=origin_kind,
            origin_ref=origin_ref or {},
        )
        return (result.task or {}), result.transport, result.callback_id

    try:
        task, transport_used, callback_id = asyncio.run(_go())
    except A2AError as e:
        # Translate the receiver's named error reason into a structured
        # tool result so the LLM can refuse / retry / escalate cleanly.
        return {
            "status": "delivery_failed",
            "reply_status": "rejected",
            "thread_id": context_id,
            "partner_agent_id": target_agent_id,
            "error_code": e.code,
            "error_reason": e.reason,
            "message": (
                f"The receiver rejected the message ({e.code}): {e.message}. "
                f"Tell the user what blocked it (reason: {e.reason or 'unspecified'}) "
                f"and offer a next step."
            ),
        }
    except Exception as e:
        # Transport failure (DNS, TLS, 5xx, timeout, offline peer, etc.).
        # Same shape as above so the LLM's existing prompt branches still
        # work, but reason is now specific (see _classify_transport_error)
        # instead of every kind of failure collapsing into one generic
        # "network request failed, try again".
        reason = _classify_transport_error(e)
        return {
            "status": "delivery_failed",
            "reply_status": "transport_error",
            "thread_id": context_id,
            "partner_agent_id": target_agent_id,
            "failure_reason": reason,
            "message": (
                f"The message couldn't be delivered — {reason}. Tell the user "
                f"that specific reason, not a generic 'it failed', and offer "
                f"to retry."
            ),
        }

    state = ((task.get("status") or {}).get("state")) or "unknown"
    reply_text = extract_reply_text(task)
    base = {
        "task": task,
        "task_state": state,
        "reply_text": reply_text,
        "transport": transport_used.value,
    }
    if transport_used == Transport.PUSH:
        # The receiver acked our message but the reply will arrive later
        # via push notification. Tell the LLM the message is in flight
        # and not to keep waiting in the same tool loop.
        base["callback_id"] = callback_id
        base["pending"] = True
        base["message"] = (
            "The message was delivered. The other agent is processing it — "
            "their reply will arrive asynchronously and surface in the chat "
            "when it's ready. Tell the user you've sent the message and "
            "they'll see the response come in shortly."
        )
    return base

def _send_via_a2a_v3(
    sender_agent_id: str,
    sender_user_id: str,
    target_agent_id: str,
    target_webhook_url: str,
    context_id: str,
    message_text: str,
) -> dict:
    """Resolve a partner persona's stored URL to its v3 A2A endpoint and
    sign+dispatch a message to it. Thin wrapper over ``_signed_a2a_send`` —
    the persona path stores either a legacy webhook or a v3 URL, so URL
    resolution happens here before the shared wire send."""
    from agent.a2a.client import resolve_a2a_url, resolve_card_url

    # Resolve the v3 URL from whatever's stored on persona_agents.
    # Personas registered before phase 4.1 store the legacy webhook URL;
    # newer ones store the v3 URL directly. The resolver handles both.
    a2a_url = resolve_a2a_url(target_webhook_url)
    if not a2a_url:
        return {
            "error": "Can't reach this persona",
            "error_message": "I couldn't resolve a working chat address from their stored details.",
            "hint": "Try searching for them again to refresh their address.",
        }
    # Card sits at `{base}/.well-known/agent-card.json` — sibling of the
    # A2A endpoint, derived from the same stored URL.
    card_url = resolve_card_url(target_webhook_url)

    return _signed_a2a_send(
        sender_agent_id=sender_agent_id,
        sender_user_id=sender_user_id,
        target_agent_id=target_agent_id,
        peer_a2a_url=a2a_url,
        peer_card_url=card_url,
        context_id=context_id,
        text=message_text,
        origin_kind="mcp_tool",
        origin_ref={"thread_id": context_id, "tool": "message_zynd_agent"},
    )

def _message_exists_on_thread(
    thread_id: str,
    sender_agent_id: str,
    content: str,
    window_minutes: int = 10,
) -> bool:
    """Return True if an identical agent-channel message was already sent
    by this persona on the thread within the recent window.

    Prevents the same follow-up from being dispatched twice when the LLM
    retries or re-emits the same message on a later turn.
    """
    sb = _get_supabase()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()
        rows = (
            sb.table("dm_messages")
            .select("content")
            .eq("thread_id", thread_id)
            .eq("sender_id", sender_agent_id)
            .eq("sender_type", "agent")
            .eq("channel", "agent")
            .gte("created_at", cutoff)
            .execute()
        )
        normalized = " ".join(content.split())
        for r in rows.data or []:
            if " ".join((r.get("content") or "").split()) == normalized:
                return True
    except Exception as e:
        logger.warning("[zynd_network] duplicate-message check failed for thread %s: %s", thread_id, e)
    return False


def message_zynd_agent(user_id: str, target_webhook_url: str, target_agent_id: str, message: str) -> dict:
    """
    Send a structured message to another user's persona on the Zynd network
    via the A2A v0.3 JSON-RPC transport.

    Use `search_zynd_personas` first to find the target's URL. The
    registry stores the persona's base URL; we derive the A2A endpoint
    (`{base}/a2a/v1`) and card URL automatically via ``resolve_a2a_url``
    — it also still understands pre-fix `/a2a/v1` URLs and legacy v2
    webhook URLs from older personas.

    Args:
        user_id: The ID of the user sending the message (injected automatically).
        target_webhook_url: The stored URL of the agent you want to message
                            (base URL or a pre-fix `/a2a/v1` URL — both work).
        target_agent_id: The agent_id of the agent you are messaging.
        message: The natural language request you are sending to the other agent.
    """
    from agent.persona_manager import get_persona_status

    persona = get_persona_status(user_id)
    sender_agent_id = persona.get("agent_id")
    if not sender_agent_id:
        return {
            "error": "No deployed persona",
            "error_message": "You need a persona before sending network messages.",
            "hint": "Finish onboarding in the Zynd dashboard first.",
        }

    if not target_webhook_url:
        return {
            "error": "Recipient can't be reached",
            "error_message": "That persona doesn't have a reachable address on the network.",
            "hint": "Try searching for them again or use a different contact method.",
        }

    log_prefix = f"[message_zynd_agent {sender_agent_id[:12]}→{target_agent_id[:12]}]"

    # Look up the dm_thread (contextId is the dm_threads.id per design C-1).
    sb = _get_supabase()
    r1 = (
        sb.table("dm_threads")
        .select("id,status")
        .in_("initiator_id", [sender_agent_id, user_id])
        .eq("receiver_id", target_agent_id)
        .execute()
    )
    r2 = (
        sb.table("dm_threads")
        .select("id,status")
        .eq("initiator_id", target_agent_id)
        .in_("receiver_id", [sender_agent_id, user_id])
        .execute()
    )
    thread = (r1.data or r2.data or [None])[0]
    if not thread:
        return {
            "error": "No connection thread",
            "error_message": "You aren't connected with this persona yet.",
            "hint": "Send a connection request first and wait for them to accept.",
        }
    thread_id = thread["id"]
    thread_status = thread.get("status") or "pending"
    if thread_status not in ("accepted",):
        return {
            "error": f"Connection is {thread_status}",
            "error_message": "You can only message accepted connections.",
            "hint": "Wait for the other side to accept your request, or send a fresh connection request.",
            "thread_id": thread_id,
        }

    # Duplicate guard: don't send the exact same agent-channel message twice
    # on the same thread within the recent window.
    if _message_exists_on_thread(thread_id, sender_agent_id, message):
        logger.info(f"{log_prefix} duplicate message detected; skipping send")
        return {
            "status": "duplicate",
            "error_message": "This exact message was already sent on this thread recently.",
            "thread_id": thread_id,
            "partner_agent_id": target_agent_id,
        }

    # Insert outbound to dm_messages BEFORE the send (M-1: persist before
    # dispatch). Both participants see it immediately via Supabase realtime.
    inserted_message_id = None
    try:
        ins = sb.table("dm_messages").insert({
            "thread_id": thread_id,
            "sender_id": sender_agent_id,
            "sender_type": "agent",
            "channel": "agent",
            "content": message,
        }).execute()
        rows = ins.data or []
        if rows:
            inserted_message_id = rows[0].get("id")
    except Exception as e:
        logger.warning(f"{log_prefix} sender-side dm_messages insert failed: {e}")

    # Snapshot the time so the proposal lookup below can scope to "during
    # this exchange". (Receiver's orchestrator may have created an
    # agent_tasks meeting row while serving the request.)
    send_time_iso = datetime.now(timezone.utc).isoformat()

    def _rollback_optimistic_insert() -> None:
        # A failed dispatch means the receiver never saw this message —
        # the optimistic row above would otherwise linger as a phantom
        # "sent" bubble in both UIs AND poison _message_exists_on_thread's
        # dedup window, permanently blocking a corrected retry (e.g. after
        # the LLM fixes a bad URL on the next attempt). Seen live: a first
        # attempt with a hallucinated webhook URL failed pre-flight but had
        # already persisted the row; 20s later the retry with the correct
        # URL was silently swallowed as a "duplicate" and never dispatched.
        if inserted_message_id is not None:
            try:
                sb.table("dm_messages").delete().eq("id", inserted_message_id).execute()
            except Exception as e:
                logger.warning(f"{log_prefix} rollback of optimistic dm_messages insert failed: {e}")

    # ── The actual A2A v3 call ──────────────────────────────────────
    delivery = _send_via_a2a_v3(
        sender_agent_id=sender_agent_id,
        sender_user_id=user_id,
        target_agent_id=target_agent_id,
        target_webhook_url=target_webhook_url,
        context_id=thread_id,
        message_text=message,
    )
    if "error" in delivery and "task" not in delivery:
        # Pre-flight failure (no v3 URL, missing keypair, etc.) — pass
        # the error to the LLM so it can explain to the user.
        _rollback_optimistic_insert()
        delivery["thread_id"] = thread_id
        delivery["partner_agent_id"] = target_agent_id
        return delivery

    # `_send_via_a2a_v3` may have returned a `delivery_failed` shape
    # (network or receiver-rejection); pass it through verbatim — the
    # LLM's prompts already know how to phrase those.
    if delivery.get("status") == "delivery_failed":
        _rollback_optimistic_insert()
        return delivery

    task = delivery["task"]
    task_state = delivery["task_state"]
    reply_text = delivery["reply_text"]

    # ── Recent agent_tasks (meeting) lookup ─────────────────────────
    # Even with synchronous reply we keep this — the receiver's
    # orchestrator may have staged a propose_meeting via the approval
    # gate, which lands in pending_approvals; if/when the user approves,
    # an agent_tasks row will appear. We surface any rows created during
    # this exchange so the LLM doesn't issue a duplicate proposal.
    recent_proposals: list[dict] = []
    try:
        pr = (
            sb.table("agent_tasks")
            .select("id,status,initiator_user_id,recipient_user_id,payload,created_at")
            .eq("thread_id", thread_id)
            .eq("type", "meeting")
            .gte("created_at", send_time_iso)
            .order("created_at", desc=True)
            .execute()
        )
        for row in (pr.data or []):
            payload = row.get("payload") or {}
            recent_proposals.append({
                "task_id": row["id"],
                "status": row["status"],
                "title": payload.get("title"),
                "start_time": payload.get("start_time"),
                "end_time": payload.get("end_time"),
                "proposed_by_me": row.get("initiator_user_id") == user_id,
            })
    except Exception as e:
        logger.warning(f"{log_prefix} proposal lookup failed (non-fatal): {e}")

    proposal_note = ""
    if recent_proposals:
        peer_created = [p for p in recent_proposals if not p["proposed_by_me"]]
        mine = [p for p in recent_proposals if p["proposed_by_me"]]
        parts = []
        if peer_created:
            parts.append(
                f"IMPORTANT: the other side already created {len(peer_created)} meeting "
                f"proposal(s) on this thread during this exchange. "
                f"DO NOT call propose_meeting — it would be a duplicate. "
                f"Instead tell the user the proposal is waiting for their review in the Meetings tab, "
                f"and offer to accept/counter/decline on their behalf via respond_to_meeting."
            )
        if mine:
            parts.append(f"You already created {len(mine)} proposal(s) on this thread; do not duplicate.")
        proposal_note = " ".join(parts)

    # ── Map task state → reply_status (back-compat with prior shape) ─
    if task_state == "completed":
        reply_status = "reply_received"
        guide = "Reply received from the other agent — quote or paraphrase it for the user as your final answer."
    elif task_state in ("input-required", "auth-required"):
        # Phase 3.4 wires a real loop; phase 3.1 just surfaces the
        # interrupted state so the user sees what's blocking.
        reply_status = "needs_more_info"
        guide = (
            "The other agent paused mid-task and asked for more info. The question is in the reply. "
            "Bring it to the user verbatim and ask what they'd like to do."
        )
    elif task_state == "failed":
        reply_status = "remote_failed"
        guide = "The other agent's handler failed. Tell the user something went wrong on their side and offer to retry."
    elif task_state == "rejected":
        reply_status = "remote_rejected"
        guide = "The other agent refused the request. Tell the user the connection lacks the necessary permission for this action."
    else:
        reply_status = "no_reply_yet"
        guide = (
            "The other agent acknowledged but didn't produce a reply this turn. The reply will "
            "appear in the Agent Activity tab when it arrives — tell the user we're waiting on them."
        )

    result = {
        "status": "success" if task_state == "completed" else "partial",
        "reply_status": reply_status,
        "reply": reply_text,
        "thread_id": thread_id,
        "task_id": task.get("id"),
        "task_state": task_state,
        "partner_agent_id": target_agent_id,
        "recent_proposals": recent_proposals,
        "message": guide,
    }
    if proposal_note:
        result["message"] = proposal_note + " Then, " + result["message"]
    return result

def call_zynd_agent(entity_id: str, text: str = "", data: dict = None, user_id: str = "", conversation_id: str = "") -> dict:
    """
    Invoke a standalone Zynd Network AGENT (not a stateless `zns:svc:` service,
    not a human's persona) over SIGNED A2A v3. Use this for non-persona results
    from ``search_zynd_network`` whose ``kind`` is ``agent`` or a domain
    category (market-intelligence, recruiting, marketing, …) — anything that
    isn't a service and isn't a persona.

    Two ways this differs from ``call_zynd_service``:
      1. It SIGNS the request with your persona's keypair, so agents running
         ``auth_mode=strict`` accept it (a plain service call is rejected).
      2. It dispatches ASYNCHRONOUSLY. Agents take time to run, so when the
         agent supports push notifications the call returns immediately with
         ``status="dispatched"`` and the agent's reply arrives LATER (it
         surfaces in the chat when ready). Do NOT block or re-poll — tell the
         user you've dispatched it and move on.

    No connection request is needed (that's only for personas).

    Returns:
      - ``status="dispatched"`` — async; the agent is running, reply comes
        later via the callback. ``callback_id`` identifies the pending result.
      - ``status="success"|"bad_request"|"remote_failed"|"rejected"|"needs_input"|…``
        — the agent answered (or failed) synchronously because it doesn't
        support push; read ``reply_text`` / ``structured_output`` and follow
        ``hint``.

    Args:
        entity_id: The agent's registry id (from ``search_zynd_network``).
        text: Free-text payload for the message text part.
        data: Structured payload for the message data part (shape per the
              agent's card ``input_schema``).
        user_id: Auto-injected by the orchestrator — the calling user. Needed
                 to derive the signing keypair; a deployed persona is required.
        conversation_id: Auto-injected by the orchestrator — the chat session
                         that triggered this call. Stored so the async reply
                         can be posted back to the right conversation.
    """
    eid = (entity_id or "").strip()
    if not eid:
        return {
            "status": "error",
            "error": "No agent ID provided",
            "error_message": "I need the agent ID to call it.",
            "hint": "Use the entity_id returned by the search or card lookup.",
        }
    if not (user_id or "").strip():
        return {
            "status": "error",
            "entity_id": eid,
            "error": "No deployed persona",
            "error_message": "Calling a network agent requires a deployed persona.",
            "hint": "Finish onboarding in the Zynd dashboard first.",
        }

    has_text = bool((text or "").strip())
    has_data = isinstance(data, dict) and len(data) > 0
    if not has_text and not has_data:
        return {
            "status": "error",
            "entity_id": eid,
            "error": "Nothing to send to the agent",
            "error_message": "An agent call needs either free text (text=) or structured inputs (data=).",
            "hint": "Check the input_schema from the agent card and try again.",
        }

    # Fire-and-forget: resolving the card, signing, and the message/send
    # round-trip are all network calls, and the agent itself runs for
    # seconds-to-minutes. Doing any of that inline would freeze the chat
    # turn, so we hand the whole dispatch to a background thread and return
    # immediately. The agent's reply surfaces later via the push callback →
    # callback_results → chat (ChatContext auto-appends it) and a toast.
    import threading

    threading.Thread(
        target=_dispatch_agent_call_bg,
        args=(eid, text, data if has_data else None, user_id, conversation_id),
        daemon=True,
    ).start()

    return {
        "status": "dispatched",
        "pending": True,
        "entity_id": eid,
        "hint": (
            "Request sent to the agent in the background. Tell the user you've dispatched it "
            "and their answer will appear here automatically when it's ready — do NOT wait, "
            "re-poll, or call the agent again."
        ),
    }

def _dispatch_agent_call_bg(entity_id: str, text: str, data: "Any", user_id: str, conversation_id: str = "") -> None:
    """Background worker for ``call_zynd_agent``: resolve the agent card,
    sign, and dispatch via PUSH off the chat turn so nothing blocks the user.
    The reply returns asynchronously through the push callback path."""
    print(f"[call_zynd_agent bg] started eid={entity_id} user={user_id[:8]}")
    try:
        from agent.a2a.client import resolve_card_url
        from agent.a2a.transport import Intent, Transport, TransportHints
        from mcp.tools.zynd_services import get_zynd_service_card

        print(f"[call_zynd_agent bg] fetching card for {entity_id}")
        card = get_zynd_service_card(entity_id)
        print(f"[call_zynd_agent bg] card status={card.get('status')} url={card.get('url')!r}")
        if card.get("status") != "success":
            print(f"[call_zynd_agent bg] card load failed: {card}")
            logger.warning(
                "call_zynd_agent[bg] card load failed for %s: %s",
                entity_id, card.get("status"),
            )
            return
        peer_a2a_url = card.get("url") or ""
        if not peer_a2a_url:
            print(f"[call_zynd_agent bg] no a2a url on card: {card}")
            logger.warning("call_zynd_agent[bg] agent card has no url: %s", entity_id)
            return
        # The card may resolve a canonical entity_id different from the slug.
        eid = card.get("entity_id") or entity_id
        card_url = resolve_card_url(peer_a2a_url) or f"{config.ZYND_REGISTRY_URL}/v1/entities/{eid}/card"

        print(f"[call_zynd_agent bg] signer lookup for user={user_id[:8]}")
        signer = _persona_signer(user_id)
        if signer is None:
            print(f"[call_zynd_agent bg] no active persona/signer for user={user_id[:8]}")
            logger.warning("call_zynd_agent[bg] no active persona for user=%s", user_id)
            return
        sender_agent_id = signer[1]
        print(f"[call_zynd_agent bg] sending to {peer_a2a_url} as {sender_agent_id[:20]}")

        origin_ref = {"tool": "call_zynd_agent", "entity_id": eid}
        if conversation_id:
            origin_ref["conversation_id"] = conversation_id

        delivery = _signed_a2a_send(
            sender_agent_id=sender_agent_id,
            sender_user_id=user_id,
            target_agent_id=eid,
            peer_a2a_url=peer_a2a_url,
            peer_card_url=card_url,
            context_id=str(uuid.uuid4()),  # standalone agents are stateless to us
            text=text,
            data=data,
            intent=Intent.AGENT_TO_AGENT,
            # Agents run async; PUSH registers a callback and the reply comes
            # back through the push handler. Cards don't reliably advertise
            # pushNotifications, so force it rather than sniff capabilities.
            hints=TransportHints(force=Transport.PUSH),
            origin_kind="mcp_tool",
            origin_ref=origin_ref,
        )
        cb_id = delivery.get("callback_id")
        task = delivery.get("task")
        print(
            f"[call_zynd_agent bg] done: cb={cb_id} transport={delivery.get('transport')} "
            f"task_id={(task or {}).get('id') if isinstance(task, dict) else None}"
        )
        logger.info(
            "call_zynd_agent[bg] dispatched eid=%s transport=%s state=%s cb=%s task=%s",
            eid, delivery.get("transport"), delivery.get("task_state"),
            cb_id, (task or {}).get("id") if isinstance(task, dict) else None,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[call_zynd_agent bg] EXCEPTION: {type(e).__name__}: {e}")
        logger.exception("call_zynd_agent[bg] dispatch failed for %s: %s", entity_id, e)

def read_agent_channel(user_id: str, thread_id: str, limit: int = 20) -> dict:
    """
    Read the most recent agent-channel messages on a DM thread.

    Use this when you need to know what's been said between your agent and
    another agent on a specific connection — e.g. to look up the last thing
    the other side said, check context across multiple turns, or verify
    whether a reply has arrived since your last send. Returns messages
    newest-first.

    Only reads the agent channel (cross-agent and AI-initiated automation
    chatter). Does NOT read the human conversation tab — that's private
    between humans and off-limits to the agent.

    Args:
        user_id: The user whose thread to read (injected automatically).
        thread_id: The dm_threads row id. Get it from list_my_connections
                   or from a prior request_connection / message_zynd_agent
                   result.
        limit: Max number of messages to return (default 20, most recent first).

    Returns a dict with:
        - messages: list of {sender_id, sender_type, content, created_at}
        - thread_id, count, my_agent_id
    """
    from agent.persona_manager import get_persona_status
    persona = get_persona_status(user_id)
    my_agent_id = persona.get("agent_id") if persona.get("deployed") else None

    if not my_agent_id:
        return {
            "error": "No deployed persona",
            "error_message": "I need an active persona to read agent-channel messages.",
            "hint": "Finish onboarding in the Zynd dashboard first.",
        }

    try:
        uuid.UUID(str(thread_id))
    except (ValueError, AttributeError, TypeError):
        return {
            "error": "Invalid thread ID",
            "error_message": f"'{thread_id}' isn't a valid thread ID — it looks truncated or malformed.",
            "hint": "Call list_my_connections to get the real thread_id, don't guess or reuse a shortened ID from earlier context.",
        }

    sb = _get_supabase()

    # Verify the user is a participant of this thread (don't leak other
    # people's agent-channel traffic via a guessed thread_id).
    thread_res = sb.table("dm_threads").select("initiator_id,receiver_id").eq("id", thread_id).execute()
    if not thread_res.data:
        return {
            "error": "Thread not found",
            "error_message": "I couldn't find that conversation thread.",
            "hint": "Check the thread ID and try again.",
        }
    t = thread_res.data[0]
    if my_agent_id not in (t["initiator_id"], t["receiver_id"]):
        return {
            "error": "Not a participant",
            "error_message": "You aren't part of that conversation thread.",
            "hint": "Make sure you're using a thread you belong to.",
        }

    try:
        # Clamp limit to a sensible range
        limit = max(1, min(int(limit or 20), 100))
        r = (
            sb.table("dm_messages")
            .select("sender_id,sender_type,content,created_at")
            .eq("thread_id", thread_id)
            .eq("channel", "agent")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception as e:
        err = friendly_error("read the agent-channel messages", e)
        return {"error": err["error"], "error_message": err["error_message"], "hint": err["hint"]}

    rows = r.data or []

    # Tag each row so the LLM can easily tell self-sent from received.
    messages = []
    for m in rows:
        messages.append({
            "sender_id": m.get("sender_id"),
            "sender_type": m.get("sender_type"),
            "content": m.get("content"),
            "created_at": m.get("created_at"),
            "from_me": m.get("sender_id") == my_agent_id,
        })

    return {
        "status": "success",
        "thread_id": thread_id,
        "count": len(messages),
        "my_agent_id": my_agent_id,
        "messages": messages,
    }
