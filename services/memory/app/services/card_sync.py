"""Best-effort card snapshot refresh after memory-side public-card mutations.

The cards-api backend holds a stored snapshot of the owner's public findability
facts (``card.zynd_memory``) that the public page / data.json / search read
without hitting the memory layer per view. When the mutation happens on the
memory side — an agent calling ``forget_fact_tool``, or the user hitting
``/me/findability/approve|revoke|declare`` or ``/me/forget`` — cards-api has no
way to know, so we ping its internal refresh endpoint. The 6-hourly cron in
cards-api stays the backstop; this just removes the multi-hour lag.

Fire-and-forget: never blocks the mutation, never raises into the caller.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return bool(settings.feature_s02_card_sync and settings.memory_service_token)


async def _resolve_email(pool, uid: str) -> str | None:
    try:
        return await pool.fetchval("SELECT email FROM users WHERE id = $1::uuid", uid)
    except Exception:  # noqa: BLE001 — best-effort
        return None


def _schedule(email: str) -> None:
    try:
        asyncio.create_task(_post(email))
    except RuntimeError:  # no running loop — cron backstop still applies
        return


async def _post(email: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                settings.cards_api_url.rstrip("/") + "/internal/refresh-card-memory",
                headers={"Authorization": "Bearer " + settings.memory_service_token},
                json={"email": email},
            )
            if resp.status_code >= 400:
                logger.warning("card refresh notify failed status=%d", resp.status_code)
    except Exception as exc:  # noqa: BLE001 — background best-effort, never raise
        logger.warning("card refresh notify failed err=%s", exc)


async def notify_cards_refresh(pool, uid: str) -> None:
    """Resolve the owner's email and schedule a cards-api snapshot refresh."""
    if not _enabled():
        return
    email = await _resolve_email(pool, uid)
    if not email:
        return
    _schedule(email)