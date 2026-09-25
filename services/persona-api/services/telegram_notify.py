"""
Telegram push notifications — outbound pings to a linked user's chat.

Use this from anywhere in the backend when you want to push a message
to the user (approval requests, inbound persona DMs, daily briefings,
…). It's a best-effort send: if the user hasn't linked Telegram, or the
bot token is unset, or Telegram returns an error, it logs and returns
False — it never raises. Callers SHOULD fire it via
`background_tasks.add_task` or `asyncio.create_task` so request paths
never block on Telegram's API.

Lives in `services/` rather than `api/` so any module can import it
without dragging in FastAPI routers (`api/telegram.py` would create a
circular import once we ping from inside the orchestrator).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

import config
from services import telegram_store

logger = logging.getLogger(__name__)


def _api_base() -> str | None:
    """Resolve TELEGRAM_BOT_TOKEN at call time so tests / hot reloads
    can change it without re-importing."""
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        return None
    return f"https://api.telegram.org/bot{token}"


async def send_raw(
    chat_id: int | str,
    text: str,
    *,
    parse_mode: str | None = "Markdown",
    disable_web_page_preview: bool = True,
) -> bool:
    """Low-level send. Returns True on success. Never raises.

    If the first attempt fails with `parse_mode` set, we retry once
    without a parse_mode — Telegram rejects messages whose Markdown is
    malformed (unbalanced underscores etc.), and we'd rather deliver
    plain text than nothing.
    """
    base = _api_base()
    if not base:
        return False

    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{base}/sendMessage", json=payload)
        if resp.status_code < 400:
            return True
        logger.warning(
            f"[telegram_notify] sendMessage HTTP {resp.status_code}: {resp.text[:200]}"
        )
        if parse_mode:
            payload.pop("parse_mode", None)
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{base}/sendMessage", json=payload)
            return resp.status_code < 400
        return False
    except Exception as e:
        logger.warning(f"[telegram_notify] sendMessage failed: {e}")
        return False


async def notify_user(
    user_id: str,
    text: str,
    *,
    parse_mode: str | None = "Markdown",
) -> bool:
    """Send `text` to the user's linked Telegram chat.

    No-op (returns False) when:
      - the user hasn't linked Telegram (no row in `telegram_links`)
      - TELEGRAM_BOT_TOKEN is unset
      - Telegram's API rejects the request

    Best-effort — never raises. Safe to call from request paths via
    `background_tasks.add_task(notify_user, ...)`.
    """
    if not user_id or not text:
        return False
    chat_id = telegram_store.get_chat_id_for_user(user_id)
    if not chat_id:
        # No linked Telegram — silent no-op.
        return False
    return await send_raw(chat_id, text, parse_mode=parse_mode)
