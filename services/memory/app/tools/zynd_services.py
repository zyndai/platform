
"""
Zynd Network service-discovery MCP tools.

Adapted from agent-persona for memory-layer MCP (FastMCP decorator pattern).
"""
import json
import logging
import threading
import time
import uuid
from typing import Any

import httpx
import requests

from app.config import settings

logger = logging.getLogger(__name__)

_SEARCH_CACHE: dict[tuple[str, int, str], tuple[float, dict]] = {}
_SEARCH_CACHE_LOCK = threading.Lock()
_SEARCH_CACHE_TTL = 30.0


def _flatten_schema_refs(schema: Any, _defs: dict | None = None, _depth: int = 0) -> Any:
    if _defs is None and isinstance(schema, dict):
        _defs = schema.get("$defs") or schema.get("definitions") or {}
    if _depth > 12 or not isinstance(schema, (dict, list)):
        return schema
    if isinstance(schema, list):
        return [_flatten_schema_refs(v, _defs, _depth + 1) for v in schema]
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        key = ref.split("/")[-1]
        target = (_defs or {}).get(key)
        if isinstance(target, dict):
            return _flatten_schema_refs(target, _defs, _depth + 1)
        return {"type": "object"}
    out: dict = {}
    for k, v in schema.items():
        if k in ("$defs", "definitions", "$ref", "$schema"):
            continue
        out[k] = _flatten_schema_refs(v, _defs, _depth + 1)
    return out


def _search_cache_get(key: tuple[str, int, str]) -> dict | None:
    with _SEARCH_CACHE_LOCK:
        hit = _SEARCH_CACHE.get(key)
        if not hit:
            return None
        expires_at, value = hit
        if expires_at < time.time():
            _SEARCH_CACHE.pop(key, None)
            return None
        return value


def _search_cache_put(key: tuple[str, int, str], value: dict) -> None:
    with _SEARCH_CACHE_LOCK:
        _SEARCH_CACHE[key] = (time.time() + _SEARCH_CACHE_TTL, value)
        if len(_SEARCH_CACHE) > 64:
            oldest = sorted(_SEARCH_CACHE.items(), key=lambda kv: kv[1][0])[:len(_SEARCH_CACHE) - 64]
            for k, _ in oldest:
                _SEARCH_CACHE.pop(k, None)


async def search_zynd_services(query: str, top_k: int = 5, category: str = "") -> dict:
    q = (query or "").strip()
    if not q:
        return {"status": "error", "error": "Empty query", "hint": "Pass a short natural-language description of the capability you need.", "results": [], "count": 0}

    top_k = max(1, min(int(top_k or 5), 25))
    cat = (category or "").strip()

    cache_key = (q.lower(), top_k, cat.lower())
    cached = _search_cache_get(cache_key)
    if cached is not None:
        return {**cached, "from_cache": True}

    body: dict[str, Any] = {"query": q, "type": "service", "max_results": top_k, "status": "any"}
    if cat:
        body["category"] = cat

    try:
        resp = requests.post(f"{settings.zynd_registry_url}/v1/search", json=body, timeout=10)
        resp.raise_for_status()
        payload = resp.json() or {}
    except requests.exceptions.Timeout:
        return {"status": "error", "error": "Registry search timed out.", "results": [], "count": 0}
    except Exception as e:
        return {"status": "error", "error": f"Registry search failed: {e}", "results": [], "count": 0}

    results = []
    for r in payload.get("results", []) or []:
        eid = r.get("entity_id")
        if not eid:
            continue
        results.append({"entity_id": eid, "name": r.get("name") or "", "summary": r.get("summary") or "", "category": r.get("category") or "", "tags": r.get("tags") or [], "status": r.get("status") or "", "score": r.get("score")})

    out: dict = {"status": "success", "count": len(results), "results": results, "total_found": payload.get("total_found", len(results))}
    if not results:
        out["hint"] = "No services matched. Try a shorter or differently-worded query."
    else:
        out["hint"] = "Pick the best-matching entity_id and pass it to get_zynd_service_card to see the input/output schema before calling."
    _search_cache_put(cache_key, out)
    return out


def _card_to_result(card: dict, eid: str) -> dict:
    x_zynd = card.get("x-zynd") or {}
    return {
        "status": "success", "entity_id": eid,
        "name": card.get("name") or "", "description": card.get("description") or "",
        "url": card.get("url") or "", "preferred_transport": card.get("preferredTransport") or "",
        "default_input_modes": card.get("defaultInputModes") or [],
        "default_output_modes": card.get("defaultOutputModes") or [],
        "input_schema": _flatten_schema_refs(x_zynd.get("inputSchema") or {}),
        "output_schema": _flatten_schema_refs(x_zynd.get("outputSchema") or {}),
        "skills": card.get("skills") or [], "capabilities": card.get("capabilities") or {},
        "pricing": card.get("pricing") or {},
        "service_status": x_zynd.get("status") or card.get("status") or "",
        "category": x_zynd.get("category") or "", "tags": x_zynd.get("tags") or [],
    }


def _deployer_card_fallback(eid: str) -> dict | None:
    base = settings.zynd_deployer_url.rstrip("/")
    for prefix in ("agent", "service"):
        url = f"{base}/{prefix}/{eid}/.well-known/agent-card.json"
        try:
            r = requests.get(url, timeout=8)
            if r.status_code == 200:
                card = r.json() or {}
                real_eid = (card.get("x-zynd") or {}).get("entityId") or eid
                return _card_to_result(card, real_eid)
        except Exception:
            continue
    return None


async def get_zynd_service_card(entity_id: str) -> dict:
    eid = (entity_id or "").strip()
    if not eid:
        return {"status": "error", "error": "entity_id is required."}
    try:
        resp = requests.get(f"{settings.zynd_registry_url}/v1/entities/{eid}/card", timeout=15)
    except requests.exceptions.Timeout:
        return {"status": "error", "entity_id": eid, "error": "Registry timed out fetching the service card."}
    except Exception as e:
        return {"status": "error", "entity_id": eid, "error": f"Registry request failed: {e}"}
    if resp.status_code == 502:
        return {"status": "unreachable", "entity_id": eid, "error": "Service is registered but its agent-card endpoint is unreachable."}
    if resp.status_code == 404:
        deployer_card = _deployer_card_fallback(eid)
        if deployer_card is not None:
            return deployer_card
        return {"status": "not_found", "entity_id": eid, "error": "No entity with that id is registered."}
    try:
        resp.raise_for_status()
    except Exception as e:
        return {"status": "error", "entity_id": eid, "error": f"Registry returned HTTP {resp.status_code}: {e}"}
    return _card_to_result(resp.json() or {}, eid)


async def call_zynd_service(entity_id: str, text: str = "", data: dict = None, user_id: str = "") -> dict:
    eid = (entity_id or "").strip()
    if not eid:
        return {"status": "error", "error": "entity_id is required."}
    has_text = bool((text or "").strip())
    has_data = isinstance(data, dict) and len(data) > 0
    if not has_text and not has_data:
        return {"status": "error", "entity_id": eid, "error": "At least one of 'text' or 'data' must be provided."}

    card = await get_zynd_service_card(eid)
    if card.get("status") != "success":
        return card
    service_url = card.get("url")
    if not service_url:
        return {"status": "error", "entity_id": eid, "error": "No callable URL in the service card."}

    parts = []
    if has_text:
        parts.append({"kind": "text", "text": text.strip()})
    if has_data:
        parts.append({"kind": "data", "data": data})
    message_id = str(uuid.uuid4())
    payload = {
        "jsonrpc": "2.0", "id": message_id, "method": "message/send",
        "params": {"message": {"messageId": message_id, "role": "user", "parts": parts}},
    }
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(service_url, json=payload, headers={"Content-Type": "application/json"})
            if r.status_code == 200:
                result = r.json()
                return {"status": "success", "entity_id": eid, "result": result}
            return {"status": "error", "entity_id": eid, "error": f"HTTP {r.status_code}: {r.text[:300]}"}
    except httpx.TimeoutException:
        return {"status": "error", "entity_id": eid, "error": "Service timed out after 90s."}
    except Exception as e:
        return {"status": "error", "entity_id": eid, "error": str(e)}
