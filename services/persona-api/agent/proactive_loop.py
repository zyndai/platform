"""
Proactive Agent Loop — background scheduler that makes personas do things
before the user asks.

Runs per-user checks on a configurable cadence:
  1. Morning brief — calendar events + memory context
  2. Midday nudge — pending actions, stale connections, contradictions
  3. Evening recap — day summary, tomorrow prep

Each check is isolated — a crash for one user never affects others.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import config
from agent.daily_brief import generate_morning_brief, push_brief_to_user
from agent.nudge_engine import scan_nudges, push_nudge_to_user

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

# How often the main loop wakes up to check if any user needs a brief/nudge.
POLL_INTERVAL_SECONDS = 300  # 5 minutes

# How often to re-scan all active users (in seconds).
FULL_SCAN_INTERVAL_SECONDS = 3600  # 1 hour

# Track per-user last-run times so we don't spam.
_last_morning_brief: dict[str, float] = {}
_last_nudge_scan: dict[str, float] = {}
_last_evening_recap: dict[str, float] = {}


class ProactiveAgent:
    """Manages the background proactive agent loop."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the proactive agent background task."""
        if self._task is not None and not self._task.done():
            logger.info("[proactive] already running")
            return

        if not config.MEMORY_LAYER_JWT_SECRET:
            logger.info("[proactive] memory layer not configured — skipping")
            return

        self._task = asyncio.create_task(self._run_loop())
        logger.info("[proactive] started (poll=%ss, full_scan=%ss)",
                     POLL_INTERVAL_SECONDS, FULL_SCAN_INTERVAL_SECONDS)

    async def stop(self) -> None:
        """Stop the proactive agent gracefully."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[proactive] stopped")

    async def _run_loop(self) -> None:
        """Main loop — polls for users who need proactive actions."""
        last_full_scan = 0.0

        while True:
            try:
                now = datetime.now(timezone.utc).timestamp()

                # Full scan: refresh the list of active users and check all of them.
                if now - last_full_scan > FULL_SCAN_INTERVAL_SECONDS:
                    await self._full_scan()
                    last_full_scan = now
                else:
                    # Quick scan: check users whose brief/nudge windows are open.
                    await self._quick_scan()

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[proactive] loop iteration crashed — sleeping and retrying")

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _full_scan(self) -> None:
        """Scan all active users for proactive actions."""
        active_users = await _get_active_users()
        logger.info("[proactive] full scan: %d active users", len(active_users))

        for user_id, tz_hint in active_users:
            try:
                await self._check_user(user_id, tz_hint)
            except Exception:
                logger.exception("[proactive] check failed for user %s", user_id)

    async def _quick_scan(self) -> None:
        """Check users whose windows might be open (lightweight scan)."""
        # For now, just do a full scan — optimization later.
        # The full scan already throttles per-user with last-run timestamps.
        pass

    async def _check_user(self, user_id: str, time_zone: str | None) -> None:
        """Run all proactive checks for a single user."""
        now = datetime.now(timezone.utc)

        # Resolve timezone for hour-based gating.
        user_hour = _get_user_local_hour(now, time_zone)

        # ── Morning brief: 6-10 AM local time ──
        if 6 <= user_hour < 10:
            last = _last_morning_brief.get(user_id, 0)
            if now.timestamp() - last > 14400:  # 4 hours — once per morning
                await self._run_morning_brief(user_id, time_zone)
                _last_morning_brief[user_id] = now.timestamp()

        # ── Midday nudge: 11 AM - 2 PM local time ──
        if 11 <= user_hour < 14:
            last = _last_nudge_scan.get(user_id, 0)
            if now.timestamp() - last > 10800:  # 3 hours
                await self._run_nudge_scan(user_id, time_zone)
                _last_nudge_scan[user_id] = now.timestamp()

        # ── Evening recap: 6-9 PM local time ──
        if 18 <= user_hour < 21:
            last = _last_evening_recap.get(user_id, 0)
            if now.timestamp() - last > 14400:  # 4 hours
                await self._run_evening_recap(user_id, time_zone)
                _last_evening_recap[user_id] = now.timestamp()

    async def _run_morning_brief(self, user_id: str, time_zone: str | None) -> None:
        """Generate and push a morning brief for a user."""
        try:
            brief = await generate_morning_brief(user_id, time_zone)
            if brief:
                await push_brief_to_user(user_id, brief)
                logger.info("[proactive] morning brief sent to %s", user_id)
        except Exception:
            logger.exception("[proactive] morning brief failed for %s", user_id)

    async def _run_nudge_scan(self, user_id: str, time_zone: str | None) -> None:
        """Scan for nudges and push them to the user."""
        try:
            nudges = await scan_nudges(user_id)
            for nudge in nudges:
                await push_nudge_to_user(user_id, nudge)
                logger.info("[proactive] nudge sent to %s: %s", user_id, nudge.get("title", "?"))
        except Exception:
            logger.exception("[proactive] nudge scan failed for %s", user_id)

    async def _run_evening_recap(self, user_id: str, time_zone: str | None) -> None:
        """Generate and push an evening recap."""
        try:
            recap = await _generate_evening_recap(user_id, time_zone)
            if recap:
                await push_brief_to_user(user_id, recap, kind="evening")
                logger.info("[proactive] evening recap sent to %s", user_id)
        except Exception:
            logger.exception("[proactive] evening recap failed for %s", user_id)


# ── Helpers ──────────────────────────────────────────────────────────


def _get_user_local_hour(now: datetime, time_zone: str | None) -> int:
    """Get the user's local hour (0-23). Falls back to UTC."""
    if not time_zone:
        return now.hour
    try:
        from zoneinfo import ZoneInfo
        local = now.astimezone(ZoneInfo(time_zone))
        return local.hour
    except Exception:
        return now.hour


async def _get_active_users() -> list[tuple[str, str | None]]:
    """Fetch all active users with deployed personas and their timezones."""
    try:
        sb = config.get_supabase()
        rows = (
            sb.table("persona_agents")
            .select("user_id, profile")
            .eq("active", True)
            .execute()
        )
        users: list[tuple[str, str | None]] = []
        for row in (rows.data or []):
            uid = row.get("user_id")
            profile = row.get("profile") or {}
            tz = profile.get("timezone") if isinstance(profile, dict) else None
            users.append((uid, tz))
        return users
    except Exception as e:
        logger.warning("[proactive] failed to fetch active users: %s", e)
        return []


async def _generate_evening_recap(
    user_id: str, time_zone: str | None
) -> str | None:
    """Generate an evening recap — what happened today, what's up tomorrow."""
    from agent.daily_brief import generate_morning_brief

    # For now, reuse morning brief logic but label it as evening.
    # Future: add "what got done today" from chat history / todos.
    brief = await generate_morning_brief(user_id, time_zone)
    if not brief:
        return None

    evening_lines = [
        "🌙 **Evening Recap**",
        "",
        brief.replace("☀️ Morning Brief", "🌙 Evening Recap"),
    ]
    return "\n".join(evening_lines)


# ── Singleton ────────────────────────────────────────────────────────

_proactive_agent: ProactiveAgent | None = None


def get_proactive_agent() -> ProactiveAgent:
    global _proactive_agent
    if _proactive_agent is None:
        _proactive_agent = ProactiveAgent()
    return _proactive_agent
