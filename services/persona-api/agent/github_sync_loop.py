"""
GitHub Sync Loop — daily background refresher for connected GitHub accounts.

Every hour, scans api_tokens for users who connected GitHub and runs
services.github_sync.sync_user for anyone whose last snapshot is older
than 24h. This is the "cron" — an asyncio loop started in main.py's
lifespan, same pattern as proactive_loop/brief_watcher. GitHub OAuth app
tokens don't expire, so a revoked/re-scoped token just returns no data
and the next scan retries.

Per-user failures are isolated — one broken token never blocks the scan.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import config

logger = logging.getLogger(__name__)

# How often the loop wakes up to check for users due for a sync.
POLL_INTERVAL_SECONDS = 3600  # 1 hour

# Sync a user only when their last snapshot is older than this.
SYNC_INTERVAL_SECONDS = 86400  # 24 hours


class GitHubSyncLoop:
    """Manages the daily GitHub background sync loop."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            logger.info("[github-sync] already running")
            return
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "[github-sync] started (poll=%ss, sync_interval=%ss)",
            POLL_INTERVAL_SECONDS, SYNC_INTERVAL_SECONDS,
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[github-sync] stopped")

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._scan()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[github-sync] loop iteration crashed — sleeping and retrying")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _scan(self) -> None:
        from services.github_sync import sync_user

        users = await _get_github_users()
        if not users:
            return

        due = [u for u in users if await _is_due(u)]
        logger.info("[github-sync] scan: %d github users, %d due", len(users), len(due))

        for user_id in due:
            try:
                result = await sync_user(user_id)
                logger.info("[github-sync] %s → %s", user_id, result.get("status"))
            except Exception:
                logger.exception("[github-sync] sync failed for user %s", user_id)


async def _get_github_users() -> list[str]:
    """User IDs that have a stored GitHub OAuth token."""
    try:
        sb = config.get_supabase()
        rows = await asyncio.to_thread(
            lambda: sb.table("api_tokens")
            .select("user_id")
            .eq("provider", "github")
            .execute()
        )
        return [r["user_id"] for r in (rows.data or []) if r.get("user_id")]
    except Exception as exc:
        logger.warning("[github-sync] failed to list github users: %s", exc)
        return []


async def _is_due(user_id: str) -> bool:
    """True when the user has no snapshot or it's older than 24h."""
    try:
        sb = config.get_supabase()
        rows = await asyncio.to_thread(
            lambda: sb.table("github_profiles")
            .select("synced_at")
            .eq("user_id", user_id)
            .execute()
        )
        if not rows.data:
            return True
        synced = (rows.data[0].get("synced_at") or "")
        try:
            synced_dt = datetime.fromisoformat(synced.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - synced_dt).total_seconds()
            return age > SYNC_INTERVAL_SECONDS
        except (ValueError, TypeError):
            return True
    except Exception as exc:
        logger.warning("[github-sync] due-check failed for %s: %s", user_id, exc)
        return False


# ── Singleton ────────────────────────────────────────────────────────

_github_sync_loop: GitHubSyncLoop | None = None


def get_github_sync_loop() -> GitHubSyncLoop:
    global _github_sync_loop
    if _github_sync_loop is None:
        _github_sync_loop = GitHubSyncLoop()
    return _github_sync_loop
