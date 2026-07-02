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

import asyncio
import json
import logging
import re
import threading
import time
import uuid
from typing import Any, Optional

import requests

import config

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
        return {"status": "error", "error": "No personas found.", "results": [], "count": 0, "source": "none"}

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
    agents — in one search. Use this FIRST when the user asks to find an
    agent, service, persona, or "something that can do X" — without
    knowing whether the target is a human's persona or a standalone agent.

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
               | ``any`` (default). Pick ``any`` when in doubt — the
               result rows are tagged so the caller can branch.

    Returns ``{status, count, results: [{name, entity_id, kind, summary,
    category, tags, url, status}], source, query_used}``. ``query_used``
    echoes the actual string sent to the registry (post-normalization
    or post-broadening) so callers can show the user what was searched.
    """
    raw_query = (query or "").strip()
    top_k = max(1, min(int(top_k or 8), 25))
    kind = (kind or "any").lower().strip()

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
        results.append({
            "name": a.get("name") or "",
            "entity_id": aid,
            "kind": row_kind,
            "entity_type": entity_type or row_kind,
            "summary": a.get("summary") or a.get("description") or "",
            "category": category,
            "tags": tags[:10],
            "url": endpoint,
            "status": a.get("status") or "",
            "avatar_url": avatars.get(aid),
        })

    # Supplement with the deployer's running entities. The registry's
    # search index misses agents/services that are live on the deployer
    # but never registered (entityId null), so a registry-only result
    # under-reports the network. Personas don't live on the deployer, so
    # skip the merge for persona-only asks.
    if kind != "persona":
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
        return {
            "status": "error",
            "error": registry_error,
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


def search_zynd_personas(query: str, top_k: int = 5, user_id: str = "") -> dict:
    """
    Search the Zynd AI Network for other people's agent personas.
    Use this as the FIRST tool when the user asks about finding people, companies, or agents.
    Only returns agents tagged as "persona" to filter out non-persona agents.

    Args:
        query: Name, keyword, or topic to search for (e.g., 'Alice', 'ZyndAI', 'machine learning').
        top_k: Max results to return.
        user_id: Injected automatically by the orchestrator — do not pass it.
    """
    try:
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
        if q_norm in catchall_phrases:
            query = "persona"
        else:
            tokens = set(re.findall(r"[a-z]+", q_norm))
            # If the user asked something like "find all people" or "show me
            # users on the network", drop down to a broad persona search.
            if tokens & catchall_tokens:
                query = "persona"

        print(f"[zynd_network] Searching registry with query: '{query}' (original: '{original_query}')")

        # Widen the pool: the registry caps the candidate pool before
        # applying the persona tag filter, so max_results=top_k starves
        # broad asks (e.g. top_k=5 → 3 personas when 17 exist). Request
        # the floor, then trim to top_k after assembly.
        resp = requests.post(
            f"{config.ZYND_REGISTRY_URL}/v1/search",
            json={
                "query": query,
                "tags": ["persona"],
                "max_results": max(int(top_k), _REGISTRY_POOL_FLOOR),
                "enrich": True,  # include the full AgentCard inline so we get endpoints.invoke
                "status": "any",  # don't filter out agents whose heartbeat is mid-cycle
            },
            timeout=10,
        )
        resp.raise_for_status()

        results = resp.json().get("results", [])

        avatars = _get_avatar_map()

        # Pass 1: collect every persona row (cheap — no webhook resolution).
        matched: list[dict] = []
        for a in results:
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
            if self_id and (a.get("entity_id") or a.get("agent_id")) == self_id:
                continue  # never recommend the caller their own persona
            matched.append(a)

        total_available = len(matched)

        # Pass 2: resolve webhooks ONLY for the top_k rows we actually
        # return — webhook resolution does a card fetch + DB lookup per
        # row (N+1), so we must not run it across the full widened pool.
        personas = []
        for a in matched[:top_k]:
            # Registry switched from `agent_id` to `entity_id` in the new schema;
            # accept either so this works across versions.
            aid = a.get("entity_id") or a.get("agent_id") or ""
            # Prefer webhook from search result's inline card (enrich=true), then service_endpoint,
            # then fall back to a card lookup, then to local DB.
            webhook = _agent_url_from_card(a.get("card")) or a.get("service_endpoint") or a.get("entity_url") or ""
            if not webhook:
                webhook = _agent_url_from_card(_fetch_agent_card(aid))
            if not webhook:
                try:
                    sb = _get_supabase()
                    local = sb.table("persona_agents").select("webhook_url").eq("agent_id", aid).execute()
                    if local.data:
                        webhook = local.data[0].get("webhook_url", "")
                except Exception:
                    pass

            personas.append({
                "name": a.get("name"),
                "agent_id": aid,
                "description": a.get("summary") or a.get("description", ""),
                "webhook_url": webhook,
                "avatar_url": avatars.get(aid),
            })

        if personas:
            return {
                "status": "success",
                "count": len(personas),
                "total_available": total_available,
                "results": personas,
                "source": "registry",
            }

        # Registry returned zero hits. The orchestrator hits this any time it
        # picks a query like "people" or "*" that the registry's FTS can't
        # match against persona descriptions. Fall back to local DB so the
        # user sees real personas instead of an empty-network reply.
        local_personas = _local_persona_fallback(original_query, top_k, avatars)
        if self_id:
            local_personas = [p for p in local_personas if p.get("agent_id") != self_id]
        if local_personas:
            return {"status": "degraded", "count": len(local_personas), "results": local_personas, "source": "local_db"}
        return {"status": "success", "count": 0, "results": [], "source": "registry"}
    except Exception as e:
        # Last-ditch fallback so a transient registry failure still surfaces
        # personas we know about locally.
        try:
            avatars = _get_avatar_map()
            local_personas = _local_persona_fallback(query, top_k, avatars)
            if self_id:
                local_personas = [p for p in local_personas if p.get("agent_id") != self_id]
            if local_personas:
                return {"status": "degraded", "count": len(local_personas), "results": local_personas, "source": "local_db", "warning": str(e)}
        except Exception:
            pass
        return {"error": str(e)}


def _local_persona_fallback(query: str, top_k: int, avatars: dict[str, str]) -> list[dict]:
    """Read active personas from the local DB, narrowed by ILIKE when the
    query is specific. Returned shape mirrors search_zynd_personas results
    (minus webhook resolution — the orchestrator resolves it at thread time).
    """
    q = (query or "").strip()
    try:
        sb = _get_supabase()
        builder = (
            sb.table("persona_agents")
            .select("agent_id,name,description,webhook_url")
            .eq("active", True)
            .limit(top_k)
        )
        catchall = {"", "*", "persona", "people", "person", "all", "any", "everyone", "anyone", "available"}
        if q and q.lower() not in catchall:
            pattern = f"%{q}%"
            builder = builder.or_(f"name.ilike.{pattern},description.ilike.{pattern}")
        rows = builder.execute()
        return [
            {
                "name": r.get("name") or "",
                "agent_id": r.get("agent_id") or "",
                "description": r.get("description") or "",
                "webhook_url": r.get("webhook_url") or "",
                "avatar_url": avatars.get(r.get("agent_id") or ""),
            }
            for r in (rows.data or [])
            if r.get("agent_id")
        ]
    except Exception as e:
        logger.warning(f"[zynd_network] local fallback failed: {e}")
        return []


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
            return {"error": "Agent not found in registry"}

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
        return {"error": str(e)}


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
        return {"error": "You need to deploy a persona first before connecting with others."}

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
            "message": f"You already have a {t['status']} connection with {target_name}.",
        }

    # Create new thread in 'agent' mode — the AI initiated it, so the AI
    # should keep handling replies until the user explicitly takes over.
    result = sb.table("dm_threads").insert({
        "initiator_id": my_agent_id,
        "receiver_id": target_agent_id,
        "initiator_name": my_name,
        "receiver_name": target_name,
        "status": "pending",
        "mode": "agent",
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
            "message": f"Connection request sent to {target_name}. They will need to accept it.",
        }

    return {"error": "Failed to create connection thread."}


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
        # Transport failure (DNS, TLS, 5xx, etc.). Same shape as above so
        # the LLM's existing prompt branches still work.
        return {
            "status": "delivery_failed",
            "reply_status": "transport_error",
            "thread_id": context_id,
            "partner_agent_id": target_agent_id,
            "error": f"{type(e).__name__}: {e}",
            "message": (
                "The message couldn't be delivered. Tell the user the network "
                "request failed and offer to retry."
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
            "error": (
                "Could not resolve an A2A v3 URL from the partner's stored URL. "
                f"webhook_url={target_webhook_url!r}"
            )
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
        return {"error": "You haven't deployed a persona yet — cannot send messages."}

    if not target_webhook_url:
        return {"error": "The target agent does not have a webhook URL. They cannot receive messages."}

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
            "error": (
                "No connection thread exists with this agent. Call request_connection "
                "first and wait for the receiver to accept it before messaging."
            ),
        }
    thread_id = thread["id"]
    thread_status = thread.get("status") or "pending"
    if thread_status not in ("accepted",):
        return {
            "error": (
                f"Connection is in '{thread_status}' state — only 'accepted' "
                f"connections may exchange messages. Wait for the other side to accept."
            ),
            "thread_id": thread_id,
        }

    # Insert outbound to dm_messages BEFORE the send (M-1: persist before
    # dispatch). Both participants see it immediately via Supabase realtime.
    try:
        sb.table("dm_messages").insert({
            "thread_id": thread_id,
            "sender_id": sender_agent_id,
            "sender_type": "agent",
            "channel": "agent",
            "content": message,
        }).execute()
    except Exception as e:
        logger.warning(f"{log_prefix} sender-side dm_messages insert failed: {e}")

    # Snapshot the time so the proposal lookup below can scope to "during
    # this exchange". (Receiver's orchestrator may have created an
    # agent_tasks meeting row while serving the request.)
    from datetime import datetime, timezone
    send_time_iso = datetime.now(timezone.utc).isoformat()

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
        delivery["thread_id"] = thread_id
        delivery["partner_agent_id"] = target_agent_id
        return delivery

    # `_send_via_a2a_v3` may have returned a `delivery_failed` shape
    # (network or receiver-rejection); pass it through verbatim — the
    # LLM's prompts already know how to phrase those.
    if delivery.get("status") == "delivery_failed":
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
        return {"status": "error", "error": "entity_id is required."}
    if not (user_id or "").strip():
        return {
            "status": "error",
            "entity_id": eid,
            "error": "Signed agent calls require a calling user with a deployed persona.",
            "hint": "This works for the principal's own persona, not in unauthenticated contexts.",
        }

    has_text = bool((text or "").strip())
    has_data = isinstance(data, dict) and len(data) > 0
    if not has_text and not has_data:
        return {
            "status": "error",
            "entity_id": eid,
            "error": "At least one of 'text' or 'data' must be provided.",
            "hint": "Check the input_schema from get_zynd_service_card and try again.",
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
        return {"error": "No active persona for this user."}

    sb = _get_supabase()

    # Verify the user is a participant of this thread (don't leak other
    # people's agent-channel traffic via a guessed thread_id).
    thread_res = sb.table("dm_threads").select("initiator_id,receiver_id").eq("id", thread_id).execute()
    if not thread_res.data:
        return {"error": f"Thread {thread_id} not found."}
    t = thread_res.data[0]
    if my_agent_id not in (t["initiator_id"], t["receiver_id"]):
        return {"error": "You are not a participant of this thread."}

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
        return {"error": f"Failed to read messages: {e}"}

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
