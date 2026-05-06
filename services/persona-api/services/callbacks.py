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
    """Lazy supabase client. Service-role for RLS bypass."""
    from supabase import create_client

    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def _mint_token() -> str:
    """``cb_<base64url(16-bytes)>`` — greppable in logs, 128 bits of entropy."""
    raw = secrets.token_bytes(16)
    b64 = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return f"cb_{b64}"


def _push_url_for(user_id: str) -> str:
    """The endpoint a peer should POST to for this persona. Matches the
    route mounted in agent.a2a_router.a2a_push_inbound."""
    base = (config.ZYND_WEBHOOK_BASE_URL or "").rstrip("/")
    return f"{base}/api/persona/{user_id}/a2a/push"


# ── Public API ───────────────────────────────────────────────────────


async def register(
    *,
    user_id: str,
    thread_id: str,
    peer_agent_id: str,
    our_message_id: str,
    origin_kind: str,
    origin_ref: dict[str, Any],
) -> tuple[str, str, str]:
    """Create a pending callback row. Returns
    ``(callback_id, push_url, push_token)``. The dispatcher passes
    push_url + push_token into the peer's ``pushNotificationConfig``;
    the peer echoes the token in ``Authorization: Bearer …`` on the
    push back.

    The supabase client is sync; we run inserts on the event loop
    directly because the per-call cost is small and the dispatcher
    is already doing async work around us. Switch to ``run_in_executor``
    if profiling shows blocking.
    """
    token = _mint_token()
    row = {
        "user_id": user_id,
        "thread_id": thread_id,
        "peer_agent_id": peer_agent_id,
        "our_message_id": our_message_id,
        "origin_kind": origin_kind,
        "origin_ref": origin_ref or {},
        "push_token": token,
        "status": "pending",
    }
    sb = _supabase()
    res = sb.table(_TABLE_OUTBOUND).insert(row).execute()
    if not res.data:
        raise RuntimeError("services.callbacks.register: insert returned no rows")
    callback_id = res.data[0]["id"]
    return callback_id, _push_url_for(user_id), token


async def mark_peer_task(callback_id: str, peer_task_id: str) -> None:
    """Once the receiver has acked our message/send, link their Task.id
    onto our row. Used as a secondary correlation key alongside the
    bearer token."""
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

    Returns the new ``callback_results.id``.
    """
    sb = _supabase()

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
        sb.table(_TABLE_OUTBOUND).update({"status": "received"}).eq(
            "id", callback["id"]
        ).execute()

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
    """Adapter satisfying the :class:`CallbackRegistrar` Protocol with
    module-level functions. The dispatcher only invokes
    ``register`` and ``mark_peer_task``."""

    async def register(
        self,
        *,
        user_id: str,
        thread_id: str,
        peer_agent_id: str,
        our_message_id: str,
        origin_kind: str,
        origin_ref: dict[str, Any],
    ) -> tuple[str, str, str]:
        return await register(
            user_id=user_id,
            thread_id=thread_id,
            peer_agent_id=peer_agent_id,
            our_message_id=our_message_id,
            origin_kind=origin_kind,
            origin_ref=origin_ref,
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
