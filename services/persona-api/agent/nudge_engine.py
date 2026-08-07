"""
Nudge Engine — detects things that need the user's attention and
surfaces them as actionable notifications.

Scans:
  1. Memory-layer: contradictory assertions, decaying facts, unreinforced facts
  2. Supabase: pending approvals, stale connections, overdue todos
  3. Zynd network: inactive connections, unread agent messages
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import config
from agent.memory_client import get_context, is_enabled

logger = logging.getLogger(__name__)


async def scan_nudges(user_id: str) -> list[dict]:
    """Scan all sources for nudges that need the user's attention.

    Returns a list of nudge dicts with:
      - title: Short headline
      - body: Longer explanation
      - priority: "high" | "medium" | "low"
      - action: Optional suggested action string
    """
    nudges: list[dict] = []

    # Run all checks in parallel.
    import asyncio

    checks = await asyncio.gather(
        _check_memory_decay(user_id),
        _check_memory_contradictions(user_id),
        _check_pending_approvals(user_id),
        _check_overdue_todos(user_id),
        _check_stale_connections(user_id),
        return_exceptions=True,
    )

    for result in checks:
        if isinstance(result, list):
            nudges.extend(result)
        elif isinstance(result, Exception):
            logger.debug("[nudge] check failed: %s", result)

    # Sort by priority: high → medium → low.
    priority_order = {"high": 0, "medium": 1, "low": 2}
    nudges.sort(key=lambda n: priority_order.get(n.get("priority", "low"), 99))

    return nudges


async def push_nudge_to_user(user_id: str, nudge: dict) -> bool:
    """Push a single nudge to the user via Telegram or DB."""
    title = nudge.get("title", "Nudge")
    body = nudge.get("body", "")
    priority = nudge.get("priority", "low")

    emoji = {"high": "🔴", "medium": "🟡", "low": "🔵"}.get(priority, "💭")
    message = f"{emoji} **{title}**\n{body}"

    from agent.daily_brief import push_brief_to_user
    return await push_brief_to_user(user_id, message, kind="nudge")


# ── Nudge checks ─────────────────────────────────────────────────────


async def _check_memory_decay(user_id: str) -> list[dict]:
    """Check for facts that are decaying — confidence fading below threshold."""
    if not is_enabled():
        return []

    try:
        # Query for facts that might be decaying — use a broad topic to catch all.
        ctx = await get_context(
            user_id=user_id,
            topic="recent activities goals preferences",
            k=30,
            min_confidence=0.35,  # Lower threshold to catch fading facts
        )

        nudges = []
        for a in ctx.assertions:
            # Facts with confidence between 0.35 and 0.55 are fading.
            if 0.35 <= a.confidence <= 0.55:
                nudges.append({
                    "title": f"Fading memory: {a.predicate}",
                    "body": (
                        f"I'm less sure about this than I used to be: "
                        f"*{a.statement[:120]}*\n"
                        f"Confidence: {a.confidence:.0%} — I'll keep it "
                        f"unless you tell me it's changed."
                    ),
                    "priority": "low",
                })

        return nudges[:3]  # Cap at 3 decay nudges
    except Exception:
        return []


async def _check_memory_contradictions(user_id: str) -> list[dict]:
    """Check for contradictory assertions in memory."""
    if not is_enabled():
        return []

    try:
        # Query broad context and look for pairs that contradict.
        # This is a heuristic approach — a full contradiction engine would
        # use the LLM to compare pairs, but that's expensive per-user.
        ctx = await get_context(
            user_id=user_id,
            topic="work role location preferences",
            k=20,
            min_confidence=0.5,
        )

        # Group by predicate — if multiple values for same predicate,
        # they might contradict (e.g., "works at Foo" and "works at Bar").
        by_predicate: dict[str, list] = {}
        for a in ctx.assertions:
            by_predicate.setdefault(a.predicate, []).append(a)

        nudges = []
        for predicate, assertions in by_predicate.items():
            if len(assertions) >= 2:
                values = [a.object or a.statement for a in assertions]
                unique = list(set(values))
                if len(unique) >= 2:
                    nudges.append({
                        "title": f"Conflicting info: {predicate}",
                        "body": (
                            f"I have multiple values for your {predicate}:\n"
                            + "\n".join(f"- {v[:80]}" for v in unique[:3])
                            + "\n\nWhich is correct?"
                        ),
                        "priority": "medium",
                    })

        return nudges[:2]  # Cap at 2 contradiction nudges
    except Exception:
        return []


async def _check_pending_approvals(user_id: str) -> list[dict]:
    """Check for pending actions that need the user's approval."""
    nudges = []

    try:
        sb = config.get_supabase()

        # Pending approval items.
        approvals = (
            sb.table("pending_approvals")
            .select("id, tool_name, created_at")
            .eq("user_id", user_id)
            .eq("status", "pending")
            .limit(5)
            .execute()
        )
        if approvals.data:
            count = len(approvals.data)
            nudges.append({
                "title": f"{count} pending approval{'s' if count > 1 else ''}",
                "body": (
                    f"You have {count} action{'s' if count > 1 else ''} waiting for your approval. "
                    "Open the app to review — they won't execute until you approve."
                ),
                "priority": "high",
            })

    except Exception as e:
        logger.debug("[nudge] approvals check failed: %s", e)

    return nudges


async def _check_overdue_todos(user_id: str) -> list[dict]:
    """Check for todos that might be overdue."""
    nudges = []

    try:
        sb = config.get_supabase()

        # Check for todos created more than 2 days ago that aren't done.
        rows = (
            sb.table("brief_todos")
            .select("title, created_at")
            .eq("user_id", user_id)
            .eq("done", False)
            .order("created_at", desc=False)
            .execute()
        )
        if rows.data:
            now = datetime.now(timezone.utc)
            overdue = []
            for row in rows.data:
                created = row.get("created_at")
                if created:
                    try:
                        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        age_hours = (now - created_dt).total_seconds() / 3600
                        if age_hours > 48:  # 2 days
                            overdue.append(row.get("title", "Untitled todo"))
                    except Exception:
                        pass

            if overdue:
                nudges.append({
                    "title": f"{len(overdue)} overdue todo{'s' if len(overdue) > 1 else ''}",
                    "body": (
                        "You have items that have been on your list for over 2 days:\n"
                        + "\n".join(f"- {t[:80]}" for t in overdue[:5])
                    ),
                    "priority": "medium",
                })

    except Exception:
        pass

    return nudges


async def _check_stale_connections(user_id: str) -> list[dict]:
    """Check for Zynd network connections that have gone stale."""
    nudges = []

    try:
        sb = config.get_supabase()

        # Check for pending connection requests that haven't been acted on.
        pending = (
            sb.table("dm_threads")
            .select("initiator_id, created_at")
            .eq("participant_id", user_id)
            .eq("status", "pending")
            .execute()
        )
        if pending.data:
            now = datetime.now(timezone.utc)
            stale = []
            for row in pending.data:
                created = row.get("created_at")
                if created:
                    try:
                        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        age_hours = (now - created_dt).total_seconds() / 3600
                        if age_hours > 48:  # 2 days
                            stale.append(row)
                    except Exception:
                        pass

            if stale:
                nudges.append({
                    "title": f"{len(stale)} stale connection request{'s' if len(stale) > 1 else ''}",
                    "body": (
                        f"You have {len(stale)} connection request{'s' if len(stale) > 1 else ''} "
                        "that have been waiting over 2 days. Accept or decline to keep your network clean."
                    ),
                    "priority": "low",
                })

    except Exception:
        pass

    return nudges
