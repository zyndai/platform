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

3. ``call_zynd_service`` — POST an A2A v3 JSON-RPC ``message/send`` to the
   service, SIGNED with the principal's persona keypair (x-zynd-auth) when
   one is available so the service can attribute the call. Services that
   don't require auth ignore the signature. No DB writes and no
   ``dm_threads`` row — services are stateless from our side. If the
   principal has no persona the call still goes out unsigned.

The registry itself lives at ``config.ZYND_REGISTRY_URL`` and exposes the
endpoints documented at ``{registry}/swagger/index.html``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from typing import Any

import httpx
import requests

import config
from agent.a2a.types import (
    ZYND_AUTH_EXPIRED,
    ZYND_AUTH_FAILED,
    ZYND_REPLAY_DETECTED,
)

logger = logging.getLogger(__name__)


def _flatten_schema_refs(schema: Any, _defs: dict | None = None, _depth: int = 0) -> Any:
    """Inline ``$ref`` references against ``$defs``/``definitions`` and drop
    the defs block, returning a self-contained JSON Schema.

    Service authors using Pydantic emit schemas with ``$defs`` + ``$ref``
    (e.g. ``CompetitorInput``). Strict function-calling backends (Gemini)
    reject those — both when the schema rides in a tool DEFINITION and when
    it comes back inside a tool RESULT. Flattening keeps the schema usable
    (fields stay visible so the caller can build the payload) while removing
    the references. Recursion is depth-bounded to defang cyclic refs."""
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
        return {"type": "object"}  # unresolvable — degrade to open object
    out: dict = {}
    for k, v in schema.items():
        if k in ("$defs", "definitions", "$ref", "$schema"):
            continue
        out[k] = _flatten_schema_refs(v, _defs, _depth + 1)
    return out


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
    Use this when, and ONLY when, no built-in tool covers the user's ask — e.g. file/format
    conversion (pdf→text, xml→json, docx→text), currency conversion, translation, text
    summarization, image manipulation, niche data lookups. Do NOT use this for things an LLM
    can answer from general knowledge, or where a built-in tool already covers the task.

    Mandatory next step: pick the highest-scored ACTIVE result and pass its ``entity_id``
    to ``get_zynd_service_card`` to read its input/output schema. NEVER skip the card fetch
    — the search result's ``service_endpoint`` is deployer-internal and NOT callable.

    Cached for 30s per ``(query, top_k, category)`` triple to soften repeat queries.

    Args:
        query: Natural-language description of the capability you need (e.g. 'translate text',
               'convert xml to json', 'currency converter'). Short and specific beats long
               and ambiguous — service summaries are ~1 line each.
        top_k: Maximum results to return (1–25, default 5). Use 3 unless you specifically
               want a wider net.
        category: Optional category filter. Known values: 'conversion', 'finance',
                  'text-nlp'. Leave empty to search all categories.
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
    Fetch a service's live agent-card from the registry. REQUIRED step between
    ``search_zynd_services`` and ``call_zynd_service`` — never skip it.

    Returns the real callable ``url``, the ``input_schema`` (which decides what payload
    shape to send), the ``output_schema`` (so you know what fields to read out of the
    reply), available skills, pricing, and live ``service_status``.

    Use the ``input_schema`` to choose between ``text=`` and ``data=`` on the call:
      - Task-specific fields like ``target_language``, ``amount``, ``from_currency``,
        ``pdf_url`` → pass them in ``data={...}``.
      - A single free-text field (just ``content`` or ``text``) → use ``text=...``.
      - A generic Zynd-message envelope (``sender_id``, ``conversation_id``, etc.) →
        task params usually go in ``metadata`` (pass ``data={"metadata": {...}}``) or
        the service treats ``content`` as the payload (pass ``text=``).

    Distinct error statuses:
      - ``status: "not_found"`` — no such entity. Try a different search result.
      - ``status: "unreachable"`` — registered but deployment broken. Move to the next
        search result; do NOT retry this one.
      - ``status: "error"`` — registry/network problem; safe to retry once.

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
        # Not in the registry — but it may be a deployer slug for an agent
        # that's live on the deployer yet never registered (the network
        # search now surfaces those). Try the deployer's card directly.
        deployer_card = _deployer_card_fallback(eid)
        if deployer_card is not None:
            return deployer_card
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

    return _card_to_result(resp.json() or {}, eid)


def _card_to_result(card: dict, eid: str) -> dict:
    """Shape a raw agent-card dict into the get_zynd_service_card result."""
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
        "input_schema": _flatten_schema_refs(x_zynd.get("inputSchema") or {}),
        "output_schema": _flatten_schema_refs(x_zynd.get("outputSchema") or {}),
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


def _deployer_card_fallback(eid: str) -> dict | None:
    """Fetch an agent/service card straight from the deployer for entities
    that are live there but missing from the registry. ``eid`` is the
    deployer slug (e.g. ``grant-finder-48da29``). Returns a card result, or
    None if the deployer doesn't have it either.

    The deployer serves cards at both /agent/<slug> and /service/<slug>;
    we try the slug under each prefix's well-known path. The card's own
    ``url`` is authoritative for the callable endpoint, so we trust it
    rather than guessing agent-vs-service from the prefix."""
    base = config.ZYND_DEPLOYER_URL.rstrip("/")
    for prefix in ("agent", "service"):
        url = f"{base}/{prefix}/{eid}/.well-known/agent-card.json"
        try:
            r = requests.get(url, timeout=8)
            if r.status_code == 200:
                # The card's x-zynd.entityId is the real registry id; prefer
                # it so downstream signing/dispatch uses the canonical id.
                card = r.json() or {}
                real_eid = (card.get("x-zynd") or {}).get("entityId") or eid
                return _card_to_result(card, real_eid)
        except Exception:
            continue
    return None


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


# Field names agents commonly use to carry the human-readable reply inside
# a DataPart payload. Checked in order; first non-empty wins.
_DATA_REPLY_FIELDS = ("response", "text", "message", "reply", "answer", "result", "output", "summary")


def _data_part_payloads(parts: Any) -> list[dict | list]:
    """Collect the ``data`` object of every DataPart in a parts array."""
    out: list[dict | list] = []
    if not isinstance(parts, list):
        return out
    for p in parts:
        if isinstance(p, dict) and p.get("kind") == "data":
            d = p.get("data")
            if isinstance(d, (dict, list)):
                out.append(d)
    return out


def _readable_from_data(payload: dict | list) -> str:
    """Pull a human-readable string out of a DataPart payload, if any."""
    if isinstance(payload, dict):
        for f in _DATA_REPLY_FIELDS:
            v = payload.get(f)
            if isinstance(v, str) and v.strip():
                return v
            if isinstance(v, (dict, list)) and v:
                return json.dumps(v, indent=2)
    return ""


def _extract_reply_from_task(task: dict) -> tuple[str, dict | list | None]:
    """Return (reply_text, structured_output) from an A2A Task.

    Handles BOTH reply shapes seen on the network:
      * TextPart — plain text, or a JSON-encoded string (translation-style).
      * DataPart — a structured ``data`` object (competitor-monitor-style,
        which returns ``{"mode": "chat", "response": "…"}``). The human
        text is pulled from common fields (response/text/message/…); the
        whole object becomes ``structured_output``.

    Prefers ``status.message.parts`` over ``artifacts[*].parts`` to match
    the agent client.
    """
    status_msg = (task.get("status") or {}).get("message") or {}
    sources = [status_msg.get("parts")] + [
        art.get("parts") for art in (task.get("artifacts") or []) if isinstance(art, dict)
    ]

    text = ""
    structured: dict | list | None = None

    for parts in sources:
        # 1) Text parts.
        chunk = _join_text_parts(parts)
        if chunk and not text:
            text = chunk
        # 2) Data parts.
        for payload in _data_part_payloads(parts):
            if structured is None:
                structured = payload
            if not text:
                text = _readable_from_data(payload)
        if text or structured is not None:
            break

    # A JSON-encoded string in a TextPart is structured output too.
    if structured is None and text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, (dict, list)):
                structured = parsed
        except (ValueError, TypeError):
            pass

    return text, structured


# Tokens that distinguish a payload-shape rejection (LLM should fix `data`
# and retry) from a generic handler crash. Advisory only — it steers the
# hint, never blocks a retry.
_SCHEMA_ERROR_TOKENS = ("schema", "valid", "required", "expected", "property", "parse", "zod")


def classify_task_result(
    task_state: str, reply_text: str, structured: dict | list | None = None
) -> tuple[str, str]:
    """Map an A2A task state + extracted reply into a (status, hint) the LLM
    can act on. Shared by call_zynd_service and call_zynd_agent's inline
    (SEND) path so both speak the same failure vocabulary.

    The A2A SDK reports schema mismatches, handler crashes, and missing
    handlers as a Task with state="failed"/"rejected" — NOT as a thrown
    error — so the caller must inspect the state, which is what this does.
    """
    low = (reply_text or "").lower()
    if task_state == "completed":
        if reply_text or structured:
            return "success", "Use reply_text / structured_output as the answer."
        return (
            "empty_result",
            "Completed with no output — the payload shape was likely wrong. "
            "Re-read input_schema and retry with a different data shape.",
        )
    if task_state == "failed":
        if any(tok in low for tok in _SCHEMA_ERROR_TOKENS):
            return (
                "bad_request",
                "The agent rejected the payload shape. Fix `data` to match input_schema "
                "and retry; the validation message is in reply_text.",
            )
        return (
            "remote_failed",
            "The agent's handler failed. Tell the user and offer to retry or pick another result.",
        )
    if task_state == "rejected":
        return (
            "rejected",
            "The agent can't handle this request — pick a different result; do NOT retry this id.",
        )
    if task_state == "input-required":
        return (
            "needs_input",
            "The agent paused and asked for more info (in reply_text) — bring the question to the user.",
        )
    if task_state == "auth-required":
        return (
            "auth_required",
            "This entity is a signed agent, not an unauthenticated service. "
            "Call it via call_zynd_agent (which signs the request) instead.",
        )
    if task_state in ("working", "submitted"):
        return (
            "working",
            "The agent didn't complete synchronously. Tell the user it's still processing and offer to retry.",
        )
    return "partial", "Unexpected task state — surface reply_text to the user."


def call_zynd_service(entity_id: str, text: str = "", data: dict = None, user_id: str = "") -> dict:
    """
    Invoke a Zynd Network service via A2A v3 JSON-RPC. The request is SIGNED with the
    principal's persona keypair (x-zynd-auth) when a persona is available, so the service
    can attribute the call; services that don't require auth simply ignore the signature.
    (If the principal has no deployed persona the call still goes out unsigned.)

    PRECONDITION: you must have already called ``get_zynd_service_card`` for this entity_id
    and read its ``input_schema``. Shape the payload based on what the schema declares:

      - Schema declares task-specific fields (``target_language``, ``amount``,
        ``from_currency``, ``to_currency``, ``pdf_url``, etc.) → pass them in ``data``:

            call_zynd_service(eid, data={"amount": 100, "from_currency": "USD",
                                          "to_currency": "EUR"})

      - Schema declares ONLY a single free-text field (``content`` or ``text``) →
        pass the request in ``text``:

            call_zynd_service(eid, text="Summarize this paragraph: …")

      - Schema is a generic Zynd-message envelope (fields like ``sender_id``,
        ``message_id``, ``conversation_id``, ``content``, ``metadata``) → the task
        parameters usually go in metadata, or the service treats ``content`` as the
        body. Pass ``text=<request body>`` and optionally
        ``data={"metadata": {"target_language": "fr"}}`` per the service description.

    You may pass both ``text`` and ``data``; they ride in separate parts and the service
    picks whichever it needs. At least one must be provided.

    Reading the reply:
      - ``structured_output`` is the JSON-parsed reply when the service returns a JSON
        blob. Prefer reading individual fields from here.
      - ``reply_text`` is the raw text fallback. Use only when ``structured_output``
        is None.
      - ``task_state == "completed"`` with empty reply usually means the payload shape
        was wrong — re-read input_schema and retry with a different ``data`` shape.

    On failure, never retry the same entity_id silently:
      - ``status: "error"`` from the card load → pick a different search result.
      - 90s timeout → tell the principal the service didn't respond and offer to retry.

    Args:
        entity_id: The service's registry id, e.g. 'zns:svc:c565a80ae1c70f794d7afaf8ca17f953'.
        text: Free-text payload for the A2A message text part. Use when input_schema
              accepts free text (single ``content``/``text`` field, or generic envelope).
        data: Structured payload for the A2A data part. Use when input_schema declares
              specific named fields. Shape it to match the schema's ``properties``.
        user_id: Auto-injected by the orchestrator — the calling principal. Used to sign
                 the request (x-zynd-auth) with their persona keypair. Optional: if absent
                 or the principal has no persona, the call is sent unsigned.
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

    # Sign with the principal's persona keypair so the service can attribute
    # the call (x-zynd-auth). Best-effort: if there's no active persona (or
    # signing fails for any reason) the message goes out unsigned — services
    # that don't require auth ignore the missing signature; those that do
    # reply with an auth error, which the JSON-RPC error branch maps below.
    if (user_id or "").strip():
        try:
            from mcp.tools.zynd_network import _persona_signer
            from agent.a2a.auth import sign_message

            signer = _persona_signer(user_id)
            if signer is not None:
                keypair, sender_agent_id, developer_proof = signer
                sign_message(
                    message,
                    keypair,
                    sender_agent_id,
                    developer_proof=developer_proof,
                )
        except Exception as e:  # noqa: BLE001 — never block the call on signing
            logger.warning("call_zynd_service: signing failed, sending unsigned: %s", e)

    # Deferred-push services accept the task immediately, run async, and push
    # status-only callbacks; the real result is pulled later via tasks/get in
    # the inbound push handler. Trigger when the caller asks for it
    # (`defer_to_push` in the payload) or the card advertises push. Falls back
    # to the blocking call when there's no persona to register a callback for.
    defer_to_push = bool(
        (isinstance(data, dict) and data.get("defer_to_push"))
        or (card.get("capabilities") or {}).get("pushNotifications") is True
    )
    push_cfg: dict | None = None
    callback_id: str | None = None
    if defer_to_push and (user_id or "").strip():
        from services import callbacks as cb_service
        try:
            callback_id, push_url, push_token = asyncio.run(
                cb_service.register(
                    user_id=user_id,
                    thread_id=message["contextId"],
                    peer_agent_id=eid,
                    our_message_id=message["messageId"],
                    origin_kind="mcp_tool",
                    origin_ref={"tool": "call_zynd_service", "entity_id": eid},
                    peer_a2a_url=url,
                )
            )
            push_cfg = {"url": push_url, "token": push_token}
        except Exception as e:  # noqa: BLE001
            logger.warning("call_zynd_service: callback register failed, using blocking: %s", e)
            callback_id = None
            push_cfg = None

    body = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        # blocking: hold the response until the task is terminal rather than
        # acking early with state="working" — for synchronous services. For
        # deferred-push services we instead register a callback URL and let
        # the result arrive asynchronously.
        "params": {
            "message": message,
            "configuration": (
                {"pushNotificationConfig": push_cfg} if push_cfg else {"blocking": True}
            ),
        },
    }
    timeout = 30.0 if push_cfg else 90.0

    try:
        with httpx.Client(timeout=timeout) as h:
            resp = h.post(url, json=body)
            resp.raise_for_status()
            envelope = resp.json()
    except httpx.TimeoutException:
        return {
            "status": "error",
            "entity_id": eid,
            "url": url,
            "error": f"Service call timed out ({int(timeout)}s).",
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
        code = err.get("code")
        if code in (ZYND_AUTH_FAILED, ZYND_REPLAY_DETECTED, ZYND_AUTH_EXPIRED):
            # The "service" rejected us for auth — it's actually a signed
            # agent. Tell the LLM to route via the signed call_zynd_agent.
            return {
                "status": "auth_required",
                "entity_id": eid,
                "url": url,
                "error_code": code,
                "error_message": err.get("message") or "Authentication required.",
                "hint": "This entity is a signed agent, not an unauthenticated service. "
                        "Call it via call_zynd_agent (which signs the request) instead.",
            }
        return {
            "status": "error",
            "entity_id": eid,
            "url": url,
            "error_code": code,
            "error_message": err.get("message") or "Unknown JSON-RPC error.",
            "error_data": err.get("data"),
            "error": f"JSON-RPC error from service: {err.get('message')}",
            "hint": "Network/registry issue or a malformed call — retry once or pick another result.",
        }

    task = envelope.get("result") or {}
    if not isinstance(task, dict):
        return {
            "status": "error",
            "entity_id": eid,
            "url": url,
            "error": "Service returned an unexpected result shape.",
        }

    if push_cfg and callback_id:
        from services import callbacks as cb_service
        try:
            cb_service.record_dispatch_ack(callback_id, task)
        except Exception as e:  # noqa: BLE001
            logger.warning("call_zynd_service: record_dispatch_ack failed: %s", e)
        return {
            "status": "dispatched",
            "pending": True,
            "entity_id": eid,
            "url": url,
            "task_id": task.get("id"),
            "callback_id": callback_id,
            "hint": (
                "Service is running asynchronously; its result will appear in "
                "the chat when ready. Tell the user you've dispatched it — do "
                "NOT wait or re-poll."
            ),
        }

    task_state = ((task.get("status") or {}).get("state")) or "unknown"
    reply_text, structured = _extract_reply_from_task(task)
    status, hint = classify_task_result(task_state, reply_text, structured)

    return {
        "status": status,
        "hint": hint,
        "entity_id": eid,
        "task_id": task.get("id"),
        "task_state": task_state,
        "reply_text": reply_text,
        "structured_output": structured,
    }
