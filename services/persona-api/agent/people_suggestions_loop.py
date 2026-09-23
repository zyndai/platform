"""
People Suggestions Loop — weekly background refresher for the People page's
"Similar people" section.

Every hour, scans active personas and runs services.people_suggestions on
anyone whose last suggestion run is missing or older than a week. Same
pattern as agent/twitter_sync_loop.py — an asyncio loop started in main.py's
lifespan. There's also a manual path (the People page's "Refresh
suggestions" button, api/people.py), which is the only way to get a refresh
sooner than the weekly cadence, subject to its own cooldown.

Per-user failures are isolated — one broken profile never blocks the scan.
Skips the scan entirely when QuickEnrich isn't configured for this
deployment, so an unconfigured dev box doesn't spend an hourly query on
nothing.
"""

from __future__ import annotations

import asyncio
import logging

import config

logger = logging.getLogger(__name__)

# How often the loop wakes up to check for users due for a refresh.
POLL_INTERVAL_SECONDS = 3600  # 1 hour

# Refresh a user only when their last suggestion run is older than this.
REFRESH_INTERVAL_SECONDS = 7 * 86400  # 7 days


class PeopleSuggestionsLoop:
    """Manages the weekly People-suggestions background refresh loop."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            logger.info("[people-suggestions] already running")
            return
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "[people-suggestions] started (poll=%ss, refresh_interval=%ss)",
            POLL_INTERVAL_SECONDS, REFRESH_INTERVAL_SECONDS,
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[people-suggestions] stopped")

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._scan()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[people-suggestions] loop iteration crashed — sleeping and retrying")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _scan(self) -> None:
        from services import people_suggestions
        from services.quickenrich import is_configured

        if not await asyncio.to_thread(is_configured):
            return

        user_ids = await _get_active_users()
        if not user_ids:
            return

        due = []
        for user_id in user_ids:
            run = await asyncio.to_thread(people_suggestions.get_run_state, user_id)
            if people_suggestions.is_due(run, interval_seconds=REFRESH_INTERVAL_SECONDS):
                due.append(user_id)

        logger.info(
            "[people-suggestions] scan: %d active personas, %d due", len(user_ids), len(due)
        )

        for user_id in due:
            try:
                result = await asyncio.to_thread(people_suggestions.run_for_user, user_id)
                logger.info("[people-suggestions] %s → %s", user_id, result.get("status"))
            except Exception:
                logger.exception("[people-suggestions] refresh failed for user %s", user_id)


async def _get_active_users() -> list[str]:
    """User IDs with an active, deployed persona."""
    try:
        sb = config.get_supabase()
        rows = await asyncio.to_thread(
            lambda: sb.table("persona_agents")
            .select("user_id")
            .eq("active", True)
            .execute()
        )
        return [r["user_id"] for r in (rows.data or []) if r.get("user_id")]
    except Exception as exc:
        logger.warning("[people-suggestions] failed to list active personas: %s", exc)
        return []


# ── Singleton ────────────────────────────────────────────────────────

_people_suggestions_loop: PeopleSuggestionsLoop | None = None


def get_people_suggestions_loop() -> PeopleSuggestionsLoop:
    global _people_suggestions_loop
    if _people_suggestions_loop is None:
        _people_suggestions_loop = PeopleSuggestionsLoop()
    return _people_suggestions_loop
