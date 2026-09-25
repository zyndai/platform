"""
Twitter Sync Loop — weekly background refresher for connected X accounts.

Every hour, scans twitter_profiles for users who saved a handle and runs
services.twitter_scraper.scrape_user for anyone whose last scrape is older
than a week. This is the "cron" — an asyncio loop started in main.py's
lifespan, same pattern as github_sync_loop/proactive_loop. There's also a
manual path (the Accounts card's "Refresh now"), which is the only way to
get a scrape sooner than the weekly cadence.

Per-user failures are isolated — one broken handle never blocks the scan.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import config

logger = logging.getLogger(__name__)

# How often the loop wakes up to check for users due for a sync.
POLL_INTERVAL_SECONDS = 3600  # 1 hour

# Sync a user only when their last scrape is older than this.
SYNC_INTERVAL_SECONDS = 7 * 86400  # 7 days


class TwitterSyncLoop:
    """Manages the weekly Twitter background sync loop."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            logger.info("[twitter-sync] already running")
            return
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "[twitter-sync] started (poll=%ss, sync_interval=%ss)",
            POLL_INTERVAL_SECONDS, SYNC_INTERVAL_SECONDS,
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[twitter-sync] stopped")

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._scan()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[twitter-sync] loop iteration crashed — sleeping and retrying")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _scan(self) -> None:
        from services.twitter_scraper import scrape_user

        handles = await _get_twitter_users()
        if not handles:
            return

        due = [
            (user_id, handle)
            for user_id, handle in handles.items()
            if await _is_due(user_id)
        ]
        logger.info("[twitter-sync] scan: %d twitter users, %d due", len(handles), len(due))

        for user_id, handle in due:
            try:
                result = await scrape_user(user_id, handle)
                logger.info("[twitter-sync] %s → %s", user_id, result.get("status"))
            except Exception:
                logger.exception("[twitter-sync] sync failed for user %s", user_id)


async def _get_twitter_users() -> dict[str, str]:
    """User IDs that have a stored X handle (from a past save/scrape)."""
    try:
        sb = config.get_supabase()
        rows = await asyncio.to_thread(
            lambda: sb.table("twitter_profiles")
            .select("user_id, handle")
            .execute()
        )
        return {
            r["user_id"]: r["handle"]
            for r in (rows.data or [])
            if r.get("user_id") and r.get("handle")
        }
    except Exception as exc:
        logger.warning("[twitter-sync] failed to list twitter users: %s", exc)
        return {}


async def _is_due(user_id: str) -> bool:
    """True when the user has no scrape yet or it's older than a week."""
    try:
        sb = config.get_supabase()
        rows = await asyncio.to_thread(
            lambda: sb.table("twitter_profiles")
            .select("scraped_at")
            .eq("user_id", user_id)
            .execute()
        )
        if not rows.data:
            return True
        scraped = (rows.data[0].get("scraped_at") or "")
        try:
            scraped_dt = datetime.fromisoformat(scraped.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - scraped_dt).total_seconds()
            return age > SYNC_INTERVAL_SECONDS
        except (ValueError, TypeError):
            return True
    except Exception as exc:
        logger.warning("[twitter-sync] due-check failed for %s: %s", user_id, exc)
        return False


# ── Singleton ────────────────────────────────────────────────────────

_twitter_sync_loop: TwitterSyncLoop | None = None


def get_twitter_sync_loop() -> TwitterSyncLoop:
    global _twitter_sync_loop
    if _twitter_sync_loop is None:
        _twitter_sync_loop = TwitterSyncLoop()
    return _twitter_sync_loop
