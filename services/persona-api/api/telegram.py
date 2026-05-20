"""
Telegram bot bridge.

Receives Telegram webhook events, maps chat_ids to Zynd users via the
telegram_links DB table (replacing the old telegram_users.json), and
routes messages through the orchestrator. Conversation history is
persisted per-chat in telegram_chat_history so the bot remembers prior
turns across backend restarts.

Handshake flow:
  1. User clicks "Connect Telegram" in the webapp → opens a deep link
     `https://t.me/<bot>?start=<supabase_user_id>`.
  2. Telegram opens the bot with `/start <supabase_user_id>`.
  3. We parse the token, persist the (user_id, chat_id) link row, and
     reply with a confirmation.

Memory flow:
  1. Load the persisted message list from telegram_chat_history into
     orchestrator._conversations[conv_id].
  2. Call handle_user_message — it appends the new turn to that list
     in place, exactly as it would for an ephemeral in-memory conv.
  3. Read the updated list back out of _conversations and upsert it
     to the DB so the next turn picks up the context.

Slash commands:
  Routed through `_dispatch_slash_command`. Each command has its own
  `_handle_<name>` coroutine; the dispatcher just looks up the base
  command (strips a trailing `@botname`) and calls it with the parsed
  arg string. Slash commands never go through the orchestrator — they
  hit the underlying MCP tool / DB directly so they're cheap, fast,
  and don't burn LLM tokens for what is effectively a structured query.

v1 doesn't summarize or window the history — the full list is loaded
every turn. If context limits bite, we'll cap to the last N turns here.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Awaitable, Callable

import httpx
from fastapi import APIRouter, BackgroundTasks, Request

from agent.orchestrator import _conversations, handle_user_message
from services import telegram_store
import config

logger = logging.getLogger(__name__)

router = APIRouter()

TELEGRAM_TOKEN = config.TELEGRAM_BOT_TOKEN
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

DASHBOARD_BASE = "https://persona.zynd.ink"

# Telegram caps a single message at 4096 chars. Lists get truncated at
# this many rows with a "…and N more" footer instead.
MAX_LIST_ROWS = 20
TELEGRAM_MSG_CAP = 3900  # leave headroom for Markdown escape sequences


# ── Telegram low-level send ──────────────────────────────────────────

async def send_telegram_message(
    chat_id: int | str,
    text: str,
    *,
    parse_mode: str | None = "Markdown",
) -> bool:
    """Send a plain message. Returns True on success, False on any
    Telegram or network error. Never raises — slash command handlers
    rely on this being best-effort."""
    if not TELEGRAM_TOKEN:
        logger.warning("[Telegram] Bot token not configured; cannot send.")
        return False

    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
        if resp.status_code >= 400:
            logger.warning(f"[Telegram] sendMessage HTTP {resp.status_code}: {resp.text[:200]}")
            # Retry once without Markdown parse mode — Telegram is finicky
            # about unbalanced underscores etc., and we'd rather show raw
            # text than nothing.
            if parse_mode:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        f"{TELEGRAM_API_URL}/sendMessage",
                        json={"chat_id": chat_id, "text": text},
                    )
                return resp.status_code < 400
            return False
        return True
    except Exception as e:
        logger.warning(f"[Telegram] sendMessage failed: {e}")
        return False


# ── Markdown escaping ────────────────────────────────────────────────

_MD_ESCAPE = {
    "_": "\\_",
    "*": "\\*",
    "[": "\\[",
    "]": "\\]",
    "`": "\\`",
}


def _escape_md(text: str | None) -> str:
    """Escape Telegram Markdown (legacy/v1) special chars in user-provided
    strings so a name like `John_Doe` doesn't get interpreted as italic."""
    if not text:
        return ""
    out = []
    for ch in str(text):
        out.append(_MD_ESCAPE.get(ch, ch))
    return "".join(out)


def _truncate_list(rows: list[str], cap: int = MAX_LIST_ROWS) -> list[str]:
    """Truncate a list of rendered list-rows to `cap`; append an
    "…and N more" footer when truncated."""
    if len(rows) <= cap:
        return rows
    keep = rows[:cap]
    keep.append(f"…and {len(rows) - cap} more")
    return keep


def _safe_msg(text: str) -> str:
    """Hard cap on Telegram message length."""
    if len(text) <= TELEGRAM_MSG_CAP:
        return text
    return text[: TELEGRAM_MSG_CAP - 3] + "..."


# ── Conversation namespace ───────────────────────────────────────────

def _conv_id_for(chat_id: str) -> str:
    """Conversation id namespace for Telegram chats — kept separate from
    the webapp's conversation ids so the two surfaces don't bleed into
    each other."""
    return f"tg_{chat_id}"


# ── Help text ────────────────────────────────────────────────────────

HELP_TEXT = (
    "*Zynd Persona — Telegram commands*\n\n"
    "*Brief*\n"
    "• /brief — show your current brief\n"
    "• /brief\\_add <text> — append a line\n"
    "• /brief\\_replace <text> — rewrite the entire brief\n"
    "• /brief\\_clear — empty the brief\n\n"
    "*Calendar & meetings*\n"
    "• /meetings — pending meeting tickets\n"
    "• /calendar [today|week] — events on your calendar\n\n"
    "*Network*\n"
    "• /inbox — recent agent-channel messages awaiting a reply\n"
    "• /who <name> — find a persona on the Zynd Network\n"
    "• /connect <handle> — send a connection request\n"
    "• /connections — your network connections\n\n"
    "*Todos*\n"
    "• /todos — list open todos\n"
    "• /todo <text> — add a todo\n\n"
    "*Other*\n"
    "• /reset — forget our chat history\n"
    "• /help — this message\n\n"
    "Anything else, just say it in plain English and I'll figure it out."
)


# ── Brief command helpers ────────────────────────────────────────────

def _brief_error_message(result: dict) -> str:
    """Format a brief-tool error result for Telegram. Surfaces the
    structured codes (`no_persona`, `google_unavailable`) with their
    clickable links; falls back to the raw error string otherwise."""
    code = result.get("code")
    if code in ("no_persona", "google_unavailable"):
        # The brief tool already composed a user-facing message that
        # includes a URL — let Telegram render it as a clickable link.
        return f"⚠️ {result.get('error') or result.get('message') or 'Something went wrong.'}"
    return f"⚠️ {result.get('error') or 'Something went wrong.'}"


# ── Slash command handlers ───────────────────────────────────────────
#
# Each handler takes (user_id, chat_id, arg_str) and is responsible for
# sending its own Telegram reply. They never raise — fail-soft is the
# contract.

async def _handle_help(user_id: str, chat_id: int, _arg: str) -> None:
    await send_telegram_message(chat_id, HELP_TEXT)


async def _handle_reset(user_id: str, chat_id: int, _arg: str) -> None:
    chat_id_str = str(chat_id)
    telegram_store.clear_history(_conv_id_for(chat_id_str))
    _conversations.pop(_conv_id_for(chat_id_str), None)
    await send_telegram_message(
        chat_id, "🧹 Okay, I've forgotten our previous conversation. Fresh start!"
    )


# Brief ----------------------------------------------------------------

async def _handle_brief(user_id: str, chat_id: int, _arg: str) -> None:
    from mcp.tools.brief import read_my_brief

    result = read_my_brief(user_id=user_id)
    if not result.get("success"):
        await send_telegram_message(chat_id, _brief_error_message(result))
        return

    if not result.get("exists"):
        await send_telegram_message(
            chat_id,
            "📝 You don't have a brief yet.\nAdd a line with `/brief_add <text>`.",
        )
        return

    content = (result.get("content") or "").strip()
    url = result.get("url") or ""
    if not content:
        body = "_(your brief is empty)_"
    else:
        body = _escape_md(content)
    header = "*Your brief*"
    if url:
        header = f"*Your brief* — [open in Google Docs]({url})"
    msg = f"{header}\n\n{body}"
    await send_telegram_message(chat_id, _safe_msg(msg))


async def _handle_brief_add(user_id: str, chat_id: int, arg: str) -> None:
    from mcp.tools.brief import append_to_my_brief

    text = arg.strip()
    if not text:
        await send_telegram_message(
            chat_id, "Usage: `/brief_add <text>` — what should I append to your brief?"
        )
        return
    result = append_to_my_brief(user_id=user_id, text=text)
    if not result.get("success"):
        await send_telegram_message(chat_id, _brief_error_message(result))
        return
    await send_telegram_message(
        chat_id, f"✅ Added to your brief:\n_{_escape_md(text)}_"
    )


async def _handle_brief_replace(user_id: str, chat_id: int, arg: str) -> None:
    from mcp.tools.brief import replace_my_brief

    text = arg.strip()
    if not text:
        await send_telegram_message(
            chat_id,
            "Usage: `/brief_replace <text>` — pass the full new body. "
            "(Use `/brief_clear` to empty it instead.)",
        )
        return
    result = replace_my_brief(user_id=user_id, content=text)
    if not result.get("success"):
        await send_telegram_message(chat_id, _brief_error_message(result))
        return
    await send_telegram_message(chat_id, "✅ Brief replaced.")


async def _handle_brief_clear(user_id: str, chat_id: int, _arg: str) -> None:
    from mcp.tools.brief import clear_my_brief

    result = clear_my_brief(user_id=user_id)
    if not result.get("success"):
        await send_telegram_message(chat_id, _brief_error_message(result))
        return
    await send_telegram_message(chat_id, "🧹 Brief cleared.")


# Meetings -------------------------------------------------------------

def _format_meeting_when(row: dict) -> str:
    payload = row.get("payload") or {}
    start = payload.get("start_time") or payload.get("start") or row.get("start_time") or "?"
    return str(start)


def _format_meeting_partner_name(row: dict, user_id: str) -> str:
    if row.get("initiator_user_id") == user_id:
        return row.get("recipient_name") or "the other side"
    return row.get("initiator_name") or "the other side"


async def _handle_meetings(user_id: str, chat_id: int, _arg: str) -> None:
    from mcp.tools.scheduling import list_pending_meetings

    try:
        result = list_pending_meetings(user_id=user_id)
    except Exception as e:
        logger.warning(f"[/meetings] failed: {e}")
        await send_telegram_message(chat_id, f"⚠️ Couldn't load meetings: {e}")
        return

    awaiting_me = result.get("awaiting_me") or []
    awaiting_them = result.get("awaiting_them") or []
    if not awaiting_me and not awaiting_them:
        await send_telegram_message(chat_id, "You have no pending meetings.")
        return

    rows: list[str] = []
    for row in awaiting_me:
        title = (row.get("payload") or {}).get("title") or row.get("title") or "Untitled"
        when = _format_meeting_when(row)
        partner = _format_meeting_partner_name(row, user_id)
        rows.append(
            f"• {_escape_md(title)} — {_escape_md(when)} — needs *you* (with {_escape_md(partner)})"
        )
    for row in awaiting_them:
        title = (row.get("payload") or {}).get("title") or row.get("title") or "Untitled"
        when = _format_meeting_when(row)
        partner = _format_meeting_partner_name(row, user_id)
        rows.append(
            f"• {_escape_md(title)} — {_escape_md(when)} — needs *{_escape_md(partner)}*"
        )

    rows = _truncate_list(rows)
    msg = "*Pending meetings*\n\n" + "\n".join(rows)
    await send_telegram_message(chat_id, _safe_msg(msg))


# Calendar -------------------------------------------------------------

def _parse_iso_to_dt(iso_str: str) -> datetime | None:
    """Parse an ISO 8601 string (with or without Z / +00:00) into an
    aware datetime in UTC. Returns None on parse failure."""
    if not iso_str:
        return None
    try:
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


async def _handle_calendar(user_id: str, chat_id: int, arg: str) -> None:
    from mcp.tools.google.calendar import list_events

    scope = (arg.strip().lower() or "today")
    if scope not in ("today", "week"):
        await send_telegram_message(
            chat_id, "Usage: `/calendar today` or `/calendar week`."
        )
        return

    # list_events takes only max_results (returns upcoming events from
    # now, ordered). We pull a generous window and filter client-side
    # by the requested scope.
    try:
        result = list_events(user_id=user_id, max_results=50)
    except Exception as e:
        logger.warning(f"[/calendar] failed: {e}")
        await send_telegram_message(chat_id, f"⚠️ Couldn't load calendar: {e}")
        return

    if not result.get("success"):
        await send_telegram_message(
            chat_id, f"⚠️ Couldn't load calendar: {result.get('error')}"
        )
        return

    now = datetime.now(timezone.utc)
    if scope == "today":
        window_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
        window_end = window_start + timedelta(days=1)
    else:  # week
        window_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
        window_end = window_start + timedelta(days=7)

    events: list[dict] = []
    for e in result.get("events") or []:
        start_dt = _parse_iso_to_dt(e.get("start") or "")
        if not start_dt:
            continue
        if window_start <= start_dt < window_end:
            events.append({
                "title": e.get("summary") or "(No title)",
                "start": start_dt,
                "end": _parse_iso_to_dt(e.get("end") or "") or start_dt,
            })

    events.sort(key=lambda x: x["start"])

    if not events:
        label = "today" if scope == "today" else "this week"
        await send_telegram_message(chat_id, f"Nothing on your calendar {label}.")
        return

    if scope == "today":
        rows = [
            f"{ev['start'].strftime('%H:%M')}-{ev['end'].strftime('%H:%M')} {_escape_md(ev['title'])}"
            for ev in events
        ]
        rows = _truncate_list(rows)
        msg = "*Today*\n\n" + "\n".join(rows)
    else:
        # Group by date.
        by_date: dict[str, list[str]] = {}
        for ev in events:
            d = ev["start"].strftime("%a %b %d")
            by_date.setdefault(d, []).append(
                f"{ev['start'].strftime('%H:%M')}-{ev['end'].strftime('%H:%M')} {_escape_md(ev['title'])}"
            )
        rendered_lines: list[str] = []
        for d, lines in by_date.items():
            rendered_lines.append(f"*{d}*")
            rendered_lines.extend(lines)
            rendered_lines.append("")
        rendered_lines = _truncate_list(rendered_lines, cap=MAX_LIST_ROWS * 2)
        msg = "*This week*\n\n" + "\n".join(rendered_lines).strip()

    await send_telegram_message(chat_id, _safe_msg(msg))


# Inbox ----------------------------------------------------------------

async def _handle_inbox(user_id: str, chat_id: int, _arg: str) -> None:
    """Show recent agent-channel inbound messages where the user hasn't
    replied. v1 heuristic: for each thread the user's agent participates
    in, find the most recent message from the OTHER side and, if there's
    nothing newer from our side on that thread, list it."""
    from agent.persona_manager import get_persona_status

    sb = config.get_supabase()

    try:
        persona = get_persona_status(user_id)
    except Exception as e:
        logger.warning(f"[/inbox] persona lookup failed: {e}")
        await send_telegram_message(chat_id, f"⚠️ Couldn't load inbox: {e}")
        return

    my_agent_id = persona.get("agent_id")
    if not my_agent_id:
        await send_telegram_message(
            chat_id,
            "📭 You don't have a persona yet — connect one at "
            f"{DASHBOARD_BASE}/dashboard.",
        )
        return

    # Identify all threads I'm a participant in.
    try:
        r1 = sb.table("dm_threads").select("*").eq("initiator_id", my_agent_id).execute()
        r2 = sb.table("dm_threads").select("*").eq("receiver_id", my_agent_id).execute()
    except Exception as e:
        logger.warning(f"[/inbox] thread fetch failed: {e}")
        await send_telegram_message(chat_id, f"⚠️ Couldn't load inbox: {e}")
        return

    threads = (r1.data or []) + (r2.data or [])
    if not threads:
        await send_telegram_message(chat_id, "📭 Inbox clear.")
        return

    awaiting: list[tuple[str, str, str]] = []  # (partner_name, content, ts)
    for t in threads:
        thread_id = t["id"]
        partner_name = (
            t.get("receiver_name") if t.get("initiator_id") == my_agent_id
            else t.get("initiator_name")
        ) or "Unknown"

        try:
            msgs_r = (
                sb.table("dm_messages")
                .select("*")
                .eq("thread_id", thread_id)
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
        except Exception as e:
            logger.warning(f"[/inbox] dm_messages fetch failed for thread {thread_id}: {e}")
            continue

        msgs = msgs_r.data or []
        if not msgs:
            continue

        latest_from_me = None
        latest_from_other = None
        for m in msgs:
            sender_id = m.get("sender_id")
            if sender_id == my_agent_id or sender_id == user_id:
                if latest_from_me is None:
                    latest_from_me = m
            else:
                if latest_from_other is None:
                    latest_from_other = m
            if latest_from_me and latest_from_other:
                break

        if not latest_from_other:
            continue
        if latest_from_me and latest_from_me.get("created_at", "") >= latest_from_other.get("created_at", ""):
            continue

        content = (latest_from_other.get("content") or "").strip()
        snippet = content[:80] + ("…" if len(content) > 80 else "")
        awaiting.append((partner_name, snippet, latest_from_other.get("created_at", "")))

    if not awaiting:
        await send_telegram_message(chat_id, "📭 Inbox clear.")
        return

    awaiting.sort(key=lambda x: x[2], reverse=True)
    awaiting = awaiting[:10]
    rows = [
        f"• *{_escape_md(name)}*: \"{_escape_md(snippet)}\""
        for name, snippet, _ in awaiting
    ]
    msg = "*Inbox — awaiting your reply*\n\n" + "\n".join(rows)
    await send_telegram_message(chat_id, _safe_msg(msg))


# Network --------------------------------------------------------------

def _persona_handle(p: dict) -> str | None:
    """Extract a usable t.me / agent handle from a persona search result."""
    h = (p.get("agent_handle") or "").strip()
    if h:
        return h
    profile = p.get("profile") or {}
    if isinstance(profile, dict):
        for k in ("agent_handle", "telegram_handle", "twitter_handle"):
            v = (profile.get(k) or "").strip()
            if v:
                return v
    return None


async def _handle_who(user_id: str, chat_id: int, arg: str) -> None:
    from mcp.tools.zynd_network import search_zynd_personas

    name = arg.strip()
    if not name:
        await send_telegram_message(chat_id, "Usage: `/who <name>`")
        return

    try:
        result = search_zynd_personas(query=name, top_k=3)
    except Exception as e:
        logger.warning(f"[/who] failed: {e}")
        await send_telegram_message(chat_id, f"⚠️ Search failed: {e}")
        return

    personas = result.get("results") or []
    if not personas:
        await send_telegram_message(chat_id, f"No personas found for *{_escape_md(name)}*.")
        return

    blocks: list[str] = []
    for p in personas[:3]:
        pname = _escape_md(p.get("name") or "Unknown")
        desc = (p.get("description") or "").strip()
        if len(desc) > 200:
            desc = desc[:200] + "…"
        handle = _persona_handle(p)
        line2_bits: list[str] = []
        if handle:
            line2_bits.append(f"@{_escape_md(handle)} — [t.me/{_escape_md(handle)}](https://t.me/{handle})")
        if desc:
            line2_bits.append(_escape_md(desc))
        block = f"• *{pname}*"
        if line2_bits:
            block += "\n  " + "\n  ".join(line2_bits)
        blocks.append(block)

    msg = "*People matching that name*\n\n" + "\n\n".join(blocks)
    await send_telegram_message(chat_id, _safe_msg(msg))


async def _handle_connect(user_id: str, chat_id: int, arg: str) -> None:
    from mcp.tools.zynd_network import (
        request_connection,
        search_zynd_personas,
    )

    handle = arg.strip().lstrip("@")
    if not handle:
        await send_telegram_message(chat_id, "Usage: `/connect <handle>`")
        return

    try:
        search = search_zynd_personas(query=handle, top_k=5)
    except Exception as e:
        logger.warning(f"[/connect] search failed: {e}")
        await send_telegram_message(chat_id, f"⚠️ Couldn't resolve `{_escape_md(handle)}`: {e}")
        return

    target = None
    for p in search.get("results") or []:
        candidate_handle = _persona_handle(p) or ""
        if candidate_handle.lower() == handle.lower():
            target = p
            break
    if target is None and (search.get("results") or []):
        # Fall back to the top match if the handle didn't exactly hit —
        # let the user see who we picked.
        target = search["results"][0]

    if not target:
        await send_telegram_message(
            chat_id, f"No persona matches `{_escape_md(handle)}`."
        )
        return

    target_agent_id = target.get("agent_id")
    target_name = target.get("name") or handle
    if not target_agent_id:
        await send_telegram_message(
            chat_id, f"⚠️ Couldn't resolve `{_escape_md(handle)}` to an agent."
        )
        return

    try:
        result = request_connection(
            user_id=user_id,
            target_agent_id=target_agent_id,
            target_name=target_name,
        )
    except Exception as e:
        logger.warning(f"[/connect] request_connection failed: {e}")
        await send_telegram_message(chat_id, f"⚠️ Connection request failed: {e}")
        return

    status = result.get("status")
    if status == "already_exists":
        cstatus = result.get("connection_status") or "pending"
        await send_telegram_message(
            chat_id,
            f"You already have a *{_escape_md(cstatus)}* connection with *{_escape_md(target_name)}*.",
        )
        return
    if status == "success":
        await send_telegram_message(
            chat_id, f"🔗 Connection request sent to *{_escape_md(target_name)}*."
        )
        return
    if result.get("error"):
        await send_telegram_message(
            chat_id, f"⚠️ {_escape_md(result['error'])}"
        )
        return
    await send_telegram_message(
        chat_id, f"🔗 Connection request sent to *{_escape_md(target_name)}*."
    )


async def _handle_connections(user_id: str, chat_id: int, _arg: str) -> None:
    from mcp.tools.zynd_network import list_my_connections

    try:
        result = list_my_connections(user_id=user_id)
    except Exception as e:
        logger.warning(f"[/connections] failed: {e}")
        await send_telegram_message(chat_id, f"⚠️ Couldn't load connections: {e}")
        return

    my_agent_id = result.get("my_agent_id")
    accepted = result.get("connections") or []
    pending = result.get("pending_requests") or []

    incoming = [c for c in pending if not c.get("initiated_by_me")]
    outgoing = [c for c in pending if c.get("initiated_by_me")]

    sections: list[str] = []

    def _row(c: dict) -> str:
        name = _escape_md(c.get("partner_name") or "Unknown")
        # Partner handle isn't in the connections payload by default — show
        # the agent_id suffix instead so the user can copy it.
        handle = c.get("partner_agent_id") or ""
        handle_disp = handle[:8] if handle else ""
        return f"• *{name}* ({_escape_md(handle_disp)})"

    if accepted:
        sections.append("*Connected*\n" + "\n".join(_row(c) for c in _truncate_list(accepted)))
    else:
        sections.append("*Connected*\n_(none)_")

    if outgoing:
        sections.append(
            "*Pending (outgoing)*\n" + "\n".join(_row(c) for c in _truncate_list(outgoing))
        )

    if incoming:
        sections.append(
            "*Incoming requests*\n" + "\n".join(_row(c) for c in _truncate_list(incoming))
        )

    msg = "\n\n".join(sections)
    if not msg.strip():
        msg = "_No connections yet._"
    await send_telegram_message(chat_id, _safe_msg(msg))


# Todos ----------------------------------------------------------------

async def _handle_todos(user_id: str, chat_id: int, _arg: str) -> None:
    sb = config.get_supabase()
    try:
        rows = (
            sb.table("brief_todos")
            .select("id, title")
            .eq("user_id", user_id)
            .eq("done", False)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
    except Exception as e:
        logger.warning(f"[/todos] fetch failed: {e}")
        await send_telegram_message(chat_id, f"⚠️ Couldn't load todos: {e}")
        return

    data = rows.data or []
    if not data:
        await send_telegram_message(chat_id, "No open todos.")
        return

    lines: list[str] = []
    for r in data:
        tid = str(r.get("id") or "")
        suffix = tid.replace("-", "")[-4:] if tid else "----"
        title = _escape_md(r.get("title") or "(untitled)")
        lines.append(f"• [{suffix}] {title}")
    msg = "*Open todos*\n\n" + "\n".join(lines)
    await send_telegram_message(chat_id, _safe_msg(msg))


async def _handle_todo(user_id: str, chat_id: int, arg: str) -> None:
    """Both `/todo <text>` and `/todo add <text>` reach this handler.
    Anything after the optional `add` keyword becomes the todo title."""
    text = arg.strip()
    if text.lower().startswith("add "):
        text = text[4:].strip()
    elif text.lower() == "add":
        text = ""

    if not text:
        await send_telegram_message(
            chat_id,
            "Usage: `/todo <text>` — what should I add to your todos?",
        )
        return

    sb = config.get_supabase()
    try:
        sb.table("brief_todos").insert({
            "user_id": user_id,
            "title": text,
            "source_text": text,
            "done": False,
        }).execute()
    except Exception as e:
        logger.warning(f"[/todo] insert failed: {e}")
        await send_telegram_message(chat_id, f"⚠️ Couldn't add todo: {e}")
        return

    await send_telegram_message(chat_id, f"✅ Added todo: _{_escape_md(text)}_")


# ── Dispatcher ───────────────────────────────────────────────────────

# Each entry: command base name (without the leading `/`) → handler.
_SLASH_HANDLERS: dict[str, Callable[[str, int, str], Awaitable[None]]] = {
    "help": _handle_help,
    "reset": _handle_reset,
    "clear": _handle_reset,
    "brief": _handle_brief,
    "brief_add": _handle_brief_add,
    "brief_replace": _handle_brief_replace,
    "brief_clear": _handle_brief_clear,
    "meetings": _handle_meetings,
    "calendar": _handle_calendar,
    "inbox": _handle_inbox,
    "who": _handle_who,
    "connect": _handle_connect,
    "connections": _handle_connections,
    "todos": _handle_todos,
    "todo": _handle_todo,
}


def _parse_slash(text: str) -> tuple[str, str] | None:
    """If `text` is a slash command, return (cmd_base, arg_str).
    Otherwise return None. Handles the `@botname` group-form suffix."""
    if not text.startswith("/"):
        return None
    first, _, rest = text[1:].partition(" ")
    cmd_base = first.split("@", 1)[0].lower()
    if not cmd_base:
        return None
    return cmd_base, rest.strip()


async def _dispatch_slash_command(
    user_id: str,
    chat_id: int,
    cmd_base: str,
    arg_str: str,
) -> bool:
    """Look up and run a slash handler. Returns True if a handler ran
    (whether or not it succeeded), False if the command was unknown."""
    handler = _SLASH_HANDLERS.get(cmd_base)
    if not handler:
        return False
    try:
        await handler(user_id, chat_id, arg_str)
    except Exception as e:
        logger.exception(f"[telegram /{cmd_base}] handler crashed: {e}")
        await send_telegram_message(chat_id, f"⚠️ /{cmd_base} failed: {e}")
    return True


# ── Webhook entry point ──────────────────────────────────────────────

async def process_telegram_message(chat_id: int, text: str):
    chat_id_str = str(chat_id)

    # 1. Deep-linking handshake (/start <user_id>)
    if text.startswith("/start "):
        parts = text.split(" ", 1)
        user_id = parts[1].strip() if len(parts) > 1 else ""
        if not user_id:
            await send_telegram_message(
                chat_id,
                "⚠️ Missing link token. Please use the Connect Telegram button on your dashboard.",
            )
            return
        telegram_store.link_chat_to_user(chat_id_str, user_id)
        await send_telegram_message(
            chat_id,
            "✅ Awesome! Your Telegram is now securely linked to your Zynd Agent. "
            "You can chat with me directly here! What would you like to do?",
        )
        return

    # 2. Reject unauthenticated chats
    user_id = telegram_store.get_user_id_for_chat(chat_id_str)
    if not user_id:
        await send_telegram_message(
            chat_id,
            "⚠️ Your Telegram account is not linked to an active Persona. "
            "Please go to the Zynd Dashboard and click 'Connect Telegram'.",
        )
        return

    # 3. Basic /start (no token) after link — friendly welcome
    if text.strip() == "/start":
        await send_telegram_message(chat_id, "Welcome back! What can I assist you with today?")
        return

    # 4. Slash commands — direct dispatch (no LLM round-trip).
    parsed = _parse_slash(text.strip())
    if parsed:
        cmd_base, arg_str = parsed
        dispatched = await _dispatch_slash_command(user_id, chat_id, cmd_base, arg_str)
        if dispatched:
            return
        # Unknown slash command — show a friendly hint instead of routing
        # through the LLM (which is rarely the right answer for /foo).
        await send_telegram_message(
            chat_id,
            f"Unknown command `/{cmd_base}`. Try /help for the full list.",
        )
        return

    conv_id = _conv_id_for(chat_id_str)

    # 5. Orchestrate through the agent for free-form text.
    try:
        _conversations[conv_id] = telegram_store.load_history(conv_id)

        result = await handle_user_message(
            user_id=user_id,
            message=text,
            conversation_id=conv_id,
        )
        reply = result.get("reply", "Done.")

        telegram_store.save_history(
            user_id=user_id,
            conversation_id=conv_id,
            messages=_conversations.get(conv_id, []),
        )

        await send_telegram_message(chat_id, reply)
    except Exception as e:
        await send_telegram_message(chat_id, f"❌ Error processing request: {str(e)}")


@router.post("/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives incoming JSON payloads from Telegram servers in real-time.
    Returns 200 OK immediately and processes in a background task —
    Telegram retries aggressively if the webhook takes >5s.
    """
    try:
        data = await request.json()
    except Exception:
        return {"status": "ok"}

    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"]
        background_tasks.add_task(process_telegram_message, chat_id, text)

    return {"status": "ok"}


@router.get("/register")
async def register_webhook():
    """One-shot helper to register our public webhook URL with Telegram."""
    if not TELEGRAM_TOKEN:
        return {"error": "TELEGRAM_BOT_TOKEN is missing from .env"}

    webhook_url = f"{config.ZYND_WEBHOOK_BASE_URL}/api/telegram/webhook"
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{TELEGRAM_API_URL}/setWebhook", json={"url": webhook_url})

    return resp.json()
