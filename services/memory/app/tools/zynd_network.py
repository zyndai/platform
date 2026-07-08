"""
Zynd Network MCP tools — discovery, networking, and messaging on the Zynd AI network.

Adapted from agent-persona for memory-layer MCP (FastMCP decorator pattern).
"""
import json
import logging
import re
import threading
import time
from typing import Any

import httpx
import requests
from supabase import create_client, Client

from app.config import settings

logger = logging.getLogger(__name__)

_REGISTRY_POOL_FLOOR = 60

_DISCOVER_CACHE: dict[tuple[str, int], tuple[float, dict]] = {}
_DISCOVER_CACHE_LOCK = threading.Lock()
_DISCOVER_CACHE_TTL = 30.0

_AVATAR_CACHE: dict[str, tuple[float, dict[str, str]]] = {}
_AVATAR_CACHE_LOCK = threading.Lock()
_AVATAR_CACHE_TTL = 300.0

_supabase_client: Client | None = None


def _get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _supabase_client


def _build_avatar_map() -> dict[str, str]:
    try:
        sb = _get_supabase()
        rows = sb.table("persona_agents").select("user_id,agent_id").eq("active", True).execute()
        agent_to_user: dict[str, str] = {
            r["agent_id"]: r["user_id"] for r in (rows.data or []) if r.get("agent_id") and r.get("user_id")
        }
        if not agent_to_user:
            return {}

        user_avatars: dict[str, str] = {}
        page = 1
        admin_url = f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users"
        headers = {
            "apikey": settings.supabase_service_key,
            "Authorization": f"Bearer {settings.supabase_service_key}",
        }
        while page <= 10:
            r = requests.get(admin_url, headers=headers, params={"page": page, "per_page": 100}, timeout=4)
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

        return {aid: user_avatars[uid] for aid, uid in agent_to_user.items() if uid in user_avatars}
    except Exception as e:
        logger.warning(f"[discover] avatar map build failed: {e}")
        return {}


def _get_avatar_map() -> dict[str, str]:
    now = time.time()
    with _AVATAR_CACHE_LOCK:
        cached = _AVATAR_CACHE.get("global")
        if cached and cached[0] > now:
            return cached[1]
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
        if len(_DISCOVER_CACHE) > 64:
            oldest = sorted(_DISCOVER_CACHE.items(), key=lambda kv: kv[1][0])[:len(_DISCOVER_CACHE) - 64]
            for k, _ in oldest:
                _DISCOVER_CACHE.pop(k, None)


def _discover_local(q: str, top_k: int, avatars: dict[str, str]) -> list[dict]:
    sb = _get_supabase()
    broad = not q or q.lower() in ("persona", "all", "any", "everyone", "personas", "agents", "network", "list", "")

    if broad:
        result = sb.table("persona_agents").select("agent_id,name,description").eq("active", True).order("updated_at", desc=True).limit(top_k).execute()
        rows_data = result.data or []
    else:
        try:
            result = sb.rpc("search_personas_fts", {"query_text": q, "result_limit": top_k}).execute()
            rows_data = result.data or []
        except Exception:
            pattern = f"%{q}%"
            result = sb.table("persona_agents").select("agent_id,name,description").eq("active", True).or_(f"name.ilike.{pattern},description.ilike.{pattern},brief_content.ilike.{pattern}").limit(top_k).execute()
            rows_data = result.data or []

    return [{"name": r.get("name") or "", "agent_id": r.get("agent_id") or "", "description": r.get("description") or "", "avatar_url": avatars.get(r.get("agent_id") or "")} for r in rows_data if r.get("agent_id")]


def _discover_registry(q: str, top_k: int, avatars: dict[str, str]) -> list[dict]:
    registry_q = q if (q and q.lower() not in ("", "persona")) else "persona"
    try:
        resp = requests.post(f"{settings.zynd_registry_url}/v1/search", json={"query": registry_q, "tags": ["persona"], "max_results": max(int(top_k), _REGISTRY_POOL_FLOOR), "status": "any"}, timeout=4)
        resp.raise_for_status()
        raw = resp.json().get("results", [])
    except Exception:
        return []

    out: list[dict] = []
    for a in raw:
        tags = a.get("tags") or []
        if "persona" not in tags:
            continue
        aid = a.get("entity_id") or a.get("agent_id") or ""
        if not aid:
            continue
        out.append({"name": a.get("name") or "", "agent_id": aid, "description": a.get("summary") or a.get("description") or "", "avatar_url": avatars.get(aid)})
    return out


def discover_personas(query: str, top_k: int = 20) -> dict:
    q = (query or "").strip()
    key = (q.lower(), int(top_k))
    cached = _discover_cache_get(key)
    if cached is not None:
        return {**cached, "from_cache": True}

    avatars = _get_avatar_map()
    try:
        local = _discover_local(q, top_k, avatars)
    except Exception:
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
    source = "local+registry" if len(combined) > len(local) else "local" if local else "registry"
    if not results:
        return {"status": "error", "error": "No personas found.", "results": [], "count": 0, "source": "none"}
    out = {"status": "success", "count": len(results), "total_available": len(combined), "results": results, "source": source}
    _discover_cache_put(key, out)
    return out


def _fetch_agent_card(agent_id: str) -> dict | None:
    try:
        resp = requests.get(f"{settings.zynd_registry_url}/v1/entities/{agent_id}/card", timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def _agent_url_from_card(card: dict | None) -> str:
    if not card:
        return ""
    if isinstance(card.get("url"), str) and card.get("preferredTransport") == "JSONRPC":
        return card["url"]
    endpoints = card.get("endpoints") or {}
    return endpoints.get("invoke") or endpoints.get("websocket") or ""


_QUERY_STOPWORDS: set[str] = {
    "a", "an", "the", "of", "for", "to", "with", "from", "on", "in", "by",
    "at", "and", "or", "is", "are", "as", "any", "some",
    "find", "search", "search-for", "look", "look-for", "show", "show-me",
    "get", "give", "give-me", "tell", "tell-me", "list", "fetch", "discover",
    "want", "need", "please", "can", "could", "would",
    "me", "my", "i", "you", "your", "us", "we", "they", "them", "it", "this", "that",
    "agent", "agents", "service", "services", "tool", "tools", "thing", "things",
    "something", "someone", "anyone", "anything",
}


def _normalize_query(q: str) -> str:
    if not q:
        return ""
    tokens = [t for t in re.split(r"[^\w-]+", q.lower()) if t]
    filtered = [t for t in tokens if t not in _QUERY_STOPWORDS and len(t) > 1]
    if not filtered:
        return q.strip()
    return " ".join(filtered[:4])


def _call_registry_search(query: str, kind: str, top_k: int) -> tuple[list[dict], str | None]:
    filtered = kind in ("persona", "agent", "service")
    requested = max(int(top_k), _REGISTRY_POOL_FLOOR) if filtered else int(top_k)
    body: dict[str, Any] = {"query": query, "max_results": requested, "status": "any", "enrich": True}
    if kind == "persona":
        body["tags"] = ["persona"]
    elif kind in ("agent", "service"):
        body["entity_type"] = kind
    try:
        resp = requests.post(f"{settings.zynd_registry_url}/v1/search", json=body, timeout=8)
        resp.raise_for_status()
        return (resp.json() or {}).get("results") or [], None
    except requests.exceptions.Timeout:
        return [], "Registry timed out."
    except Exception as e:
        return [], f"Registry search failed: {e}"


_DEPLOYER_CACHE: dict[str, tuple[float, list[dict]]] = {}
_DEPLOYER_CACHE_LOCK = threading.Lock()
_DEPLOYER_CACHE_TTL = 60.0


def _deployer_running_entities() -> list[dict]:
    with _DEPLOYER_CACHE_LOCK:
        hit = _DEPLOYER_CACHE.get("running")
        if hit is not None and (time.time() - hit[0]) < _DEPLOYER_CACHE_TTL:
            return hit[1]

    rows: list[dict] = []
    try:
        resp = requests.get(f"{settings.zynd_deployer_url}/api/deployments", timeout=6)
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
            rows.append({"name": name, "entity_id": d.get("entityId") or slug, "kind": etype, "entity_type": etype, "summary": "", "category": "", "tags": [], "url": f"{host}/a2a/v1", "status": "active", "avatar_url": None, "source": "deployer"})
    except Exception as e:
        logger.warning(f"[deployer] running-entities fetch failed: {e!r}")
        return []

    with _DEPLOYER_CACHE_LOCK:
        _DEPLOYER_CACHE["running"] = (time.time(), rows)
    return rows


def _merge_deployer_entities(results: list[dict], kind: str, query: str) -> list[dict]:
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
            continue
        if d["entity_id"] in seen_ids or d["name"].lower() in seen_names:
            continue
        if q and q not in ("persona",) and q not in d["name"].lower():
            continue
        results.append(d)
        seen_ids.add(d["entity_id"])
        seen_names.add(d["name"].lower())
    return results


# ── Public MCP Tools (FastMCP-compatible) ─────────────────────────────

async def search_zynd_network(query: str, top_k: int = 8, kind: str = "any", user_id: str = "") -> dict:
    q = (query or "").strip()
    if not q:
        q = "persona"
    normalized = _normalize_query(q)
    registry_results, err = _call_registry_search(normalized, kind, top_k)
    if err:
        return {"status": "error", "error": err, "results": [], "count": 0}

    if kind == "persona":
        local = discover_personas(q, top_k)
        return local

    results = _merge_deployer_entities(registry_results, kind, q)
    return {"status": "success", "count": len(results), "results": results[:top_k], "total_found": len(results), "source": "registry+deployer" if any(r.get("source") == "deployer" for r in results) else "registry"}


async def search_zynd_personas(query: str, top_k: int = 5, user_id: str = "") -> dict:
    return discover_personas(query, top_k)


async def get_persona_profile(agent_id: str) -> dict:
    if not agent_id:
        return {"status": "error", "error": "agent_id is required."}
    card = _fetch_agent_card(agent_id)
    if not card:
        return {"status": "error", "error": f"No card found for {agent_id}.", "agent_id": agent_id}
    return {"status": "success", "agent_id": agent_id, "name": card.get("name") or "", "description": card.get("description") or "", "url": _agent_url_from_card(card), "capabilities": card.get("capabilities") or {}, "skills": card.get("skills") or []}


async def list_my_connections(user_id: str) -> dict:
    sb = _get_supabase()
    try:
        r = sb.table("dm_threads").select("id,initiator_id,receiver_id,status,created_at").or_(f"initiator_id.eq.{user_id},receiver_id.eq.{user_id}").in_("status", ["pending", "accepted"]).execute()
        connections = r.data or []
        enriched = []
        for c in connections:
            other_id = c["receiver_id"] if c["initiator_id"] == user_id else c["initiator_id"]
            persona = sb.table("persona_agents").select("name,agent_handle,description").eq("agent_id", other_id).eq("active", True).execute()
            name = other_id
            if persona.data:
                p = persona.data[0]
                name = p.get("agent_handle") or p.get("name") or other_id
            enriched.append({**c, "other_agent_id": other_id, "other_name": name})
        return {"status": "success", "connections": enriched, "count": len(enriched)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def request_connection(user_id: str, target_agent_id: str, target_name: str = "Network Agent") -> dict:
    sb = _get_supabase()
    try:
        me = sb.table("persona_agents").select("agent_id,name").eq("user_id", user_id).eq("active", True).execute()
        if not me.data:
            return {"status": "error", "error": "You need a deployed persona to send connection requests."}
        my_agent_id = me.data[0]["agent_id"]
        my_name = me.data[0].get("name") or "User"

        existing = sb.table("dm_threads").select("id,status").or_(
            f"and(initiator_id.eq.{my_agent_id},receiver_id.eq.{target_agent_id}),and(initiator_id.eq.{target_agent_id},receiver_id.eq.{my_agent_id})"
        ).execute()
        if existing.data:
            return {"status": "exists", "thread_id": existing.data[0]["id"], "current_status": existing.data[0]["status"]}

        thread = sb.table("dm_threads").insert({
            "initiator_id": my_agent_id,
            "receiver_id": target_agent_id,
            "status": "pending",
        }).execute()
        if not thread.data:
            return {"status": "error", "error": "Failed to create connection request."}
        thread_id = thread.data[0]["id"]

        card = _fetch_agent_card(target_agent_id)
        target_url = _agent_url_from_card(card) if card else None
        if target_url:
            try:
                payload = {
                    "jsonrpc": "2.0", "method": "connection/request",
                    "params": {
                        "thread_id": thread_id,
                        "from_agent_id": my_agent_id,
                        "from_name": my_name,
                    },
                }
                async with httpx.AsyncClient(timeout=15) as client:
                    await client.post(target_url, json=payload)
            except Exception:
                pass

        return {"status": "success", "thread_id": thread_id, "message": f"Connection request sent to {target_name}."}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def check_connection_status(user_id: str, target_agent_id: str) -> dict:
    sb = _get_supabase()
    try:
        me = sb.table("persona_agents").select("agent_id").eq("user_id", user_id).eq("active", True).execute()
        if not me.data:
            return {"status": "error", "error": "No active persona found."}
        my_agent_id = me.data[0]["agent_id"]

        r = sb.table("dm_threads").select("id,status,created_at").or_(
            f"and(initiator_id.eq.{my_agent_id},receiver_id.eq.{target_agent_id}),and(initiator_id.eq.{target_agent_id},receiver_id.eq.{my_agent_id})"
        ).execute()
        if not r.data:
            return {"status": "not_connected", "connected": False}
        return {"status": "success", "connected": True, "thread_id": r.data[0]["id"], "connection_status": r.data[0]["status"]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def message_zynd_agent(user_id: str, target_webhook_url: str, target_agent_id: str, message: str) -> dict:
    import uuid as _uuid
    msg_id = str(_uuid.uuid4())
    try:
        payload = {"jsonrpc": "2.0", "id": msg_id, "method": "message/send", "params": {"message": {"messageId": msg_id, "role": "user", "parts": [{"kind": "text", "text": message}]}}}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(target_webhook_url, json=payload)
            if r.status_code == 200:
                return {"status": "success", "sent": True, "to": target_agent_id, "message_id": msg_id}
            return {"status": "error", "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def call_zynd_agent(entity_id: str, text: str = "", data: dict = None, user_id: str = "", conversation_id: str = "") -> dict:
    eid = (entity_id or "").strip()
    if not eid:
        return {"status": "error", "error": "entity_id is required."}

    has_text = bool((text or "").strip())
    has_data = isinstance(data, dict) and len(data) > 0
    if not has_text and not has_data:
        return {"status": "error", "error": "At least one of 'text' or 'data' must be provided."}

    card = _fetch_agent_card(eid)
    target_url = None
    if card:
        target_url = _agent_url_from_card(card)
    if not target_url:
        sb = _get_supabase()
        r = sb.table("persona_agents").select("webhook_url").eq("agent_id", eid).eq("active", True).execute()
        if r.data and r.data[0].get("webhook_url"):
            target_url = r.data[0]["webhook_url"]
    if not target_url:
        return {"status": "error", "entity_id": eid, "error": "Could not resolve a callable URL for this agent."}

    parts = []
    if has_text:
        parts.append({"kind": "text", "text": text.strip()})
    if has_data:
        parts.append({"kind": "data", "data": data})

    import uuid as _uuid
    msg_id = str(_uuid.uuid4())
    payload = {
        "jsonrpc": "2.0", "id": msg_id, "method": "message/send",
        "params": {"message": {"messageId": msg_id, "role": "user", "parts": parts}},
    }

    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(target_url, json=payload, headers={"Content-Type": "application/json"})
            if r.status_code == 200:
                result = r.json()
                return {"status": "success", "entity_id": eid, "result": result}
            return {"status": "error", "entity_id": eid, "error": f"HTTP {r.status_code}: {r.text[:300]}"}
    except httpx.TimeoutException:
        return {"status": "error", "entity_id": eid, "error": "Agent timed out after 90s."}
    except Exception as e:
        return {"status": "error", "entity_id": eid, "error": str(e)}


async def read_agent_channel(user_id: str, thread_id: str, limit: int = 20) -> dict:
    sb = _get_supabase()
    try:
        r = sb.table("dm_messages").select("*").eq("thread_id", thread_id).order("created_at", desc=True).limit(limit).execute()
        return {"status": "success", "messages": r.data or [], "count": len(r.data or [])}
    except Exception as e:
        return {"status": "error", "error": str(e)}
