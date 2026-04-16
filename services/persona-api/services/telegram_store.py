"""
Telegram persistence — handshake links and per-chat conversation history.

Replaces the disk-backed `telegram_users.json` file and the in-memory
`_conversations` dict for Telegram traffic with proper Supabase-backed
storage. Two tables:

  telegram_links           — chat_id ↔ user_id map (PK on user_id,
                             unique on chat_id). Survives restarts.
  telegram_chat_history    — one row per conversation_id carrying the
                             full message list as a JSONB blob. Updated
                             in-place on every turn.

History format is the same list-of-dicts the orchestrator already uses
internally (role, content, optional tool_calls, optional tool_call_id,
etc.), so we can hydrate `_conversations[conv_id]` before a call and
persist it back after without any format translation.

We deliberately store the ENTIRE message list in one JSONB blob instead
of one-row-per-turn. Reasons:
  - Tool-role intermediate messages and assistant messages with
    embedded `tool_calls` dicts are awkward to flatten into columns.
  - v1 doesn't need per-message queryability. Summarization / windowing
    comes later.
  - One upsert per turn is simpler than batch inserts.
"""

from __future__ import annotations

import logging
from typing import Any

import config

logger = logging.getLogger(__name__)


def _sb():
    from supabase import create_client
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


# ── Handshake link map ────────────────────────────────────────────────

def get_user_id_for_chat(chat_id: str | int) -> str | None:
    """Look up the Supabase user linked to a Telegram chat_id. Returns None if unlinked."""
    try:
        r = (
            _sb()
            .table("telegram_links")
            .select("user_id")
            .eq("chat_id", str(chat_id))
            .limit(1)
            .execute()
        )
        if r.data:
            return r.data[0]["user_id"]
    except Exception as e:
        logger.warning(f"[telegram_store] get_user_id_for_chat failed: {e}")
    return None


def link_chat_to_user(chat_id: str | int, user_id: str) -> None:
    """
    Upsert the (user_id, chat_id) link. Idempotent — relinking is fine.
    If the same user previously linked a different chat_id, the old row
    is replaced by primary-key conflict on user_id; if the same chat_id
    was previously linked to a different user, that older row is removed
    first so the unique constraint on chat_id doesn't block the insert.
    """
    sb = _sb()
    chat_id_s = str(chat_id)

    # Remove any stale row that would collide on the unique chat_id
    try:
        sb.table("telegram_links").delete().eq("chat_id", chat_id_s).execute()
    except Exception as e:
        logger.warning(f"[telegram_store] clear stale chat_id row failed: {e}")

    try:
        sb.table("telegram_links").upsert({
            "user_id": user_id,
            "chat_id": chat_id_s,
        }).execute()
        logger.info(f"[telegram_store] linked chat_id={chat_id_s} to user_id={user_id}")
    except Exception as e:
        logger.error(f"[telegram_store] link_chat_to_user failed: {e}")


def unlink_chat(chat_id: str | int) -> None:
    """Remove a Telegram link (used on account delete)."""
    try:
        _sb().table("telegram_links").delete().eq("chat_id", str(chat_id)).execute()
    except Exception as e:
        logger.warning(f"[telegram_store] unlink_chat failed: {e}")


# ── Conversation history ──────────────────────────────────────────────

def load_history(conversation_id: str) -> list[dict[str, Any]]:
    """
    Load the persisted message list for a conversation. Returns [] if
    the conversation doesn't exist yet (new chat).
    """
    try:
        r = (
            _sb()
            .table("telegram_chat_history")
            .select("messages")
            .eq("conversation_id", conversation_id)
            .limit(1)
            .execute()
        )
        if r.data and isinstance(r.data[0].get("messages"), list):
            return r.data[0]["messages"]
    except Exception as e:
        logger.warning(f"[telegram_store] load_history failed: {e}")
    return []


def save_history(user_id: str, conversation_id: str, messages: list[dict[str, Any]]) -> None:
    """
    Upsert the full message list for a conversation. Called after the
    orchestrator returns, so the next turn picks up where we left off.
    """
    try:
        _sb().table("telegram_chat_history").upsert(
            {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "messages": messages,
            },
            on_conflict="conversation_id",
        ).execute()
    except Exception as e:
        logger.error(f"[telegram_store] save_history failed: {e}")


def clear_history(conversation_id: str) -> None:
    """Wipe the history for a specific conversation (useful for /reset)."""
    try:
        _sb().table("telegram_chat_history").delete().eq(
            "conversation_id", conversation_id
        ).execute()
    except Exception as e:
        logger.warning(f"[telegram_store] clear_history failed: {e}")
