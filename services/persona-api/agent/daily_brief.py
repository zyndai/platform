"""
Daily Brief Generator — builds a morning brief for a user by combining
calendar events with memory-layer context.

Flow:
  1. Fetch today's calendar events via Google Calendar
  2. For each event, query memory-layer for related context
  3. Cross-reference participants with Zynd network profiles
  4. Format a readable summary
  5. Push via Telegram or store as a pending notification
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import config
from agent.memory_client import get_context, is_enabled
from agent.memory_context import format_context_as_list

logger = logging.getLogger(__name__)


async def generate_morning_brief(
    user_id: str,
    time_zone: str | None = None,
) -> str | None:
    """Generate a morning brief for a user.

    Returns a Markdown string ready for display, or None if there's
    nothing interesting to report.
    """
    lines: list[str] = []
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%A, %B %d")

    lines.append(f"☀️ **Morning Brief — {today_str}**")
    lines.append("")

    # ── Calendar section ─────────────────────────────────────────
    events = await _fetch_today_events(user_id, time_zone)
    if events:
        lines.append("### 📅 Today's Calendar")
        for ev in events[:8]:  # cap at 8 events
            start = ev.get("start", "?")
            title = ev.get("title", "Untitled")
            participants = ev.get("participants", [])

            lines.append(f"- **{start}** — {title}")

            # For each participant, try to pull memory context.
            for name in participants[:5]:  # cap per event
                ctx = await _lookup_person_context(user_id, name)
                if ctx:
                    lines.append(f"  - *{name}*: {ctx}")

            lines.append("")
    else:
        lines.append("### 📅 Calendar")
        lines.append("No events scheduled today.")
        lines.append("")

    # ── Memory context section ───────────────────────────────────
    memory = await _get_memory_snapshot(user_id)
    if memory:
        lines.append("### 🧠 What I Remember")
        lines.append(memory)
        lines.append("")

    # ── Pending actions section ──────────────────────────────────
    pending = await _get_pending_actions(user_id)
    if pending:
        lines.append("### ⏳ Needs Attention")
        for item in pending:
            lines.append(f"- {item}")
        lines.append("")

    # ── Todo section ─────────────────────────────────────────────
    todos = await _get_todos(user_id)
    if todos:
        lines.append("### ✅ Your Todos")
        for todo in todos[:5]:
            title = todo.get("title", "Untitled")
            done = "✓" if todo.get("done") else "○"
            lines.append(f"- {done} {title}")
        lines.append("")

    if len(lines) <= 3:
        return None  # Nothing interesting

    return "\n".join(lines)


async def push_brief_to_user(
    user_id: str,
    brief: str,
    kind: str = "morning",
) -> bool:
    """Push a brief to the user via their preferred channel.

    Currently supports Telegram. Falls back to storing as a chat message
    if no push channel is configured.

    Returns True if push was delivered.
    """
    # Try Telegram first.
    telegram_id = await _get_telegram_chat_id(user_id)
    if telegram_id:
        try:
            await _send_telegram_message(telegram_id, brief)
            return True
        except Exception as e:
            logger.warning("[brief] telegram push failed for %s: %s", user_id, e)

    # Fallback: store as a system message in chat_messages so it
    # appears when the user opens the app.
    try:
        import uuid
        sb = config.get_supabase()
        sb.table("chat_messages").insert({
            "user_id": user_id,
            "conversation_id": str(uuid.uuid4()),
            "role": "system",
            "content": brief,
        }).execute()
        return True
    except Exception as e:
        logger.warning("[brief] db fallback failed for %s: %s", user_id, e)

    return False


# ── Internal helpers ──────────────────────────────────────────────────


async def _fetch_today_events(
    user_id: str, time_zone: str | None
) -> list[dict]:
    """Fetch today's calendar events for a user via Google Calendar."""
    try:
        from mcp.tools.google.calendar import list_events
        result = list_events(user_id=user_id, max_results=15)
        if not result.get("success"):
            return []

        events = result.get("events", [])
        today_events = []
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for ev in events:
            start_raw = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", "")
            if not start_raw:
                continue

            # Parse start time to local TZ
            try:
                start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                if time_zone:
                    from zoneinfo import ZoneInfo
                    local = start_dt.astimezone(ZoneInfo(time_zone))
                else:
                    local = start_dt
            except Exception:
                continue

            # Only today's events
            if local.strftime("%Y-%m-%d") != today_str:
                continue

            attendees = ev.get("attendees", [])
            participants = [
                a.get("displayName") or a.get("email", "Unknown")
                for a in (attendees or [])
            ]

            today_events.append({
                "title": ev.get("summary", "Untitled"),
                "start": local.strftime("%I:%M %p").lstrip("0"),
                "participants": participants,
                "location": ev.get("location", ""),
                "description": (ev.get("description") or "")[:200],
            })

        return today_events
    except Exception as e:
        logger.debug("[brief] calendar fetch failed for %s: %s", user_id, e)
        return []


async def _lookup_person_context(user_id: str, name: str) -> str | None:
    """Search memory-layer for context about a person."""
    if not is_enabled():
        return None

    try:
        # min_confidence=0.5 matches what we actually keep below — no point
        # fetching 0.4-0.5 assertions from the server just to discard them.
        ctx = await get_context(user_id=user_id, topic=name, k=3, min_confidence=0.5)
        if not ctx.assertions:
            return None
        return ctx.assertions[0].statement[:120]
    except Exception:
        pass
    return None


async def _get_memory_snapshot(user_id: str) -> str | None:
    """Get a snapshot of what the memory layer knows about the user."""
    if not is_enabled():
        return None

    try:
        ctx = await get_context(
            user_id=user_id,
            topic="current projects goals priorities interests",
            k=10,
            min_confidence=0.5,
        )
        if not ctx.assertions:
            return None

        # Reuse the shared list formatter rather than hand-rolling another
        # one; drop its own "## What I remember about you" header since
        # generate_morning_brief already prints its own section header.
        formatted = format_context_as_list(ctx)
        lines = [ln[:120] for ln in formatted.splitlines() if ln.startswith("-")]
        return "\n".join(lines[:6]) if lines else None
    except Exception:
        return None


async def _get_pending_actions(user_id: str) -> list[str]:
    """Get pending actions that need attention."""
    actions: list[str] = []

    try:
        sb = config.get_supabase()

        # Pending connection requests.
        conns = (
            sb.table("dm_threads")
            .select("initiator_id")
            .eq("participant_id", user_id)
            .eq("status", "pending")
            .execute()
        )
        if conns.data:
            for c in conns.data:
                initiator = c.get("initiator_id", "Someone")
                # Try to resolve to a persona name.
                try:
                    p = sb.table("persona_agents").select("name").eq("user_id", initiator).execute()
                    if p.data:
                        initiator = p.data[0].get("name", initiator)
                except Exception:
                    pass
                actions.append(f"🔗 Connection request from **{initiator}**")

        # Pending meeting proposals.
        meetings = (
            sb.table("pending_approvals")
            .select("id")
            .eq("user_id", user_id)
            .eq("status", "pending")
            .limit(5)
            .execute()
        )
        if meetings.data:
            count = len(meetings.data)
            actions.append(f"📅 {count} meeting proposal{'s' if count > 1 else ''} awaiting your response")

    except Exception as e:
        logger.debug("[brief] pending actions fetch failed: %s", e)

    return actions


async def _get_todos(user_id: str) -> list[dict]:
    """Get the user's pending todos."""
    try:
        sb = config.get_supabase()
        rows = (
            sb.table("brief_todos")
            .select("title, done")
            .eq("user_id", user_id)
            .eq("done", False)
            .order("created_at", desc=False)
            .limit(5)
            .execute()
        )
        return rows.data or []
    except Exception:
        return []


async def _get_telegram_chat_id(user_id: str) -> str | None:
    """Get the user's linked Telegram chat ID."""
    try:
        sb = config.get_supabase()
        rows = (
            sb.table("telegram_links")
            .select("chat_id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if rows.data:
            return rows.data[0].get("chat_id")
    except Exception:
        pass
    return None


async def _send_telegram_message(chat_id: str, text: str) -> None:
    """Send a Markdown message via Telegram bot."""
    import httpx

    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

    # Telegram has a 4096 char limit for messages.
    truncated = text[:4000]

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": truncated,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        resp.raise_for_status()
