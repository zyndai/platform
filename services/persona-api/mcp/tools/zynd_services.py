"""
Zynd Network service-discovery MCP tools.

These let the persona reach for capabilities it doesn't have built in
(file conversion, currency lookup, translation, image manipulation, etc.)
by discovering and invoking *services* registered on the Zynd Network.

Three-step flow:

1. ``search_zynd_services`` — natural-language search against the registry,
   returning a ranked list of candidate services. Cached in-process for 30s
   to soften rapid retries from the same chat turn.

2. ``get_zynd_service_card`` — fetch a specific service's live agent-card
   from the registry. The card carries the **real** A2A endpoint URL plus
   the service-author-declared ``inputSchema`` / ``outputSchema``. The
   ``service_endpoint`` returned by ``/v1/search`` is a deployer-internal
   address (``http://localhost:5000``) and must NOT be used — only the
   card's ``url`` is authoritative.

3. ``call_zynd_service`` — POST a plain A2A v3 JSON-RPC ``message/send``
   to the service. Services are unauthenticated at the wire level (no
   ``x-zynd-auth`` signature required), so this is a direct HTTP call with
   no persona keypair, no DB writes, and no ``dm_threads`` row.

The registry itself lives at ``config.ZYND_REGISTRY_URL`` and exposes the
endpoints documented at ``{registry}/swagger/index.html``.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Any

import httpx
import requests

import config

logger = logging.getLogger(__name__)


# ── Search-result cache ────────────────────────────────────────────────
# Rapid retries within a turn (LLM rewording its query while exploring)
# hammer the registry for the same answer. A small TTL cache keyed on the
# normalized query smooths that out without hiding fresh registry updates.
_SEARCH_CACHE: dict[tuple[str, int, str], tuple[float, dict]] = {}
_SEARCH_CACHE_LOCK = threading.Lock()
_SEARCH_CACHE_TTL = 30.0


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
            oldest = sorted(_SEARCH_CACHE.items(), key=lambda kv: kv[1][0])[
                : len(_SEARCH_CACHE) - 64
            ]
            for k, _ in oldest:
                _SEARCH_CACHE.pop(k, None)


# ── Search ─────────────────────────────────────────────────────────────


def search_zynd_services(query: str, top_k: int = 5, category: str = "") -> dict:
    """
    Search the Zynd Network for services that can fulfill capabilities you don't have built in.
    Use this when no other tool covers the user's ask — e.g. file/format conversion,
    currency conversion, translation, image manipulation, niche data lookups.

    Always follow up with ``get_zynd_service_card`` on the candidate(s) you want to use,
    so you see the real endpoint URL and the input/output schema before calling.

    Args:
        query: Natural-language description of the capability you need (e.g. 'translate text',
               'convert xml to json', 'currency converter').
        top_k: Maximum results to return (default 5).
        category: Optional category filter (e.g. 'conversion', 'finance', 'text-nlp').
                  Leave empty to search all categories.
    """
    q = (query or "").strip()
    if not q:
        return {
            "status": "error",
            "error": "Empty query",
            "hint": "Pass a short natural-language description of the capability you need.",
            "results": [],
            "count": 0,
        }

    top_k = max(1, min(int(top_k or 5), 25))
    cat = (category or "").strip()

    cache_key = (q.lower(), top_k, cat.lower())
    cached = _search_cache_get(cache_key)
    if cached is not None:
        return {**cached, "from_cache": True}

    body: dict[str, Any] = {
        "query": q,
        "type": "service",
        "max_results": top_k,
        "status": "any",
    }
    if cat:
        body["category"] = cat

    try:
        resp = requests.post(
            f"{config.ZYND_REGISTRY_URL}/v1/search",
            json=body,
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json() or {}
    except requests.exceptions.Timeout:
        return {
            "status": "error",
            "error": "Registry search timed out.",
            "hint": "Tell the user the network discovery is slow right now and offer to retry.",
            "results": [],
            "count": 0,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Registry search failed: {e}",
            "results": [],
            "count": 0,
        }

    results = []
    for r in payload.get("results", []) or []:
        eid = r.get("entity_id")
        if not eid:
            continue
        results.append({
            "entity_id": eid,
            "name": r.get("name") or "",
            "summary": r.get("summary") or "",
            "category": r.get("category") or "",
            "tags": r.get("tags") or [],
            "status": r.get("status") or "",
            "score": r.get("score"),
            # NOTE: deliberately omitting ``service_endpoint`` — it's a
            # deployer-internal URL (``http://localhost:5000``) and never
            # callable. The real URL only exists on the agent-card.
        })

    out = {
        "status": "success",
        "count": len(results),
        "results": results,
        "total_found": payload.get("total_found", len(results)),
    }
    if not results:
        out["hint"] = (
            "No services matched. Try a shorter or differently-worded query, "
            "or tell the user this capability isn't on the network."
        )
    else:
        out["hint"] = (
            "Pick the best-matching entity_id and pass it to get_zynd_service_card "
            "to see the input/output schema before calling."
        )
    _search_cache_put(cache_key, out)
    return out


# ── Card fetch ─────────────────────────────────────────────────────────


def get_zynd_service_card(entity_id: str) -> dict:
    """
    Fetch a service's live agent-card from the registry. Contains the real A2A endpoint URL,
    the input/output schema declared by the service author, available skills, pricing,
    and current status.

    Call this AFTER search_zynd_services and BEFORE call_zynd_service so you know what
    payload shape to send.

    Args:
        entity_id: The service's registry id, e.g. 'zns:svc:c565a80ae1c70f794d7afaf8ca17f953'.
    """
    eid = (entity_id or "").strip()
    if not eid:
        return {"status": "error", "error": "entity_id is required."}

    try:
        resp = requests.get(
            f"{config.ZYND_REGISTRY_URL}/v1/entities/{eid}/card",
            timeout=15,
        )
    except requests.exceptions.Timeout:
        return {
            "status": "error",
            "entity_id": eid,
            "error": "Registry timed out fetching the service card.",
            "hint": "Try another service from the search results.",
        }
    except Exception as e:
        return {
            "status": "error",
            "entity_id": eid,
            "error": f"Registry request failed: {e}",
        }

    # The registry proxies the fetch from the service's deployer. When the
    # service is registered but the deployer can't serve the card (broken
    # deployment, wrong path, dead container), the registry returns 502
    # with a JSON `error` field. Surface that distinctly so the LLM knows
    # to pick a different result rather than retrying this one.
    if resp.status_code == 502:
        try:
            err_payload = resp.json() or {}
        except Exception:
            err_payload = {}
        return {
            "status": "unreachable",
            "entity_id": eid,
            "error": err_payload.get("error") or "Service is registered but its agent-card endpoint is unreachable.",
            "hint": "This service's deployment is broken. Try another result from search_zynd_services.",
        }
    if resp.status_code == 404:
        return {
            "status": "not_found",
            "entity_id": eid,
            "error": "No entity with that id is registered.",
        }
    try:
        resp.raise_for_status()
    except Exception as e:
        return {
            "status": "error",
            "entity_id": eid,
            "error": f"Registry returned HTTP {resp.status_code}: {e}",
        }

    card = resp.json() or {}
    x_zynd = card.get("x-zynd") or {}

    return {
        "status": "success",
        "entity_id": eid,
        "name": card.get("name") or "",
        "description": card.get("description") or "",
        "url": card.get("url") or "",
        "preferred_transport": card.get("preferredTransport") or "",
        "default_input_modes": card.get("defaultInputModes") or [],
        "default_output_modes": card.get("defaultOutputModes") or [],
        "input_schema": x_zynd.get("inputSchema") or {},
        "output_schema": x_zynd.get("outputSchema") or {},
        "skills": card.get("skills") or [],
        "capabilities": card.get("capabilities") or {},
        "pricing": card.get("pricing") or {},
        "service_status": x_zynd.get("status") or card.get("status") or "",
        "category": x_zynd.get("category") or "",
        "tags": x_zynd.get("tags") or [],
        "hint": (
            "The 'url' field is the JSON-RPC endpoint to invoke. Use 'input_schema' and "
            "'output_schema' to decide what to put in call_zynd_service(text=..., data=...). "
            "Many services read the user's request from the 'text' part of the A2A message."
        ),
    }


# ── Call ───────────────────────────────────────────────────────────────


def _join_text_parts(parts: Any) -> str:
    """Concatenate the text of every TextPart in an A2A parts array.
    Matches the convention used by agent/a2a/client.py.extract_reply_text."""
    if not isinstance(parts, list):
        return ""
    out: list[str] = []
    for p in parts:
        if isinstance(p, dict) and p.get("kind") == "text":
            t = p.get("text") or ""
            if t:
                out.append(t)
    return "\n".join(out)


def _extract_reply_from_task(task: dict) -> tuple[str, dict | list | None]:
    """Return (reply_text, structured_output) from an A2A Task.

    Prefers ``status.message.parts`` over ``artifacts[*].parts`` to match
    the agent client. ``structured_output`` is the JSON-parsed reply text
    when it parses to an object or list, otherwise None — services like
    the translation service emit their structured output as a JSON-encoded
    string inside a TextPart.
    """
    text = ""
    status_msg = (task.get("status") or {}).get("message") or {}
    text = _join_text_parts(status_msg.get("parts"))
    if not text:
        for art in task.get("artifacts") or []:
            if isinstance(art, dict):
                chunk = _join_text_parts(art.get("parts"))
                if chunk:
                    text = chunk
                    break

    structured: dict | list | None = None
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, (dict, list)):
                structured = parsed
        except (ValueError, TypeError):
            pass

    return text, structured


def call_zynd_service(entity_id: str, text: str = "", data: dict = None) -> dict:
    """
    Invoke a Zynd Network service via plain A2A v3 JSON-RPC. Services are unauthenticated —
    no signing or persona keypair is needed.

    Always call get_zynd_service_card first so you know the input_schema. Most services
    expect the user's request as the message's text part; some accept structured data parts.
    You may pass both ``text`` and ``data`` — at least one is required.

    Args:
        entity_id: The service's registry id, e.g. 'zns:svc:c565a80ae1c70f794d7afaf8ca17f953'.
        text: The text payload for the A2A message text part (e.g. content to translate).
        data: Optional structured payload for an A2A data part. Used by services whose
              input_schema expects fields beyond a single text blob.
    """
    eid = (entity_id or "").strip()
    if not eid:
        return {"status": "error", "error": "entity_id is required."}

    has_text = bool((text or "").strip())
    has_data = isinstance(data, dict) and len(data) > 0
    if not has_text and not has_data:
        return {
            "status": "error",
            "entity_id": eid,
            "error": "At least one of 'text' or 'data' must be provided.",
            "hint": "Check the input_schema returned by get_zynd_service_card and try again.",
        }

    # Get the real URL from the card. Never trust the ``service_endpoint``
    # field on search results — it points at the deployer's internal
    # ``http://localhost:5000``.
    card = get_zynd_service_card(eid)
    card_status = card.get("status")
    if card_status != "success":
        return {
            "status": "error",
            "entity_id": eid,
            "error": (
                f"Could not load the service card ({card_status}): {card.get('error')}"
            ),
            "hint": card.get("hint")
                    or "Try a different service from search_zynd_services.",
        }
    url = card.get("url") or ""
    if not url:
        return {
            "status": "error",
            "entity_id": eid,
            "error": "Service card has no 'url' field — service may be misconfigured.",
        }

    parts: list[dict] = []
    if has_data:
        parts.append({"kind": "data", "data": data})
    if has_text:
        parts.append({"kind": "text", "text": text})

    message = {
        "kind": "message",
        "messageId": str(uuid.uuid4()),
        "role": "user",
        "contextId": str(uuid.uuid4()),  # services are stateless — fresh context per call
        "parts": parts,
    }
    body = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {"message": message},
    }

    try:
        with httpx.Client(timeout=90.0) as h:
            resp = h.post(url, json=body)
            resp.raise_for_status()
            envelope = resp.json()
    except httpx.TimeoutException:
        return {
            "status": "error",
            "entity_id": eid,
            "url": url,
            "error": "Service call timed out (90s).",
            "hint": "Tell the user the service didn't respond in time and offer to retry.",
        }
    except Exception as e:
        return {
            "status": "error",
            "entity_id": eid,
            "url": url,
            "error": f"Service call failed: {type(e).__name__}: {e}",
        }

    if not isinstance(envelope, dict):
        return {
            "status": "error",
            "entity_id": eid,
            "url": url,
            "error": "Service returned a non-JSON-object envelope.",
        }
    if "error" in envelope:
        err = envelope["error"] or {}
        return {
            "status": "error",
            "entity_id": eid,
            "url": url,
            "error_code": err.get("code"),
            "error_message": err.get("message") or "Unknown JSON-RPC error.",
            "error_data": err.get("data"),
            "error": f"JSON-RPC error from service: {err.get('message')}",
        }

    task = envelope.get("result") or {}
    if not isinstance(task, dict):
        return {
            "status": "error",
            "entity_id": eid,
            "url": url,
            "error": "Service returned an unexpected result shape.",
        }

    task_state = ((task.get("status") or {}).get("state")) or "unknown"
    reply_text, structured = _extract_reply_from_task(task)

    return {
        "status": "success" if task_state == "completed" else "partial",
        "entity_id": eid,
        "task_id": task.get("id"),
        "task_state": task_state,
        "reply_text": reply_text,
        "structured_output": structured,
    }
