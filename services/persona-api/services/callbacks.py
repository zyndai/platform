"""
Outbound A2A callback persistence + dispatch.

When an agent sends a push-mode A2A message, we register an
``outbound_callbacks`` row holding the bearer token the peer must echo
on their eventual push. When the peer pushes back hours (or days)
later, the inbound push handler ([a2a_router.a2a_push_inbound]) looks
up the row by bearer token, writes a ``callback_results`` row, and the
frontend's Supabase realtime subscription picks it up live.

This module is the single source of truth for callback row lifecycle:

    register      — create the pending row, mint the bearer token
    mark_peer_task — link the peer's Task.id once we know it
    lookup_by_token — phase-4 push handler uses this to verify
    record_result — write a callback_results row, flip status
    expire_old    — GC sweeper (run from heartbeat tick or cron)

The module wires itself into ``agent.a2a.transport`` at import time so
the dispatcher's PUSH branch finds a registrar and stops downgrading
to SEND. Importers don't need to call ``configure_callback_registrar``
themselves — just import this module once during startup.
"""
from __future__ import annotations

import base64
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import config
from agent.a2a.transport import (
    CallbackRegistrar,
    configure_callback_registrar,
)

logger = logging.getLogger(__name__)


_TABLE_OUTBOUND = "outbound_callbacks"
_TABLE_RESULTS = "callback_results"


def _supabase():
    return config.get_supabase()


def _mint_token() -> str:
    """``cb_<base64url(16-bytes)>`` — greppable in logs, 128 bits of entropy."""
    raw = secrets.token_bytes(16)
    b64 = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return f"cb_{b64}"


def _push_url_for(user_id: str) -> str:
    """The endpoint a peer should POST to for this persona. Must match
    the route mounted in agent.a2a_router.a2a_push_inbound, which is
    declared as ``@router.post("/push/{user_id}")`` and included with
    ``prefix="/api/persona"`` — so the live path is
    ``/api/persona/push/{user_id}``, not ``/api/persona/{user_id}/a2a/push``.
    The previous shape generated 404s on every inbound push and orphaned
    outbound_callbacks rows in 'pending' until they expired."""
    base = (config.ZYND_WEBHOOK_BASE_URL or "").rstrip("/")
    return f"{base}/api/persona/push/{user_id}"


# ── Public API ───────────────────────────────────────────────────────


def mint_credentials(user_id: str) -> tuple[str, str]:
    """Generate push credentials (push_url, push_token) without touching
    the database. The caller passes these into the outgoing message so the
    peer knows where to push back, then calls ``register_with_task`` once
    the peer has acked and returned a Task ID."""
    return _push_url_for(user_id), _mint_token()


async def register_with_task(
    *,
    user_id: str,
    thread_id: str,
    peer_agent_id: str,
    our_message_id: str,
    origin_kind: str,
    origin_ref: dict[str, Any],
    push_token: str,
    peer_a2a_url: Optional[str] = None,
    peer_task_id: Optional[str] = None,
) -> str:
    """Insert the outbound_callbacks row after the peer has acked.

    Because credentials were already minted with ``mint_credentials``,
    the row is written with ``peer_task_id`` populated in a single
    INSERT — the frontend realtime subscription sees one INSERT event
    with the task ID already present instead of an INSERT-then-UPDATE.
    Returns the new ``callback_id``.
    """
    row = {
        "user_id": user_id,
        "thread_id": thread_id,
        "peer_agent_id": peer_agent_id,
        "peer_a2a_url": peer_a2a_url,
        "our_message_id": our_message_id,
        "origin_kind": origin_kind,
        "origin_ref": origin_ref or {},
        "push_token": push_token,
        "status": "pending",
    }
    if peer_task_id:
        row["peer_task_id"] = peer_task_id
    sb = _supabase()
    res = sb.table(_TABLE_OUTBOUND).insert(row).execute()
    if not res.data:
        raise RuntimeError("services.callbacks.register_with_task: insert returned no rows")
    return res.data[0]["id"]


async def register(
    *,
    user_id: str,
    thread_id: str,
    peer_agent_id: str,
    our_message_id: str,
    origin_kind: str,
    origin_ref: dict[str, Any],
    peer_a2a_url: Optional[str] = None,
) -> tuple[str, str, str]:
    """Legacy: create a pending row before the send, returns
    ``(callback_id, push_url, push_token)``. Kept for callers that
    can't use the two-phase mint_credentials/register_with_task flow."""
    push_url, token = mint_credentials(user_id)
    callback_id = await register_with_task(
        user_id=user_id,
        thread_id=thread_id,
        peer_agent_id=peer_agent_id,
        our_message_id=our_message_id,
        origin_kind=origin_kind,
        origin_ref=origin_ref,
        push_token=token,
        peer_a2a_url=peer_a2a_url,
        peer_task_id=None,
    )
    return callback_id, push_url, token


async def mark_peer_task(callback_id: str, peer_task_id: str) -> None:
    """Link the peer's Task.id onto a row that was inserted without one."""
    sb = _supabase()
    sb.table(_TABLE_OUTBOUND).update({"peer_task_id": peer_task_id}).eq(
        "id", callback_id
    ).execute()


def lookup_by_token(push_token: str) -> Optional[dict[str, Any]]:
    """Phase 4's push handler calls this to verify an incoming push.
    Returns the callback row (dict) or None if no match.

    Synchronous — we want this in the request hot path with minimal
    overhead, and the supabase client is sync anyway.
    """
    sb = _supabase()
    res = (
        sb.table(_TABLE_OUTBOUND)
        .select("*")
        .eq("push_token", push_token)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]
    return None


def record_dispatch_ack(callback_id: str, task: dict[str, Any]) -> None:
    """Store the agent's immediate send-ack on the call row: the Task id it
    assigned plus its acceptance payload. The Agent Calls card is created
    from this (it only shows once peer_task_id is set), so the card reflects
    the response we actually got back, not the bare pre-send row."""
    if not callback_id or not isinstance(task, dict):
        return
    state = ((task.get("status") or {}).get("state")) or "submitted"
    sb = _supabase()
    try:
        sb.table(_TABLE_OUTBOUND).update({
            "peer_task_id": task.get("id"),
            "last_state": state,
            "last_event": {
                "kind": "acceptance",
                "taskId": task.get("id"),
                "status": task.get("status"),
                "artifacts": task.get("artifacts"),
            },
            "last_event_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", callback_id).execute()
    except Exception as e:  # noqa: BLE001
        logger.warning("services.callbacks.record_dispatch_ack failed cb=%s: %s", callback_id, e)


def record_push_event(callback_id: str, state: str, event: dict[str, Any]) -> None:
    """Stash the latest raw push from the peer on the outbound_callbacks row
    so the Agent Calls panel can show "last response from the agent" even
    before (or without) a final answer. Best-effort — failures just mean the
    panel shows slightly staler state."""
    if not callback_id:
        return
    sb = _supabase()
    try:
        sb.table(_TABLE_OUTBOUND).update({
            "last_state": state,
            "last_event": event,
            "last_event_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", callback_id).execute()
    except Exception as e:  # noqa: BLE001
        logger.warning("services.callbacks.record_push_event failed cb=%s: %s", callback_id, e)


def list_pending(max_age_hours: int = 48, limit: int = 100) -> list[dict[str, Any]]:
    """Pending outbound callbacks recent enough to still be worth polling.
    The fallback poller uses this to pull results the peer never pushed.
    Old rows age out of the window (and the GC sweeper flips them to
    'expired'), so polling stays bounded."""
    sb = _supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    res = (
        sb.table(_TABLE_OUTBOUND)
        .select("*")
        .eq("status", "pending")
        .gte("created_at", cutoff)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def lookup_pending_for_peer(user_id: str, peer_agent_id: str) -> Optional[dict[str, Any]]:
    """Third-tier fallback: peer didn't send our bearer token and the push
    arrived before mark_peer_task ran. Match the most recent pending row for
    this peer+user combination."""
    if not user_id or not peer_agent_id:
        return None
    sb = _supabase()
    res = (
        sb.table(_TABLE_OUTBOUND)
        .select("*")
        .eq("user_id", user_id)
        .eq("peer_agent_id", peer_agent_id)
        .eq("status", "pending")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def mark_peer_task_sync(callback_id: str, peer_task_id: str) -> None:
    """Sync variant of mark_peer_task for use in sync call sites
    (the push inbound handler runs async but calls this in a non-async
    fallback path)."""
    sb = _supabase()
    sb.table(_TABLE_OUTBOUND).update({"peer_task_id": peer_task_id}).eq(
        "id", callback_id
    ).execute()


def lookup_by_peer_task(peer_task_id: str) -> Optional[dict[str, Any]]:
    """Fallback correlation for the inbound push handler when the bearer
    token is missing or unknown: match the peer's Task.id we linked at
    dispatch (``mark_peer_task``). Returns the most recently created row."""
    if not peer_task_id:
        return None
    sb = _supabase()
    res = (
        sb.table(_TABLE_OUTBOUND)
        .select("*")
        .eq("peer_task_id", peer_task_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]
    return None


def record_result(
    *,
    callback: dict[str, Any],
    task_state: str,
    reply_text: Optional[str],
    raw_event: dict[str, Any],
) -> str:
    """Write a callback_results row and flip the parent
    outbound_callbacks status if the state is terminal.

    ``callback`` is the row returned by ``lookup_by_token``. We pass the
    whole row in (not just an id) because the caller already has it and
    we'd rather avoid a re-read.

    Returns the new ``callback_results.id`` (or the existing one if this
    callback was already recorded).
    """
    sb = _supabase()

    # Idempotency: one recorded result per callback. The push handler, the
    # fallback poller, and the inline path can all race to record the same
    # answer — first writer wins, the rest no-op.
    existing = (
        sb.table(_TABLE_RESULTS)
        .select("id")
        .eq("callback_id", callback["id"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"]

    res_row = {
        "callback_id": callback["id"],
        "user_id": callback["user_id"],
        "thread_id": callback["thread_id"],
        "peer_agent_id": callback["peer_agent_id"],
        "task_state": task_state,
        "reply_text": reply_text,
        "raw_event": raw_event,
    }
    res = sb.table(_TABLE_RESULTS).insert(res_row).execute()
    if not res.data:
        raise RuntimeError("services.callbacks.record_result: insert returned no rows")
    result_id = res.data[0]["id"]

    # Terminal states close the parent callback. Non-terminal updates
    # (input-required, auth-required) leave it pending so the next push
    # — when the peer's user finally types something — can land too.
    if task_state in ("completed", "canceled", "failed", "rejected"):
        sb.table(_TABLE_OUTBOUND).update(
            {"status": "received", "answer_text": reply_text}
        ).eq("id", callback["id"]).execute()

    return result_id


def expire_old() -> int:
    """GC sweeper — flips pending rows past expires_at to 'expired'.
    Returns the number of rows updated."""
    sb = _supabase()
    res = (
        sb.table(_TABLE_OUTBOUND)
        .update({"status": "expired"})
        .eq("status", "pending")
        .lt("expires_at", "now()")
        .execute()
    )
    return len(res.data or [])


# ── Wire into the dispatcher ─────────────────────────────────────────


class _ServiceRegistrar:
    """Adapter satisfying the :class:`CallbackRegistrar` Protocol."""

    def mint_credentials(self, user_id: str) -> tuple[str, str]:
        return mint_credentials(user_id)

    async def register_with_task(
        self,
        *,
        user_id: str,
        thread_id: str,
        peer_agent_id: str,
        our_message_id: str,
        origin_kind: str,
        origin_ref: dict[str, Any],
        push_token: str,
        peer_a2a_url: Optional[str] = None,
        peer_task_id: Optional[str] = None,
    ) -> str:
        return await register_with_task(
            user_id=user_id,
            thread_id=thread_id,
            peer_agent_id=peer_agent_id,
            our_message_id=our_message_id,
            origin_kind=origin_kind,
            origin_ref=origin_ref,
            push_token=push_token,
            peer_a2a_url=peer_a2a_url,
            peer_task_id=peer_task_id,
        )

    async def register(
        self,
        *,
        user_id: str,
        thread_id: str,
        peer_agent_id: str,
        our_message_id: str,
        origin_kind: str,
        origin_ref: dict[str, Any],
        peer_a2a_url: Optional[str] = None,
    ) -> tuple[str, str, str]:
        return await register(
            user_id=user_id,
            thread_id=thread_id,
            peer_agent_id=peer_agent_id,
            our_message_id=our_message_id,
            origin_kind=origin_kind,
            origin_ref=origin_ref,
            peer_a2a_url=peer_a2a_url,
        )

    async def mark_peer_task(self, callback_id: str, peer_task_id: str) -> None:
        await mark_peer_task(callback_id, peer_task_id)

    async def record_inline_result(
        self,
        callback_id: str,
        *,
        task: dict[str, Any],
        reply_text: Optional[str],
    ) -> None:
        """Synthesize a callback_results row for a peer that answered
        inline. Looks up the parent row, then writes the result + flips
        status — same shape Phase 4's push handler produces, so the
        frontend's realtime subscription doesn't have to special-case
        the inline path."""
        sb = _supabase()
        cb = (
            sb.table(_TABLE_OUTBOUND)
            .select("*")
            .eq("id", callback_id)
            .limit(1)
            .execute()
        )
        if not cb.data:
            logger.warning(
                "services.callbacks.record_inline_result: callback_id=%s not found",
                callback_id,
            )
            return
        task_state = ((task.get("status") or {}).get("state")) or "completed"
        record_result(
            callback=cb.data[0],
            task_state=task_state,
            reply_text=reply_text,
            raw_event={
                "kind": "status-update",
                "taskId": task.get("id"),
                "status": task.get("status") or {},
                "final": True,
                "synthesized_inline": True,
            },
        )


# Self-register on import. Importing this module is the entire wiring
# step — call it once during startup (we import it from main.py).
_registrar_instance: CallbackRegistrar = _ServiceRegistrar()
configure_callback_registrar(_registrar_instance)
