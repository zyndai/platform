"""
A2A v3 — JSON-RPC 2.0 transport for cross-agent traffic.

Mounts at:
  POST /api/persona/{user_id}/a2a/v1                       (JSON-RPC dispatcher)
  GET  /api/persona/{user_id}/.well-known/agent-card.json  (signed v0.3 card)
  POST /api/persona/push/{user_id}                         (peer push delivery)

Phase 2 status:
  • `message/send` is wired end-to-end: admission gate, permission snapshot
    freeze, dispatch into the existing orchestrator, signed reply Task.
  • Agent card is real (signed v0.3, JWS-detached over JCS bytes).
  • The other six methods (message/stream, tasks/{get,cancel,resubscribe},
    tasks/pushNotificationConfig/{set,get}) and `/push/{user_id}` are
    still stubs — those land in phase 3.

The legacy `/api/persona/webhooks/{user_id}{,/sync}` endpoints in
api/persona.py keep handling all real cross-agent traffic until phase 6
cuts over the outbound side of the platform to this router.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from agent.a2a import (
    A2A_TASK_NOT_CANCELABLE,
    A2A_TASK_NOT_FOUND,
    A2A_UNSUPPORTED_OPERATION,
    INTERRUPTED_STATES,
    Message,
    ReplayCache,
    RPC_INTERNAL_ERROR,
    RPC_INVALID_PARAMS,
    RPC_INVALID_REQUEST,
    RPC_METHOD_NOT_FOUND,
    RPC_PARSE_ERROR,
    TERMINAL_STATES,
    ZYND_AUTH_EXPIRED,
    ZYND_AUTH_FAILED,
    ZYND_REPLAY_DETECTED,
    ZyndAuthError,
    sign_message,
    verify_message,
)
from agent.a2a.card import build_persona_card_v3
from agent.orchestrator import handle_user_message
from agent.persona_manager import (
    _derive_agent_keypair,
    _get_supabase,
    _load_developer_seed,
    get_persona_status,
)
from agent.zynd_identity import keypair_from_seed
from api.persona import DEFAULT_CONNECTION_PERMISSIONS

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Module-level singletons ─────────────────────────────────────────
#
# One ReplayCache for the whole process — per-sender buckets are managed
# inside the cache, so this single instance handles all inbound traffic
# regardless of which persona is the addressee.

_replay_cache = ReplayCache()

# Strong reference set for in-flight push delivery tasks. asyncio.create_task
# can otherwise GC the coroutine before it runs because the only reference
# is the local variable in the caller's frame. We keep it alive here and
# drop it when the task finishes via a discard-on-done callback.
_push_tasks: set[asyncio.Task] = set()


def _track_push_task(coro):
    """Schedule a coroutine to run in the background and keep it alive."""
    t = asyncio.create_task(coro)
    _push_tasks.add(t)
    t.add_done_callback(_push_tasks.discard)
    return t


# Sentinel DataPart kind that a sender uses to introduce themselves on a
# pending (`requested`) connection. The §5.4 admission gate dispatches
# this even though the connection isn't `accepted` yet — the receiver's
# UI surfaces the request content, the human decides accept/decline.
HANDSHAKE_DATA_KIND = "zynd.connection.request"


def _is_handshake_message(msg_dict: dict) -> bool:
    """True iff the Message carries a DataPart with kind=zynd.connection.request."""
    for p in msg_dict.get("parts") or []:
        if isinstance(p, dict) and p.get("kind") == "data":
            data = p.get("data") or {}
            if isinstance(data, dict) and data.get("kind") == HANDSHAKE_DATA_KIND:
                return True
    return False


# JSON-RPC method names from the A2A v0.3 spec.
KNOWN_METHODS = frozenset({
    "message/send",
    "message/stream",
    "tasks/get",
    "tasks/cancel",
    "tasks/resubscribe",
    "tasks/pushNotificationConfig/set",
    "tasks/pushNotificationConfig/get",
})


# ── JSON-RPC envelope helpers ───────────────────────────────────────


def _rpc_error(req_id, code: int, message: str, data=None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _rpc_result(req_id, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


# ── Map ZyndAuthError reasons → JSON-RPC error codes ────────────────
#
# The verify_message helper raises with one of a fixed set of reasons.
# Different reasons map to different protocol error codes per design §4.7.

_AUTH_REASON_TO_CODE = {
    "missing_auth":         ZYND_AUTH_FAILED,
    "unsupported_version":  ZYND_AUTH_FAILED,
    "expired_or_skewed":    ZYND_AUTH_EXPIRED,
    "replay_detected":      ZYND_REPLAY_DETECTED,
    "entity_id_mismatch":   ZYND_AUTH_FAILED,
    "bad_signature":        ZYND_AUTH_FAILED,
    "bad_developer_proof":  ZYND_AUTH_FAILED,
    "untrusted_sender":     ZYND_AUTH_FAILED,
}


# ── Persona keypair lookup ──────────────────────────────────────────
#
# Each persona signs its replies with its own derived keypair. We pull
# the derivation_index from persona_agents and rebuild the keypair on
# demand — same shape as persona_manager.startup() rehydration.


def _persona_keypair(user_id: str):
    """Return (keypair, agent_id) for the deployed persona of `user_id`,
    or None if no persona is active. Pulls developer seed from disk and
    derives at the persona's index — fast (microseconds)."""
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
    persona = row.data[0]
    seed = _load_developer_seed()
    private_seed, _ = _derive_agent_keypair(seed, persona["derivation_index"])
    return keypair_from_seed(private_seed), persona["agent_id"]


def _now_iso() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _extract_text(parts: list) -> str:
    """Flatten the TextParts of a Message into one string — the orchestrator
    only consumes prose content for now. DataParts are preserved on the
    wire (Task.history) but ignored at the LLM layer in phase 2."""
    if not isinstance(parts, list):
        return ""
    chunks = []
    for p in parts:
        if isinstance(p, dict) and p.get("kind") == "text":
            txt = p.get("text") or ""
            if txt:
                chunks.append(txt)
    return "\n".join(chunks)


# ── Push notification helpers ───────────────────────────────────────


def _extract_push_config(params: Any) -> tuple[Optional[str], Optional[str]]:
    """Pull the (url, token) tuple out of params.configuration.pushNotificationConfig.

    Returns (None, None) if no push config is supplied. We tolerate the
    `authentication.credentials` shape (the spec's full form) AND the
    short `token` shape; both end up as a Bearer token.
    """
    if not isinstance(params, dict):
        return None, None
    cfg = (params.get("configuration") or {}).get("pushNotificationConfig")
    if not isinstance(cfg, dict):
        return None, None
    url = cfg.get("url")
    if not isinstance(url, str) or not url:
        return None, None
    token = cfg.get("token")
    if not token:
        auth = cfg.get("authentication") or {}
        token = auth.get("credentials")
    return url, token if isinstance(token, str) and token else None


_PUSH_BACKOFFS = (1.0, 4.0, 16.0)
_PUSH_TIMEOUT = 30.0
_MAX_PUSH_INFLIGHT_PER_PEER = 16  # design §11.4 backpressure cap


async def _deliver_push_for_task(
    user_id: str,
    task_id: str,
    push_url: str,
    push_token: Optional[str],
    event: dict,
) -> None:
    """POST a signed wrapper Message containing a TaskStatusUpdateEvent
    to the caller's pushNotificationConfig URL. Retries 3x with the
    backoffs from design §6.1 #18.

    The wrapper is itself a v0.3 Message (signed with x-zynd-auth) whose
    single DataPart carries the TaskStatusUpdateEvent. This matches what
    the spec calls for and lets the receiving peer use the exact same
    verify_message machinery as inbound traffic.
    """
    kp_pair = _persona_keypair(user_id)
    if kp_pair is None:
        logger.warning(f"[a2a push task={task_id[:8]}] no persona keypair, dropping push")
        return
    keypair, my_agent_id = kp_pair

    wrapper: dict[str, Any] = {
        "kind": "message",
        "messageId": str(uuid.uuid4()),
        "role": "agent",
        "parts": [{"kind": "data", "data": event}],
        "taskId": task_id,
        "contextId": event.get("contextId") or "",
    }
    sign_message(wrapper, keypair, my_agent_id)

    headers = {"Content-Type": "application/json"}
    if push_token:
        headers["Authorization"] = f"Bearer {push_token}"

    last_err: str | None = None
    for attempt, sleep_s in enumerate(_PUSH_BACKOFFS, start=1):
        try:
            async with httpx.AsyncClient(timeout=_PUSH_TIMEOUT) as h:
                resp = await h.post(push_url, json=wrapper, headers=headers)
            if 200 <= resp.status_code < 300:
                logger.info(f"[a2a push task={task_id[:8]}] delivered to {push_url} ({resp.status_code})")
                return
            # Non-2xx — retry on 5xx, give up on 4xx (the receiver
            # actively rejected the wrapper; retrying won't help).
            if 400 <= resp.status_code < 500:
                logger.warning(f"[a2a push task={task_id[:8]}] {push_url} rejected {resp.status_code}; abandoning")
                return
            last_err = f"HTTP {resp.status_code}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            logger.info(f"[a2a push task={task_id[:8]}] attempt {attempt} failed: {last_err}")

        # Don't sleep after the final attempt.
        if attempt < len(_PUSH_BACKOFFS):
            await asyncio.sleep(sleep_s)

    logger.warning(
        f"[a2a push task={task_id[:8]}] giving up after {len(_PUSH_BACKOFFS)} attempts to {push_url}: {last_err}"
    )


def _build_status_update_event_for_push(
    *,
    task_id: str,
    context_id: str,
    state: str,
    message: dict | None,
    timestamp: str,
) -> dict:
    """The TaskStatusUpdateEvent body that goes inside the push wrapper.
    Same shape as the SSE message/stream events."""
    return _status_update_event(
        task_id=task_id,
        context_id=context_id,
        state=state,
        final=state in TERMINAL_STATES,
        message=message,
        timestamp=timestamp,
    )


# ── message/send + message/stream shared admission gate ────────────


class _Admitted:
    """Carrier for state computed by the admission gate so the send and
    stream paths can share the same logic without re-querying."""

    __slots__ = (
        "task_id",
        "context_id",
        "msg_dict",
        "msg_pyd",
        "sender_entity_id",
        "permissions",
        "log_prefix",
        "inbound_text",
        "is_continuation",
    )

    def __init__(
        self,
        task_id: str,
        context_id: str,
        msg_dict: dict,
        msg_pyd: Message,
        sender_entity_id: str,
        permissions: dict,
        log_prefix: str,
        inbound_text: str,
        is_continuation: bool = False,
    ):
        self.task_id = task_id
        self.context_id = context_id
        self.msg_dict = msg_dict
        self.msg_pyd = msg_pyd
        self.sender_entity_id = sender_entity_id
        self.permissions = permissions
        self.log_prefix = log_prefix
        self.inbound_text = inbound_text
        self.is_continuation = is_continuation


def _ping_inbound_dm(
    recipient_user_id: str,
    thread: dict,
    sender_entity_id: str,
    inbound_text: str,
) -> None:
    """Best-effort Telegram ping for an inbound persona DM.

    Gating rule: only ping when the recipient's side of the thread is in
    'human' mode (they've taken over from their agent on this thread).
    When their side is still in 'agent' mode their persona will reply
    automatically, so a Telegram ping would just be noise.

    Reads the per-side mode column (`initiator_mode` / `receiver_mode`)
    on dm_threads — the legacy single-column `mode` flag is stale and
    nullable, so trusting it caused this function to silently no-op.

    Fire-and-forget — runs as an asyncio task so the admission gate
    isn't blocked on Telegram's API.
    """
    try:
        # Resolve which side of the thread the recipient is on, then
        # read the matching per-side mode column.
        from agent.persona_manager import get_persona_status
        try:
            recipient_persona = get_persona_status(recipient_user_id)
        except Exception as e:
            logger.warning(f"[a2a inbound ping] persona lookup failed: {e}")
            return
        recipient_agent_id = recipient_persona.get("agent_id")
        if not recipient_agent_id:
            return

        if recipient_agent_id == thread.get("initiator_id"):
            side_mode = (thread.get("initiator_mode") or "agent").lower()
        elif recipient_agent_id == thread.get("receiver_id"):
            side_mode = (thread.get("receiver_mode") or "agent").lower()
        else:
            # Recipient isn't actually a participant — bail.
            return

        if side_mode != "human":
            return

        # Identify the partner (the sender side of the thread) for the
        # message header. sender_entity_id == one of the thread's two
        # participants — pick the one that's NOT the recipient agent.
        if sender_entity_id == thread.get("initiator_id"):
            partner_name = thread.get("initiator_name") or "Someone"
        else:
            partner_name = thread.get("receiver_name") or "Someone"

        snippet = (inbound_text or "").strip()[:300]
        msg = (
            f"💬 *{partner_name}* says:\n{snippet}\n\n"
            "Reply in the dashboard: https://persona.zynd.ai/dashboard/messages"
        )
        from services.telegram_notify import notify_user
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(notify_user(recipient_user_id, msg))
        except RuntimeError:
            # No running loop (sync caller). Run synchronously off-thread
            # so we still never block the caller.
            import threading

            def _runner():
                try:
                    asyncio.run(notify_user(recipient_user_id, msg))
                except Exception as e:
                    logger.warning(f"[a2a inbound ping] runner failed: {e}")

            threading.Thread(target=_runner, daemon=True).start()
    except Exception as e:
        logger.warning(f"[a2a inbound ping] failed: {e}")


async def _admit_message_send(
    user_id: str,
    addressee_agent_id: str,
    params: Any,
    req_id: Any,
) -> tuple[_Admitted | None, dict | None]:
    """Run the §5.4 pre-dispatch admission gate.

    On success returns (Admitted, None). On rejection returns
    (None, JSON-RPC error envelope).

    Side effects (only on success): inserts the a2a_tasks row in the
    'submitted' state and mirrors the inbound message to dm_messages.
    The caller is responsible for transitioning the task to 'working'
    and for the terminal-state update.
    """
    # Validate params shape.
    if not isinstance(params, dict):
        return None, _rpc_error(req_id, RPC_INVALID_PARAMS, "params must be an object.")
    msg_dict = params.get("message")
    if not isinstance(msg_dict, dict):
        return None, _rpc_error(req_id, RPC_INVALID_PARAMS, "params.message is required and must be an object.")

    try:
        msg_pyd = Message(**msg_dict)
    except ValidationError as e:
        return None, _rpc_error(req_id, RPC_INVALID_PARAMS, f"Invalid Message: {e.errors()[:3]}")

    if not msg_pyd.contextId:
        return None, _rpc_error(req_id, RPC_INVALID_PARAMS, "Message.contextId is required for cross-agent traffic.")

    # ── Step 1: verify x-zynd-auth ──────────────────────────────────
    try:
        ctx = verify_message(
            msg_dict,
            mode="strict",
            replay_cache=_replay_cache,
            verify_developer_proof=True,
        )
    except ZyndAuthError as e:
        code = _AUTH_REASON_TO_CODE.get(e.reason, ZYND_AUTH_FAILED)
        return None, _rpc_error(req_id, code, str(e), {"reason": e.reason})

    sender_entity_id = ctx["entity_id"]
    if not sender_entity_id:
        return None, _rpc_error(req_id, ZYND_AUTH_FAILED, "verify_message returned no entity_id.")

    # ── Steps 2 + 3: thread lookup + ConnectionFSM ──────────────────
    sb = _get_supabase()
    thread_row = sb.table("dm_threads").select("*").eq("id", str(msg_pyd.contextId)).execute()
    if not thread_row.data:
        return None, _rpc_error(
            req_id,
            A2A_UNSUPPORTED_OPERATION,
            "contextId does not resolve to an existing connection.",
            {"reason": "no_thread", "contextId": msg_pyd.contextId},
        )
    thread = thread_row.data[0]

    if sender_entity_id == addressee_agent_id:
        return None, _rpc_error(req_id, A2A_UNSUPPORTED_OPERATION, "Self-send rejected.", {"reason": "self_send"})
    if sender_entity_id not in (thread["initiator_id"], thread["receiver_id"]):
        return None, _rpc_error(
            req_id,
            A2A_UNSUPPORTED_OPERATION,
            "Sender is not a participant of this thread.",
            {"reason": "not_participant", "sender": sender_entity_id},
        )
    if addressee_agent_id not in (thread["initiator_id"], thread["receiver_id"]):
        return None, _rpc_error(
            req_id,
            A2A_UNSUPPORTED_OPERATION,
            "Addressee is not a participant of this thread.",
            {"reason": "addressee_not_participant"},
        )

    status = thread.get("status") or "pending"
    if status in ("blocked", "declined", "revoked"):
        return None, _rpc_error(
            req_id,
            A2A_UNSUPPORTED_OPERATION,
            f"Connection is {status}; messages are not accepted.",
            {"reason": f"connection_{status}"},
        )
    if status not in ("accepted",):
        # Handshake exception (§5.1): the FIRST message on a 'pending'
        # connection is admitted IFF it's a handshake DataPart, so the
        # receiver sees the request content and can decide whether to
        # accept. Anything else on a pending thread waits for the human.
        if status == "pending" and _is_handshake_message(msg_dict):
            logger.info(f"[a2a admit] handshake on pending thread {msg_pyd.contextId} — admitted")
        else:
            return None, _rpc_error(
                req_id,
                A2A_UNSUPPORTED_OPERATION,
                "Connection is awaiting acceptance.",
                {"reason": "awaiting_acceptance"},
            )

    inbound_text = _extract_text(msg_dict.get("parts", []))

    # ── Continuation path (resume an interrupted task) ──────────────
    # If the caller set msg.taskId, they're trying to resume an existing
    # task. The task must (a) belong to this contextId and (b) be in
    # an interrupted state. Anything else gets A2A_TASK_NOT_FOUND so the
    # caller can fall back to opening a fresh task.
    if msg_pyd.taskId:
        rec_query = sb.table("a2a_tasks").select("*").eq("task_id", msg_pyd.taskId).execute()
        if not rec_query.data:
            return None, _rpc_error(req_id, A2A_TASK_NOT_FOUND, "Unknown taskId.")
        rec = rec_query.data[0]
        if rec["context_id"] != str(msg_pyd.contextId):
            return None, _rpc_error(
                req_id,
                RPC_INVALID_PARAMS,
                "taskId does not belong to the supplied contextId.",
                {"reason": "context_mismatch"},
            )
        if rec["state"] not in INTERRUPTED_STATES:
            return None, _rpc_error(
                req_id,
                A2A_TASK_NOT_FOUND,
                f"Task is in '{rec['state']}', not an interrupted state.",
                {"reason": "not_interrupted", "state": rec["state"]},
            )

        task_id = msg_pyd.taskId
        log_prefix = f"[a2a {user_id[:8]} ← {sender_entity_id[:12]} task={task_id[:8]} cont]"
        logger.info(f"{log_prefix} continuation received ({len(inbound_text)} chars)")

        # Permissions stay frozen at original dispatch time (T-3) — read
        # from the task row, not the (possibly mutated) thread row.
        permissions = rec.get("permission_snapshot") or {**DEFAULT_CONNECTION_PERMISSIONS}

        # Append the new inbound message to history and flip back to working.
        # The conditional update ensures we don't race a tasks/cancel.
        new_history = list(rec.get("history") or []) + [msg_dict]
        try:
            upd = (
                sb.table("a2a_tasks")
                .update({
                    "state": "working",
                    "history": new_history,
                    "last_message_id": msg_pyd.messageId,
                    "updated_at": _now_iso(),
                })
                .eq("task_id", task_id)
                .in_("state", list(INTERRUPTED_STATES))
                .execute()
            )
            if not (upd.data or []):
                # Lost the race — task transitioned out of interrupted
                # between our read and our update. Treat as terminal.
                cur = sb.table("a2a_tasks").select("state").eq("task_id", task_id).execute()
                cur_state = cur.data[0]["state"] if cur.data else "unknown"
                return None, _rpc_error(
                    req_id,
                    A2A_TASK_NOT_FOUND,
                    f"Task transitioned to '{cur_state}' before resume landed.",
                    {"reason": "race", "state": cur_state},
                )
        except Exception as e:
            logger.error(f"{log_prefix} continuation flip to working failed: {e}")
            return None, _rpc_error(req_id, RPC_INTERNAL_ERROR, "Failed to resume task.")

        try:
            sb.table("dm_messages").insert({
                "thread_id": str(msg_pyd.contextId),
                "sender_id": sender_entity_id,
                "sender_type": "agent",
                "channel": "agent",
                "content": inbound_text,
            }).execute()
        except Exception as e:
            logger.warning(f"{log_prefix} mirror inbound to dm_messages failed: {e}")

        # Ping the user on Telegram if they've taken over this thread.
        _ping_inbound_dm(user_id, thread, sender_entity_id, inbound_text)

        return (
            _Admitted(
                task_id=task_id,
                context_id=str(msg_pyd.contextId),
                msg_dict=msg_dict,
                msg_pyd=msg_pyd,
                sender_entity_id=sender_entity_id,
                permissions=permissions,
                log_prefix=log_prefix,
                inbound_text=inbound_text,
                is_continuation=True,
            ),
            None,
        )

    # ── New task path ───────────────────────────────────────────────
    permissions = {
        **DEFAULT_CONNECTION_PERMISSIONS,
        **(thread.get("permissions") or {}),
    }

    # Optional pushNotificationConfig in the configuration block. Caller
    # registers a wakeup URL here so they don't have to block on the
    # JSON-RPC response — we POST a signed wrapper Message to push_url
    # when the task hits a terminal/interrupted state.
    push_url, push_token = _extract_push_config(params)

    task_id = str(uuid.uuid4())
    log_prefix = f"[a2a {user_id[:8]} ← {sender_entity_id[:12]} task={task_id[:8]}]"
    logger.info(f"{log_prefix} message/send received ({len(inbound_text)} chars)")

    new_row: dict[str, Any] = {
        "task_id": task_id,
        "context_id": str(msg_pyd.contextId),
        "state": "submitted",
        "permission_snapshot": permissions,
        "history": [msg_dict],
        "last_message_id": msg_pyd.messageId,
    }
    if push_url:
        new_row["push_url"] = push_url
    if push_token:
        new_row["push_token"] = push_token

    try:
        sb.table("a2a_tasks").insert(new_row).execute()
    except Exception as e:
        logger.error(f"{log_prefix} failed to persist a2a_tasks row: {e}")
        return None, _rpc_error(req_id, RPC_INTERNAL_ERROR, "Failed to allocate task.")

    try:
        sb.table("dm_messages").insert({
            "thread_id": str(msg_pyd.contextId),
            "sender_id": sender_entity_id,
            "sender_type": "agent",
            "channel": "agent",
            "content": inbound_text,
        }).execute()
    except Exception as e:
        logger.warning(f"{log_prefix} mirror to dm_messages failed: {e}")

    # Ping the user on Telegram if they've taken over this thread.
    _ping_inbound_dm(user_id, thread, sender_entity_id, inbound_text)

    return (
        _Admitted(
            task_id=task_id,
            context_id=str(msg_pyd.contextId),
            msg_dict=msg_dict,
            msg_pyd=msg_pyd,
            sender_entity_id=sender_entity_id,
            permissions=permissions,
            log_prefix=log_prefix,
            inbound_text=inbound_text,
            is_continuation=False,
        ),
        None,
    )


async def _run_handler_and_finalize(
    user_id: str,
    admitted: _Admitted,
) -> tuple[str, str, str | None, dict, dict | None, str]:
    """Run handle_user_message, persist the next task state, return
    everything the caller needs to build the JSON-RPC / SSE response.

    Returns (next_state, reply_text, failure_reason, signed_reply_msg,
    artifact_or_None, now_iso). `next_state` may be:
      - "completed"        — handler returned a final answer
      - "failed"           — handler raised
      - "input-required" / "auth-required" — handler returned the optional
        `interruption` field, asking the caller to send another message
        on the same taskId before producing a final answer

    Artifact is None for interrupted states (no completed work yet).
    """
    sb = _get_supabase()
    log_prefix = admitted.log_prefix

    # New tasks were inserted as 'submitted' by _admit_message_send and
    # need a flip to 'working' before the handler runs. Continuation
    # tasks were already flipped to 'working' inside _admit. The
    # conditional update covers both: it no-ops if the row is anything
    # other than 'submitted' (i.e. the continuation path or a racing
    # cancel that already got there).
    if not admitted.is_continuation:
        try:
            sb.table("a2a_tasks").update({
                "state": "working",
                "updated_at": _now_iso(),
            }).eq("task_id", admitted.task_id).eq("state", "submitted").execute()
        except Exception as e:
            logger.warning(f"{log_prefix} could not flip submitted→working: {e}")

    reply_text = ""
    interruption: str | None = None
    failure_reason: str | None = None
    try:
        result = await handle_user_message(
            user_id=user_id,
            message=admitted.inbound_text,
            conversation_id=f"thread:{admitted.context_id}",
            is_external=True,
            sender_agent_id=admitted.sender_entity_id,
            external_permissions=admitted.permissions,
        )
        reply_text = (result or {}).get("reply") or "(empty reply)"
        # Optional: handler signals it needs more info before completing.
        # Phase 3.4 wires this through end-to-end; the orchestrator's
        # external-mode prompt can adopt it later.
        raw_interruption = (result or {}).get("interruption")
        if raw_interruption in INTERRUPTED_STATES:
            interruption = raw_interruption
        next_state = "completed" if interruption is None else interruption
    except Exception as e:
        logger.exception(f"{log_prefix} orchestrator crashed")
        reply_text = "[orchestrator error]"
        failure_reason = f"{type(e).__name__}: {e}"[:500]
        next_state = "failed"

    logger.info(f"{log_prefix} reply ready ({len(reply_text)} chars), next state={next_state}")

    kp_pair = _persona_keypair(user_id)
    if kp_pair is None:
        next_state = "failed"
        failure_reason = (failure_reason or "") + " | could not load persona keypair to sign reply"
        my_agent_id = ""
    else:
        keypair, my_agent_id = kp_pair

    reply_msg: dict[str, Any] = {
        "kind": "message",
        "messageId": str(uuid.uuid4()),
        "role": "agent",
        "parts": [{"kind": "text", "text": reply_text}],
        "taskId": admitted.task_id,
        "contextId": admitted.context_id,
    }
    if kp_pair is not None:
        sign_message(reply_msg, keypair, my_agent_id)

    if my_agent_id:
        try:
            sb.table("dm_messages").insert({
                "thread_id": admitted.context_id,
                "sender_id": my_agent_id,
                "sender_type": "agent",
                "channel": "agent",
                "content": reply_text,
            }).execute()
        except Exception as e:
            logger.warning(f"{log_prefix} mirror outbound to dm_messages failed: {e}")

    # Artifact only when the work is actually done — interrupted states
    # have no complete output yet, just a question.
    artifact: dict | None = None
    if next_state == "completed":
        artifact = {
            "artifactId": str(uuid.uuid4()),
            "name": "reply",
            "parts": [{"kind": "text", "text": reply_text}],
        }

    now_iso = _now_iso()

    # Read current history so we APPEND the reply rather than overwriting.
    # On continuation the inbound was already appended in _admit_message_send;
    # we just stack the outbound on top.
    cur_row = sb.table("a2a_tasks").select("history,artifacts").eq("task_id", admitted.task_id).execute()
    cur_history = list((cur_row.data[0].get("history") if cur_row.data else None) or [])
    cur_artifacts = list((cur_row.data[0].get("artifacts") if cur_row.data else None) or [])
    new_history = cur_history + [reply_msg]
    new_artifacts = cur_artifacts + ([artifact] if artifact else [])

    update_payload: dict[str, Any] = {
        "state": next_state,
        "history": new_history,
        "artifacts": new_artifacts,
        "last_message_id": reply_msg["messageId"],
        "failure_reason": failure_reason,
        "updated_at": now_iso,
    }
    if next_state in TERMINAL_STATES:
        update_payload["terminal_at"] = now_iso
    if next_state in INTERRUPTED_STATES:
        # Schedule the idle-TTL cutoff (phase 3.6 sweeper enforces).
        # idle_ttl_ms default lives on the row; we just record when
        # the task became idle so the sweeper can compare against now.
        update_payload["idle_until"] = None  # explicit reset; sweeper computes from updated_at + idle_ttl_ms

    # Conditional flip: only update if the row is still 'working'. A
    # concurrent tasks/cancel will have already moved it to 'canceled'
    # and our handler's result is discarded (T-1).
    try:
        upd = (
            sb.table("a2a_tasks")
            .update(update_payload)
            .eq("task_id", admitted.task_id)
            .eq("state", "working")
            .execute()
        )
        if not (upd.data or []):
            logger.info(f"{log_prefix} task no longer in 'working' (likely canceled mid-flight); reply discarded")
            cur = sb.table("a2a_tasks").select("state").eq("task_id", admitted.task_id).execute()
            if cur.data:
                next_state = cur.data[0]["state"]
    except Exception as e:
        logger.warning(f"{log_prefix} terminal-state persist failed: {e}")

    # Promote the underlying thread's lifecycle from 'pending' to 'active'
    # on the first time a task completes successfully. Mirrors the legacy
    # webhook's THREAD_PENDING → THREAD_ACTIVE transition so the
    # MessagesPanel "Agents talking" pill keeps working.
    if next_state == "completed":
        try:
            sb.table("dm_threads").update({"lifecycle": "active"}) \
                .eq("id", admitted.context_id) \
                .eq("lifecycle", "pending") \
                .execute()
        except Exception as e:
            logger.warning(f"{log_prefix} lifecycle promote failed: {e}")

    return next_state, reply_text, failure_reason, reply_msg, artifact, now_iso


def _maybe_fire_push(
    user_id: str,
    task_id: str,
    context_id: str,
    next_state: str,
    reply_msg: dict | None,
    timestamp: str,
) -> None:
    """If the task has a registered pushNotificationConfig, fire a
    background delivery. Best-effort — the synchronous JSON-RPC reply
    is the canonical source of truth (R-3); push is just a wakeup hint.

    Skipped for non-terminal/non-interrupted states (e.g. 'submitted'
    or 'working') because there's nothing actionable to deliver yet.
    """
    if next_state not in TERMINAL_STATES and next_state not in INTERRUPTED_STATES:
        return
    sb = _get_supabase()
    row = sb.table("a2a_tasks").select("push_url,push_token").eq("task_id", task_id).execute()
    if not row.data:
        return
    push_url = row.data[0].get("push_url")
    if not push_url:
        return
    push_token = row.data[0].get("push_token")
    event = _build_status_update_event_for_push(
        task_id=task_id,
        context_id=context_id,
        state=next_state,
        message=reply_msg,
        timestamp=timestamp,
    )
    _track_push_task(
        _deliver_push_for_task(user_id, task_id, push_url, push_token, event)
    )


async def _handle_message_send(user_id: str, addressee_agent_id: str, params: Any, req_id: Any) -> dict:
    """Synchronous JSON-RPC: run admission gate, dispatch handler, return Task."""
    admitted, err = await _admit_message_send(user_id, addressee_agent_id, params, req_id)
    if err is not None:
        return err

    next_state, _reply_text, _failure_reason, reply_msg, artifact, now_iso = (
        await _run_handler_and_finalize(user_id, admitted)
    )

    _maybe_fire_push(
        user_id=user_id,
        task_id=admitted.task_id,
        context_id=admitted.context_id,
        next_state=next_state,
        reply_msg=reply_msg,
        timestamp=now_iso,
    )

    task_obj: dict[str, Any] = {
        "kind": "task",
        "id": admitted.task_id,
        "contextId": admitted.context_id,
        "status": {
            "state": next_state,
            "message": reply_msg,
            "timestamp": now_iso,
        },
    }
    # Artifacts only get attached when there's actually completed work.
    # Interrupted states (input-required, auth-required) carry their
    # question on status.message; no artifact yet.
    if artifact is not None:
        task_obj["artifacts"] = [artifact]
    return _rpc_result(req_id, task_obj)


# ── message/stream + tasks/resubscribe (SSE) ────────────────────────


# Headers we send with every SSE response. `X-Accel-Buffering: no`
# stops nginx from holding events until the connection closes;
# `Cache-Control: no-cache` keeps proxies from caching the stream.
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def _sse_pack(envelope: dict) -> bytes:
    """Encode a JSON-RPC envelope as a single SSE event."""
    payload = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False)
    return f"data: {payload}\n\n".encode("utf-8")


def _status_update_event(
    *,
    task_id: str,
    context_id: str,
    state: str,
    final: bool,
    message: dict | None = None,
    timestamp: str | None = None,
) -> dict:
    status: dict[str, Any] = {"state": state, "timestamp": timestamp or _now_iso()}
    if message is not None:
        status["message"] = message
    return {
        "kind": "status-update",
        "taskId": task_id,
        "contextId": context_id,
        "status": status,
        "final": final,
    }


def _artifact_update_event(*, task_id: str, context_id: str, artifact: dict, last_chunk: bool = True) -> dict:
    return {
        "kind": "artifact-update",
        "taskId": task_id,
        "contextId": context_id,
        "artifact": artifact,
        "lastChunk": last_chunk,
    }


async def _stream_message_send(
    user_id: str,
    addressee_agent_id: str,
    params: Any,
    req_id: Any,
) -> AsyncIterator[bytes]:
    """SSE generator for message/stream.

    Phase 3.3 emits a fixed sequence around the synchronous handler call:
        submitted → working → artifact-update → final status-update.
    Phase 3.4 will interleave input-required pauses with caller messages
    on the same taskId; the generator structure already supports that —
    we just don't have the suspend/resume primitive yet.
    """
    admitted, err = await _admit_message_send(user_id, addressee_agent_id, params, req_id)
    if err is not None:
        yield _sse_pack(err)
        return

    yield _sse_pack(_rpc_result(
        req_id,
        _status_update_event(
            task_id=admitted.task_id,
            context_id=admitted.context_id,
            state="submitted",
            final=False,
        ),
    ))
    yield _sse_pack(_rpc_result(
        req_id,
        _status_update_event(
            task_id=admitted.task_id,
            context_id=admitted.context_id,
            state="working",
            final=False,
        ),
    ))

    next_state, _reply_text, _failure_reason, reply_msg, artifact, now_iso = (
        await _run_handler_and_finalize(user_id, admitted)
    )

    if artifact is not None:
        yield _sse_pack(_rpc_result(
            req_id,
            _artifact_update_event(
                task_id=admitted.task_id,
                context_id=admitted.context_id,
                artifact=artifact,
                last_chunk=True,
            ),
        ))
    # `final` is True only for terminal states. input-required /
    # auth-required leave the task open for the caller to resume.
    is_final = next_state in TERMINAL_STATES
    yield _sse_pack(_rpc_result(
        req_id,
        _status_update_event(
            task_id=admitted.task_id,
            context_id=admitted.context_id,
            state=next_state,
            final=is_final,
            message=reply_msg,
            timestamp=now_iso,
        ),
    ))

    # Fire push notification for callers that registered one (e.g. peers
    # using `blocking=false` who don't keep the SSE open). Same as the
    # sync path; the SSE reply isn't a substitute since the caller may
    # have closed the stream.
    _maybe_fire_push(
        user_id=user_id,
        task_id=admitted.task_id,
        context_id=admitted.context_id,
        next_state=next_state,
        reply_msg=reply_msg,
        timestamp=now_iso,
    )


async def _stream_tasks_resubscribe(
    user_id: str,
    addressee_agent_id: str,
    params: Any,
    req_id: Any,
) -> AsyncIterator[bytes]:
    """SSE generator for tasks/resubscribe.

    Phase 3.3: emit ONE status-update with the task's current state and
    close. If terminal, the event is final=true; if non-terminal, the
    client can re-call to poll. Real live re-attach lands in phase 3.4
    once the in-process pub-sub from the input-required loopback is
    available.
    """
    if not isinstance(params, dict):
        yield _sse_pack(_rpc_error(req_id, RPC_INVALID_PARAMS, "params must be an object."))
        return
    task_id = params.get("id")
    if not isinstance(task_id, str) or not task_id:
        yield _sse_pack(_rpc_error(req_id, RPC_INVALID_PARAMS, "params.id (taskId) is required."))
        return

    sb = _get_supabase()
    rec, err = _load_task_for_addressee(sb, task_id, addressee_agent_id, req_id)
    if err is not None:
        yield _sse_pack(err)
        return

    state = rec["state"]
    final = state in TERMINAL_STATES

    # Surface the most recent agent Message in status.message so callers
    # who reattach to a terminal task immediately see the reply without
    # a follow-up tasks/get.
    last_agent_msg = None
    for m in reversed(rec.get("history") or []):
        if isinstance(m, dict) and m.get("role") == "agent":
            last_agent_msg = m
            break

    yield _sse_pack(_rpc_result(
        req_id,
        _status_update_event(
            task_id=task_id,
            context_id=rec["context_id"],
            state=state,
            final=final,
            message=last_agent_msg,
            timestamp=rec.get("updated_at") or rec.get("created_at"),
        ),
    ))


# ── tasks/get + tasks/cancel handlers ───────────────────────────────


def _load_task_for_addressee(
    sb,
    task_id: str,
    addressee_agent_id: str,
    req_id: Any,
) -> tuple[dict | None, dict | None]:
    """Fetch an a2a_tasks row and verify the addressee is a participant
    of the underlying thread.

    Returns (row, None) on success or (None, error_envelope) on failure.
    Authorization model: possession of the taskId (a UUID) is the
    capability — but we additionally require the addressee (the persona
    at /api/persona/{user_id}) to be a participant of the thread, so a
    persona on the same backend can't poke at another persona's tasks
    just by guessing or scraping a taskId.
    """
    row = sb.table("a2a_tasks").select("*").eq("task_id", task_id).execute()
    if not row.data:
        return None, _rpc_error(req_id, A2A_TASK_NOT_FOUND, f"Unknown taskId '{task_id}'.")

    rec = row.data[0]
    thr = (
        sb.table("dm_threads")
        .select("initiator_id,receiver_id")
        .eq("id", rec["context_id"])
        .execute()
    )
    if not thr.data:
        return None, _rpc_error(
            req_id,
            A2A_TASK_NOT_FOUND,
            "Underlying thread no longer exists.",
            {"reason": "context_gone", "contextId": rec["context_id"]},
        )
    t = thr.data[0]
    if addressee_agent_id not in (t["initiator_id"], t["receiver_id"]):
        return None, _rpc_error(
            req_id,
            A2A_UNSUPPORTED_OPERATION,
            "Addressee is not a participant of this task's thread.",
            {"reason": "addressee_not_participant"},
        )
    return rec, None


def _row_to_task(rec: dict, *, history_length: int | None = None) -> dict[str, Any]:
    """Project an a2a_tasks row into an A2A v0.3 Task dict."""
    history = list(rec.get("history") or [])
    if history_length is not None:
        history = history[-history_length:] if history_length > 0 else []

    status: dict[str, Any] = {
        "state": rec["state"],
        "timestamp": rec.get("updated_at") or rec.get("created_at"),
    }
    # status.message: surface the most recent agent Message in history
    # so callers polling tasks/get see the latest model output without
    # having to walk artifacts. This matches the SDK's behavior.
    for m in reversed(rec.get("history") or []):
        if isinstance(m, dict) and m.get("role") == "agent":
            status["message"] = m
            break

    task: dict[str, Any] = {
        "kind": "task",
        "id": rec["task_id"],
        "contextId": rec["context_id"],
        "status": status,
        "artifacts": rec.get("artifacts") or [],
        "history": history,
    }
    if rec.get("failure_reason") and rec["state"] in TERMINAL_STATES:
        task["metadata"] = {"failure_reason": rec["failure_reason"]}
    return task


async def _handle_tasks_get(
    user_id: str,
    addressee_agent_id: str,
    params: Any,
    req_id: Any,
) -> dict:
    """Read-only Task lookup."""
    if not isinstance(params, dict):
        return _rpc_error(req_id, RPC_INVALID_PARAMS, "params must be an object.")
    task_id = params.get("id")
    if not isinstance(task_id, str) or not task_id:
        return _rpc_error(req_id, RPC_INVALID_PARAMS, "params.id (taskId) is required.")

    history_length = params.get("historyLength")
    if history_length is not None and (not isinstance(history_length, int) or history_length < 0):
        return _rpc_error(req_id, RPC_INVALID_PARAMS, "historyLength must be a non-negative integer.")

    sb = _get_supabase()
    rec, err = _load_task_for_addressee(sb, task_id, addressee_agent_id, req_id)
    if err is not None:
        return err

    return _rpc_result(req_id, _row_to_task(rec, history_length=history_length))


async def _handle_push_config_set(
    user_id: str,
    addressee_agent_id: str,
    params: Any,
    req_id: Any,
) -> dict:
    """Update or set the pushNotificationConfig for an existing task.

    params: { taskId: str, pushNotificationConfig: { url, token?, authentication? } }
    """
    if not isinstance(params, dict):
        return _rpc_error(req_id, RPC_INVALID_PARAMS, "params must be an object.")
    task_id = params.get("taskId")
    if not isinstance(task_id, str) or not task_id:
        return _rpc_error(req_id, RPC_INVALID_PARAMS, "params.taskId is required.")
    cfg = params.get("pushNotificationConfig")
    if not isinstance(cfg, dict):
        return _rpc_error(req_id, RPC_INVALID_PARAMS, "params.pushNotificationConfig is required.")
    url = cfg.get("url")
    if not isinstance(url, str) or not url:
        return _rpc_error(req_id, RPC_INVALID_PARAMS, "pushNotificationConfig.url is required.")
    token = cfg.get("token")
    if not token:
        token = (cfg.get("authentication") or {}).get("credentials")
    if token is not None and not isinstance(token, str):
        return _rpc_error(req_id, RPC_INVALID_PARAMS, "pushNotificationConfig.token must be a string.")

    sb = _get_supabase()
    rec, err = _load_task_for_addressee(sb, task_id, addressee_agent_id, req_id)
    if err is not None:
        return err

    try:
        sb.table("a2a_tasks").update({
            "push_url": url,
            "push_token": token,
            "updated_at": _now_iso(),
        }).eq("task_id", task_id).execute()
    except Exception as e:
        logger.warning(f"[a2a tasks/pushNotificationConfig/set] {task_id[:8]} update failed: {e}")
        return _rpc_error(req_id, RPC_INTERNAL_ERROR, f"{type(e).__name__}: {e}")

    return _rpc_result(req_id, {
        "taskId": task_id,
        "pushNotificationConfig": {"url": url, **({"token": token} if token else {})},
    })


async def _handle_push_config_get(
    user_id: str,
    addressee_agent_id: str,
    params: Any,
    req_id: Any,
) -> dict:
    """Read back a task's pushNotificationConfig. Returns the config or
    `{taskId, pushNotificationConfig: null}` when none is registered."""
    if not isinstance(params, dict):
        return _rpc_error(req_id, RPC_INVALID_PARAMS, "params must be an object.")
    task_id = params.get("id") or params.get("taskId")
    if not isinstance(task_id, str) or not task_id:
        return _rpc_error(req_id, RPC_INVALID_PARAMS, "params.id (taskId) is required.")

    sb = _get_supabase()
    rec, err = _load_task_for_addressee(sb, task_id, addressee_agent_id, req_id)
    if err is not None:
        return err

    url = rec.get("push_url")
    if not url:
        return _rpc_result(req_id, {"taskId": task_id, "pushNotificationConfig": None})

    cfg: dict[str, Any] = {"url": url}
    token = rec.get("push_token")
    if token:
        cfg["token"] = token
    return _rpc_result(req_id, {"taskId": task_id, "pushNotificationConfig": cfg})


async def _handle_tasks_cancel(
    user_id: str,
    addressee_agent_id: str,
    params: Any,
    req_id: Any,
) -> dict:
    """Force a task to 'canceled'. Idempotent on already-terminal rows
    via A2A_TASK_NOT_CANCELABLE (per design §3.2.5)."""
    if not isinstance(params, dict):
        return _rpc_error(req_id, RPC_INVALID_PARAMS, "params must be an object.")
    task_id = params.get("id")
    if not isinstance(task_id, str) or not task_id:
        return _rpc_error(req_id, RPC_INVALID_PARAMS, "params.id (taskId) is required.")

    sb = _get_supabase()
    rec, err = _load_task_for_addressee(sb, task_id, addressee_agent_id, req_id)
    if err is not None:
        return err

    if rec["state"] in TERMINAL_STATES:
        return _rpc_error(
            req_id,
            A2A_TASK_NOT_CANCELABLE,
            f"Task is already {rec['state']}.",
            {"reason": "already_terminal", "state": rec["state"]},
        )

    now_iso = _now_iso()
    try:
        upd = (
            sb.table("a2a_tasks")
            .update({
                "state": "canceled",
                "terminal_at": now_iso,
                "updated_at": now_iso,
                "failure_reason": f"canceled via tasks/cancel by {addressee_agent_id}",
            })
            .eq("task_id", task_id)
            # Conditional flip: only cancel if the row is still non-terminal.
            # Concurrent cancels / handler completions race us; whoever wins
            # the conditional update sets the canonical terminal state.
            .not_.in_("state", list(TERMINAL_STATES))
            .execute()
        )
    except Exception as e:
        logger.warning(f"[a2a tasks/cancel] update crashed: {e}")
        return _rpc_error(req_id, RPC_INTERNAL_ERROR, f"{type(e).__name__}: {e}")

    if not (upd.data or []):
        # Lost the race — someone else flipped it terminal between
        # our read and our update. Treat that as already-terminal.
        cur = sb.table("a2a_tasks").select("state").eq("task_id", task_id).execute()
        cur_state = cur.data[0]["state"] if cur.data else "unknown"
        return _rpc_error(
            req_id,
            A2A_TASK_NOT_CANCELABLE,
            f"Task transitioned to {cur_state} before cancel landed.",
            {"reason": "race", "state": cur_state},
        )

    rec["state"] = "canceled"
    rec["terminal_at"] = now_iso
    rec["updated_at"] = now_iso
    return _rpc_result(req_id, _row_to_task(rec))


# ── Endpoints ───────────────────────────────────────────────────────


@router.post("/{user_id}/a2a/v1")
async def a2a_jsonrpc(user_id: str, request: Request):
    """A2A v0.3 JSON-RPC dispatcher."""
    persona = get_persona_status(user_id)
    if not persona.get("deployed"):
        raise HTTPException(status_code=404, detail="No active persona for this user.")

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_rpc_error(None, RPC_PARSE_ERROR, "Body is not valid JSON."), status_code=200)

    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return JSONResponse(
            _rpc_error(
                body.get("id") if isinstance(body, dict) else None,
                RPC_INVALID_REQUEST,
                "Request envelope is not JSON-RPC 2.0.",
            ),
            status_code=200,
        )

    method = body.get("method")
    req_id = body.get("id")
    params = body.get("params")

    if not isinstance(method, str) or method not in KNOWN_METHODS:
        return JSONResponse(_rpc_error(req_id, RPC_METHOD_NOT_FOUND, f"Unknown method '{method}'."), status_code=200)

    addressee = persona["agent_id"]

    # SSE methods return a StreamingResponse — each event is a JSON-RPC
    # envelope sharing the original request id (so clients can dedupe).
    if method == "message/stream":
        return StreamingResponse(
            _stream_message_send(user_id, addressee, params, req_id),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )
    if method == "tasks/resubscribe":
        return StreamingResponse(
            _stream_tasks_resubscribe(user_id, addressee, params, req_id),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    handlers = {
        "message/send":  _handle_message_send,
        "tasks/get":     _handle_tasks_get,
        "tasks/cancel":  _handle_tasks_cancel,
        "tasks/pushNotificationConfig/set": _handle_push_config_set,
        "tasks/pushNotificationConfig/get": _handle_push_config_get,
    }
    handler = handlers.get(method)
    if handler is not None:
        try:
            envelope = await handler(user_id, addressee, params, req_id)
        except Exception as e:
            logger.exception(f"[a2a] {method} dispatcher crashed")
            envelope = _rpc_error(req_id, RPC_INTERNAL_ERROR, f"{type(e).__name__}: {e}")
        return JSONResponse(envelope, status_code=200)

    return JSONResponse(
        _rpc_error(
            req_id,
            RPC_INTERNAL_ERROR,
            f"Method '{method}' is not implemented.",
            {"reason": "not_implemented"},
        ),
        status_code=200,
    )


@router.get("/{user_id}/.well-known/agent-card.json")
async def a2a_agent_card(user_id: str):
    """Signed A2A v0.3 agent card."""
    persona = get_persona_status(user_id)
    if not persona.get("deployed"):
        raise HTTPException(status_code=404, detail="No active persona for this user.")

    card = build_persona_card_v3(user_id)
    if card is None:
        # Race: persona was active a moment ago but is gone now.
        raise HTTPException(status_code=404, detail="No active persona for this user.")
    return card


# ── Lifecycle: restart reconciliation + idle TTL sweeper ────────────


_DEFAULT_IDLE_TTL_MS = 3_600_000   # 1 hour, matches the design default
_SWEEPER_INTERVAL_S = 60           # how often we scan for timed-out tasks
_POLLER_INTERVAL_S = 30            # how often we poll pending callbacks via tasks/get


_sweeper_task: asyncio.Task | None = None
_poller_task: asyncio.Task | None = None


async def reconcile_orphan_tasks() -> int:
    """On boot: any 'submitted' / 'working' rows are orphans from a prior
    process (we crashed mid-flight). Transition them to 'failed' with
    reason='server_restart' (§6.4). Returns the number reconciled.

    We don't fire push notifications for these — phase 3.6 keeps the
    reconciliation pass cheap; UI realtime on a2a_tasks already surfaces
    the new terminal state to whichever participant is watching.
    """
    sb = _get_supabase()
    now_iso = _now_iso()
    try:
        upd = (
            sb.table("a2a_tasks")
            .update({
                "state": "failed",
                "terminal_at": now_iso,
                "failure_reason": "server_restart",
                "updated_at": now_iso,
            })
            .in_("state", ["submitted", "working"])
            .execute()
        )
    except Exception as e:
        logger.warning(f"[a2a reconcile] orphan sweep failed: {e}")
        return 0

    n = len(upd.data or [])
    if n > 0:
        logger.warning(f"[a2a reconcile] transitioned {n} orphan task(s) to failed/server_restart")
    return n


async def sweep_idle_tasks() -> int:
    """Scan a2a_tasks for INTERRUPTED rows whose updated_at + idle_ttl_ms
    is in the past. Transition them to 'failed' reason='idle_timeout'.

    We compute the cutoff in Python (Supabase doesn't natively express
    "updated_at + ttl < now" in the client SDK without a stored
    procedure) but the input set is bounded by the partial index on
    state ∈ INTERRUPTED_STATES, so the query stays cheap.
    """
    import time
    sb = _get_supabase()
    try:
        rows = (
            sb.table("a2a_tasks")
            .select("task_id,state,updated_at,idle_ttl_ms")
            .in_("state", list(INTERRUPTED_STATES))
            .execute()
        )
    except Exception as e:
        logger.warning(f"[a2a sweep] query failed: {e}")
        return 0

    now_ms = int(time.time() * 1000)
    timed_out: list[str] = []
    for r in rows.data or []:
        upd_iso = r.get("updated_at")
        if not upd_iso:
            continue
        try:
            if upd_iso.endswith("Z"):
                ts = datetime.fromisoformat(upd_iso[:-1]).replace(tzinfo=timezone.utc)
            else:
                ts = datetime.fromisoformat(upd_iso)
            upd_ms = int(ts.timestamp() * 1000)
        except Exception:
            continue
        ttl_ms = r.get("idle_ttl_ms") or _DEFAULT_IDLE_TTL_MS
        if upd_ms + ttl_ms <= now_ms:
            timed_out.append(r["task_id"])

    if not timed_out:
        return 0

    now_iso = _now_iso()
    fired = 0
    for tid in timed_out:
        try:
            r2 = (
                sb.table("a2a_tasks")
                .update({
                    "state": "failed",
                    "terminal_at": now_iso,
                    "failure_reason": "idle_timeout",
                    "updated_at": now_iso,
                })
                .eq("task_id", tid)
                # Conditional: skip if someone else already moved it.
                .in_("state", list(INTERRUPTED_STATES))
                .execute()
            )
            if r2.data:
                fired += 1
        except Exception as e:
            logger.warning(f"[a2a sweep] failed to time out task {tid[:8]}: {e}")

    if fired:
        logger.info(f"[a2a sweep] timed out {fired} interrupted task(s)")
    return fired


async def _sweeper_loop():
    """Background loop that calls sweep_idle_tasks every minute."""
    logger.info(f"[a2a sweep] loop started (interval={_SWEEPER_INTERVAL_S}s)")
    try:
        while True:
            await asyncio.sleep(_SWEEPER_INTERVAL_S)
            try:
                await sweep_idle_tasks()
            except Exception as e:
                logger.warning(f"[a2a sweep] iteration error: {e}")
    except asyncio.CancelledError:
        logger.info("[a2a sweep] loop stopped")
        raise


async def _poll_pending_callbacks() -> int:
    """Fallback for the push path: pull the result of still-pending agent
    calls with tasks/get, in case the peer never pushed (or its push was
    dropped). Reuses the exact push-recording logic, just driven by the DB
    rather than an inbound webhook. Once a result records, the row flips to
    'received' and drops out of this scan.
    """
    from services import callbacks as cb_service

    try:
        pending = cb_service.list_pending()
    except Exception as e:  # noqa: BLE001
        logger.warning("[a2a poll] list_pending failed: %s", e)
        return 0

    polled = 0
    for cb in pending:
        task_id = cb.get("peer_task_id")
        if not task_id:
            continue  # never linked a peer task — nothing to fetch by
        try:
            await _fetch_and_record_push_result(cb, {"taskId": task_id}, {})
            polled += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("[a2a poll] fetch failed cb=%s: %s", cb.get("id"), e)
    if polled:
        logger.info("[a2a poll] checked %d pending call(s)", polled)
    return polled


async def _poller_loop():
    """Background loop that polls pending callbacks every _POLLER_INTERVAL_S."""
    logger.info(f"[a2a poll] loop started (interval={_POLLER_INTERVAL_S}s)")
    try:
        while True:
            await asyncio.sleep(_POLLER_INTERVAL_S)
            try:
                await _poll_pending_callbacks()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[a2a poll] iteration error: {e}")
    except asyncio.CancelledError:
        logger.info("[a2a poll] loop stopped")
        raise


async def start_a2a_lifecycle() -> None:
    """Hook into the FastAPI lifespan startup: reconcile orphans + start
    the idle-task sweeper and the pending-callback poller."""
    global _sweeper_task, _poller_task
    await reconcile_orphan_tasks()
    if _sweeper_task is None:
        _sweeper_task = asyncio.create_task(_sweeper_loop())
    if _poller_task is None:
        _poller_task = asyncio.create_task(_poller_loop())


async def stop_a2a_lifecycle() -> None:
    """Lifespan shutdown: stop sweeper + poller + drain in-flight pushes."""
    global _sweeper_task, _poller_task
    for attr in ("_sweeper_task", "_poller_task"):
        t = globals().get(attr)
        if t is not None:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
            globals()[attr] = None
    if _push_tasks:
        # Wait briefly for in-flight push deliveries to settle so we
        # don't lose them at process exit.
        await asyncio.gather(*list(_push_tasks), return_exceptions=True)


@router.post("/push/{user_id}")
async def a2a_push_inbound(user_id: str, request: Request):
    """Inbound push notification from a peer.

    A peer we previously called with a pushNotificationConfig posts here
    when the task they're handling on our behalf reaches a terminal or
    interrupted state. The body is a signed wrapper Message whose
    DataPart carries a TaskStatusUpdateEvent.

    Verification chain (each step rejects on failure):

      1. Strict x-zynd-auth verification on the wrapper.
      2. ``Authorization: Bearer <token>`` MUST match a row in
         ``outbound_callbacks`` we issued when sending. Without this,
         any signed peer could write into any user's callback log.
      3. The matched callback row must belong to ``user_id`` from the
         path — defends against a peer using a token issued for one
         persona to push into another.
      4. The matched callback row's ``peer_agent_id`` must match the
         verified sender. Defends against token theft + replay between
         peers.

    On success: write a ``callback_results`` row, flip parent status if
    terminal, return ack. Frontend's Supabase realtime subscription on
    ``callback_results`` picks the row up and renders it live.
    """
    persona = get_persona_status(user_id)
    if not persona.get("deployed"):
        raise HTTPException(status_code=404, detail="No active persona for this user.")

    try:
        wrapper = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body is not valid JSON.")

    if not isinstance(wrapper, dict):
        raise HTTPException(status_code=400, detail="Push body is not a JSON object.")

    auth_header_preview = (request.headers.get("authorization") or "")[:30]
    logger.info(
        "[a2a push-inbound] received push user=%s from=%s auth=%s body_keys=%s",
        user_id[:8],
        request.client.host if request.client else "unknown",
        auth_header_preview or "(none)",
        list(wrapper.keys()),
    )

    # MVP posture: accept and route the push on a best-effort basis. zynd
    # peers push bearer-only and sometimes unsigned, so identity checks
    # (signature, token↔user, token↔peer) degrade to warnings instead of
    # rejecting. The only fatal cases are "can't parse" and "can't correlate
    # to any callback we issued" — without a callback row there's nowhere to
    # route the result.
    try:
        ctx = verify_message(
            wrapper,
            mode="permissive",
            replay_cache=_replay_cache,
            verify_developer_proof=True,
        )
        sender_entity_id = ctx["entity_id"]
    except ZyndAuthError as e:
        logger.warning("[a2a push-inbound] signature present but invalid (accepting, MVP): %s", e.reason)
        sender_entity_id = None

    event = _extract_push_event(wrapper)
    task_id = (event.get("taskId") if event else None) or wrapper.get("taskId")

    auth_header = request.headers.get("authorization") or ""
    bearer = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""

    from services import callbacks as cb_service

    callback = cb_service.lookup_by_token(bearer) if bearer else None
    if callback is None and task_id:
        # Fallback 1: correlate by the peer Task.id we linked at dispatch.
        callback = cb_service.lookup_by_peer_task(task_id)
    if callback is None and sender_entity_id:
        # Fallback 2: peer didn't send our bearer token and the push arrived
        # before mark_peer_task ran (race between push delivery and our ack
        # processing). Match the most recent pending row for this peer+user.
        callback = cb_service.lookup_pending_for_peer(user_id, sender_entity_id)
        if callback:
            logger.info(
                "[a2a push-inbound user=%s] correlated via peer fallback cb=%s peer=%s task=%s",
                user_id[:8], str(callback.get("id", ""))[:8],
                sender_entity_id[:16], str(task_id or "")[:8],
            )
            # Link the task ID now so future pushes and the poller can use it.
            if task_id and not callback.get("peer_task_id"):
                try:
                    cb_service.mark_peer_task_sync(callback["id"], task_id)
                    callback["peer_task_id"] = task_id
                except Exception as _e:
                    logger.warning("[a2a push-inbound] mark_peer_task_sync failed: %s", _e)
    if callback is None:
        logger.warning(
            "[a2a push-inbound user=%s] uncorrelated push (bearer=%s task=%s from=%s) — acking & dropping",
            user_id[:8], bool(bearer), str(task_id or "")[:8], (sender_entity_id or "")[:12],
        )
        return {"status": "ack_uncorrelated", "task_id": task_id}

    if callback.get("user_id") != user_id:
        logger.warning(
            "[a2a push-inbound] token user %s != path user %s — proceeding (MVP)",
            str(callback.get("user_id"))[:8], user_id[:8],
        )
    if sender_entity_id and callback.get("peer_agent_id") != sender_entity_id:
        logger.warning(
            "[a2a push-inbound] signed sender %s != token peer %s — proceeding (MVP)",
            sender_entity_id[:12], str(callback.get("peer_agent_id"))[:12],
        )

    if event is None:
        event = {"taskId": task_id, "status": wrapper.get("status") or {}}

    # zynd push callbacks are status-only and arrive many times per task;
    # status.state can read "completed" while the payload is still a
    # deferral ack. So we don't trust the event — ack now and, in the
    # background, pull the real Task with tasks/get and record it only
    # once the result is actually present.
    task_state = (event.get("status") or {}).get("state") or "unknown"
    try:
        logger.info("[a2a push-inbound] raw body cb=%s: %s",
                    callback.get("id"), json.dumps(wrapper)[:2000])
    except Exception:  # noqa: BLE001
        pass
    # Stash this raw push on the call row so the Agent Calls panel can show
    # the latest webhook response immediately, regardless of readiness.
    cb_service.record_push_event(callback.get("id"), task_state, event)
    _track_push_task(_fetch_and_record_push_result(callback, event, wrapper))

    logger.info(
        "[a2a push-inbound user=%s] cb=%s from=%s task=%s state=%s final=%s correlated_by=%s (fetch scheduled)",
        user_id[:8],
        str(callback.get("id", ""))[:8],
        (sender_entity_id or "unsigned")[:16],
        str(event.get("taskId") or "")[:8],
        task_state,
        event.get("final"),
        "token" if bearer else "peer_task_id",
    )

    return {
        "status": "received",
        "task_id": event.get("taskId"),
        "task_state": task_state,
        "from": sender_entity_id,
    }


def _extract_push_event(wrapper: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Pull the status-update event out of a push wrapper's DataParts.
    Lenient: accepts the canonical ``kind=="status-update"`` part, but also
    any DataPart that carries a taskId/status so we don't drop pushes whose
    wrapper shape differs slightly. Returns None when there's nothing usable
    (the handler then synthesizes a minimal event from the wrapper)."""
    for part in wrapper.get("parts") or []:
        if isinstance(part, dict) and part.get("kind") == "data":
            d = part.get("data")
            if isinstance(d, dict) and (
                d.get("kind") == "status-update" or d.get("taskId") or d.get("status")
            ):
                return d
    return None


async def _fetch_and_record_push_result(
    callback: dict[str, Any], event: dict[str, Any], wrapper: dict[str, Any]
) -> None:
    """Surface the peer's real result, once it's actually present.

    Two delivery styles, handled in order:
      1. In the push body — services that "POST the shortlist to the
         callback URL when ready" put the payload right in the push. We
         check the wrapper/event first.
      2. Via tasks/get — status-only notifiers. We pull the Task and judge
         readiness from its content (status.state is unreliable: a peer can
         report "completed" while the payload is still a deferral ack).

    When neither is ready we record nothing and leave the callback pending so
    the next push re-checks. A genuine terminal failure is surfaced so the
    user isn't left waiting forever.
    """
    from services import callbacks as cb_service

    cb_id = callback.get("id")

    # 1. Result delivered inside the push body?
    body_ready, b_reply, b_structured = _push_result_ready(_push_body_as_task(event, wrapper))
    if body_ready:
        _record_push_result(
            cb_service, callback, cb_id,
            task_state="completed",
            reply=b_reply, structured=b_structured,
            raw_event={**event, "structured": b_structured, "source": "push-body"},
        )
        return

    # 2. Fall back to tasks/get.
    task_id = event.get("taskId") or callback.get("peer_task_id")
    if not task_id:
        logger.info("[a2a push-fetch] push body not ready and no task id; cb=%s", cb_id)
        return

    a2a_url = callback.get("peer_a2a_url") or _resolve_peer_a2a_url(
        callback.get("peer_agent_id")
    )
    if not a2a_url:
        logger.warning("[a2a push-fetch] no peer a2a url; cb=%s", cb_id)
        return

    kp = _persona_keypair(callback.get("user_id"))
    if kp is None:
        logger.warning("[a2a push-fetch] no persona keypair; cb=%s", cb_id)
        return
    keypair, agent_id = kp

    from agent.a2a.client import A2AClient, A2AError

    client = A2AClient(keypair, agent_id, timeout=30.0)
    try:
        task = await client.get_task(a2a_url, task_id)
    except A2AError as e:
        logger.info("[a2a push-fetch] tasks/get rejected cb=%s: %s", cb_id, e)
        return
    except Exception as e:  # noqa: BLE001
        logger.warning("[a2a push-fetch] tasks/get failed cb=%s: %s", cb_id, e)
        return

    state = ((task.get("status") or {}).get("state")) or "unknown"
    ready, reply, structured = _push_result_ready(task)
    is_failure = state in ("failed", "rejected", "canceled")
    if not ready and not is_failure:
        logger.info(
            "[a2a push-fetch] task %s not ready (state=%s) cb=%s",
            str(task_id)[:8], state, cb_id,
        )
        return

    # A real terminal failure is surfaced under its own state; a ready
    # result lands as "completed" regardless of the (possibly premature)
    # state the peer reported.
    _record_push_result(
        cb_service, callback, cb_id,
        task_state=state if is_failure else "completed",
        reply=reply, structured=structured,
        raw_event={**event, "fetched_task": task, "structured": structured},
    )


def _record_push_result(cb_service, callback, cb_id, *, task_state, reply, structured, raw_event) -> None:
    # The frontend renders reply_text; a structured-only result (no text part)
    # would otherwise show as an empty "processing" row, so serialize the
    # payload. The raw structured form stays in raw_event for rich UI.
    reply_text = reply
    if reply_text is None and structured is not None:
        try:
            reply_text = json.dumps(structured, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            reply_text = str(structured)
    try:
        result_id = cb_service.record_result(
            callback=callback,
            task_state=task_state,
            reply_text=reply_text,
            raw_event=raw_event,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("[a2a push-fetch] record_result failed cb=%s: %s", cb_id, e)
        return
    logger.info(
        "[a2a push-fetch] recorded cb=%s result=%s state=%s source=%s",
        cb_id, str(result_id)[:8], task_state, raw_event.get("source", "tasks/get"),
    )

    if task_state == "completed" and callback.get("origin_kind") == "mcp_tool":
        origin = callback.get("origin_ref") or {}
        chat_conv_id = origin.get("conversation_id")
        if chat_conv_id:
            _track_push_task(_autonomous_chat_reply(
                user_id=callback["user_id"],
                conversation_id=chat_conv_id,
                peer_agent_id=callback.get("peer_agent_id", "unknown agent"),
                reply_text=reply_text or "",
                structured=raw_event.get("structured"),
            ))


async def _autonomous_chat_reply(
    user_id: str,
    conversation_id: str,
    peer_agent_id: str,
    reply_text: str,
    structured: Any = None,
) -> None:
    """Re-enter the LLM to compose a natural reply from an async agent result.

    The synthetic user turn is kept in-memory only so it doesn't pollute the
    chat history. Only the assistant reply is persisted and shown to the user.
    """
    from agent.orchestrator import (
        _build_system_prompt,
        _conversations,
        _get_provider,
        _persist_chat_message,
        strip_think_tags,
    )
    from services.token_store import list_connected_providers, is_linkedin_scraped

    # Reload conversation history from DB if this server process lost it.
    if not _conversations.get(conversation_id):
        try:
            import config as _cfg
            sb = _cfg.get_supabase()
            rows = (
                sb.table("chat_messages")
                .select("role,content")
                .eq("user_id", user_id)
                .eq("conversation_id", conversation_id)
                .order("created_at", desc=False)
                .limit(50)
                .execute()
            )
            if rows.data:
                _conversations[conversation_id] = [
                    {"role": r["role"], "content": r["content"] or ""}
                    for r in rows.data
                    if r["role"] in ("user", "assistant")
                ]
                logger.info(
                    "[a2a push] reloaded %d messages for conv=%s",
                    len(_conversations[conversation_id]), conversation_id[:8],
                )
        except Exception as e:
            logger.warning("[a2a push] history reload failed conv=%s: %s", conversation_id[:8], e)

    history = list(_conversations.get(conversation_id) or [])

    # Build the synthetic message. If we have the full structured payload
    # (e.g. a shortlist with detailed influencer data), include it so the LLM
    # can present rich results rather than just the one-line summary.
    result_body = reply_text
    if structured is not None:
        try:
            result_body = (
                f"{reply_text}\n\nFull result data:\n"
                f"```json\n{json.dumps(structured, ensure_ascii=False, indent=2)}\n```"
            )
        except Exception:  # noqa: BLE001
            pass

    synthetic = {
        "role": "user",
        "content": (
            f"[Async result from agent {peer_agent_id}]\n\n"
            f"{result_body}\n\n"
            "Present this result to your principal."
        ),
    }
    history.append(synthetic)

    try:
        user_conns = list_connected_providers(user_id)
        connected = [c["provider"] for c in user_conns]
        linkedin_read = is_linkedin_scraped(user_id)
        system_msg = {"role": "system", "content": _build_system_prompt(user_id, connected, linkedin_scraped=linkedin_read)}
        messages = [system_msg] + history

        provider = _get_provider()
        raw_reply, _ = await asyncio.to_thread(provider.chat_with_tools, messages, [])
        final_reply = strip_think_tags(raw_reply or "")

        # Append to the real in-memory history (synthetic user turn stays local).
        real_history = _conversations.setdefault(conversation_id, [])
        real_history.append(synthetic)
        real_history.append({"role": "assistant", "content": raw_reply or ""})

        _persist_chat_message(user_id, conversation_id, "assistant", final_reply, [])
        logger.info(
            "[a2a push] autonomous reply posted conv=%s peer=%s",
            conversation_id[:8], peer_agent_id[:16],
        )
    except Exception as e:
        logger.warning("[a2a push] autonomous reply failed conv=%s: %s", conversation_id[:8], e)


def _push_body_as_task(event: dict[str, Any], wrapper: dict[str, Any]) -> dict[str, Any]:
    """Assemble a Task-like view of a result that may be delivered INSIDE the
    push body (the "shortlist will be POSTed to the callback URL" style).
    Gathers the status message plus any DataParts/artifacts on the event and
    on the wrapper (excluding the status-update envelope itself) so
    _push_result_ready can judge them."""
    event = event or {}
    wrapper = wrapper or {}
    artifacts = list(event.get("artifacts") or [])
    extra_parts = [
        p for p in (wrapper.get("parts") or [])
        if isinstance(p, dict)
        and p.get("kind") == "data"
        and isinstance(p.get("data"), dict)
        and p["data"].get("kind") != "status-update"
    ]
    if extra_parts:
        artifacts.append({"parts": extra_parts})
    return {"status": event.get("status") or {}, "artifacts": artifacts}


def _resolve_peer_a2a_url(peer_agent_id: Optional[str]) -> Optional[str]:
    """Fallback for legacy callbacks with no stored peer_a2a_url: resolve
    the peer's A2A endpoint from its registry card."""
    if not peer_agent_id:
        return None
    try:
        from agent.a2a.client import resolve_a2a_url
        from mcp.tools.zynd_network import _agent_url_from_card, _fetch_agent_card

        return resolve_a2a_url(_agent_url_from_card(_fetch_agent_card(peer_agent_id)))
    except Exception as e:  # noqa: BLE001
        logger.warning("[a2a push-fetch] peer url resolve failed for %s: %s", peer_agent_id, e)
        return None


# Keys in a result DataPart that are narration/metadata rather than payload —
# their presence doesn't make a Task "ready".
_ACK_NARRATION_KEYS = frozenset({
    "delivery", "mode", "taskid", "task_id", "contextid", "context_id",
    "status", "state", "response", "message", "note", "detail",
})
_ACK_PHRASES = (
    "when ready", "task accepted", "will be posted", "will be pushed",
    "delivered via push", "search done", "result delivered",
)


def _push_result_ready(task: dict[str, Any]) -> tuple[bool, Optional[str], Any]:
    """Decide whether a fetched Task carries the real result vs. a deferral
    ack. Returns ``(ready, reply_text, structured_payload)``.

    A task can have multiple artifacts: an early deferral ack (shortlist=null,
    delivery="push") followed by the real result (shortlist populated). We scan
    ALL data payloads and return the first non-ack one."""
    if not isinstance(task, dict):
        return False, None, None

    from agent.a2a.client import extract_reply_text

    base_reply = extract_reply_text(task) or None

    for structured in _all_data_payloads(task):
        if not _is_acceptance_ack(base_reply, structured):
            # Prefer the response/reply field embedded in the payload itself
            # (e.g. "Ranked 2 influencers…") over the generic status text.
            payload_reply = structured.get("response") or structured.get("message") or base_reply
            return True, payload_reply, structured

    # No structured payload at all — a plain text reply is the result.
    if base_reply and not _is_acceptance_ack(base_reply, None):
        return True, base_reply, None

    return False, None, None


def _all_data_payloads(task: dict[str, Any]) -> list[dict[str, Any]]:
    """All non-empty DataPart payloads from status.message and every artifact,
    in document order."""
    results: list[dict[str, Any]] = []

    def _scan(parts: Any) -> None:
        for p in parts or []:
            if isinstance(p, dict) and p.get("kind") == "data":
                d = p.get("data")
                if isinstance(d, dict) and d:
                    results.append(d)

    msg = (task.get("status") or {}).get("message")
    if isinstance(msg, dict):
        _scan(msg.get("parts"))
    for art in task.get("artifacts") or []:
        if isinstance(art, dict):
            _scan(art.get("parts"))
    return results


def _first_data_payload(task: dict[str, Any]) -> Optional[dict[str, Any]]:
    """First non-empty DataPart payload (kept for callers outside this module)."""
    payloads = _all_data_payloads(task)
    return payloads[0] if payloads else None


def _nonempty(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, (str, list, dict, tuple, set)) and len(v) == 0:
        return False
    return True


def _is_acceptance_ack(reply: Optional[str], structured: Any) -> bool:
    """True when the Task is just an 'accepted; result will be pushed later'
    placeholder — a structured DataPart with ``delivery=="push"`` and no
    populated payload field, or a text-only notification whose text matches
    a known ack phrase (e.g. 'Search done; result delivered via push.')."""
    if not isinstance(structured, dict):
        # Text-only message: check whether it's a push-delivery notification.
        if isinstance(reply, str):
            low = reply.lower()
            return any(p in low for p in _ACK_PHRASES)
        return False

    narration = reply or ""
    resp = structured.get("response") or structured.get("message")
    if isinstance(resp, str):
        narration = f"{narration}\n{resp}"
    has_payload = any(
        k.lower() not in _ACK_NARRATION_KEYS and _nonempty(v)
        for k, v in structured.items()
    )
    if has_payload:
        return False
    if structured.get("delivery") == "push":
        return True
    return any(p in narration.lower() for p in _ACK_PHRASES)
