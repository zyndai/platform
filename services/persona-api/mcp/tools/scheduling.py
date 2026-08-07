"""
Scheduling MCP tools — thin wrappers around services.meetings.

These are what the orchestrator calls during chat. They delegate all
logic to services.meetings so the REST endpoints (api/meetings.py) can
share the same state machine.

Internal mode (principal chatting with their own agent):
  - propose_meeting  — the agent formalises a negotiated time as a ticket.
  - respond_to_meeting — act on a ticket the principal received.
  - list_pending_meetings — answer "what meetings am I expecting?".

External mode (foreign agent contacting us):
  - propose_meeting is unlocked only when the thread's
    can_request_meetings permission is true (see orchestrator's
    EXTERNAL_PERMISSION_GATES). Even then, the foreign agent can ONLY
    propose; it can't accept its own proposal — the actor-same-as-last-mover
    guard in services.meetings enforces that.
  - respond_to_meeting is NEVER in the external allowlist. A foreign
    agent shouldn't be able to accept/counter/decline tickets on our DB;
    the recipient's own user (or their own agent) does that via the UI
    or the recipient's own internal-mode chat.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mcp.tools.error_utils import friendly_error, friendly_error_message
from services import meetings as meetings_svc


def _format_group_meeting_line(
    *,
    title: str,
    start_time: str,
    end_time: str,
    time_zone: str | None,
    attendee_count: int,
) -> str:
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(time_zone) if time_zone else timezone.utc
    except Exception:
        tz = timezone.utc

    def _to_dt(s: str) -> datetime:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(tz)

    try:
        sdt = _to_dt(start_time)
        edt = _to_dt(end_time)
    except Exception:
        clean = lambda x: x.replace("Z", " UTC").replace("T", " ")
        line = f"{title} confirmed — {clean(start_time)} → {clean(end_time)}."
        if attendee_count:
            line += f" Invites sent to {attendee_count} member(s)."
        return line

    same_day = sdt.date() == edt.date()
    day_part = sdt.strftime("%a %b %-d")
    start_part = sdt.strftime("%-I:%M %p").lstrip("0")
    end_part = edt.strftime("%-I:%M %p").lstrip("0")
    tz_part = sdt.strftime("%Z") or (time_zone or "UTC")

    if same_day:
        when = f"{day_part}, {start_part}–{end_part} {tz_part}"
    else:
        end_day = edt.strftime("%a %b %-d")
        when = f"{day_part} {start_part} → {end_day} {end_part} {tz_part}"

    line = f"{title} confirmed — {when}."
    if attendee_count:
        line += f" Invites sent to {attendee_count} member(s)."
    return line


def propose_meeting(
    user_id: str,
    thread_id: str,
    title: str,
    start_time: str,
    end_time: str,
    location: str = "",
    description: str = "",
) -> dict:
    """
    Propose a meeting directly on an accepted DM thread.

    If the principal supplied a specific time, use it. If not, infer a
    reasonable default slot (e.g. the next business-hour opening) from
    their calendar. The other side receives the proposal as a meeting
    card they can accept, counter, or decline — this IS the negotiation
    mechanism, so do not ask the other agent for availability first.

    Args:
        user_id: The user on whose behalf the proposal is being made (injected).
        thread_id: The dm_threads row this meeting lives on. Both sides must already
                   be connected on this thread.
        title: A short, human-readable title (e.g. "Zynd Founders Sync").
        start_time: ISO-8601 start timestamp in UTC (e.g. "2026-04-14T15:00:00Z").
        end_time: ISO-8601 end timestamp in UTC.
        location: Optional venue or video-call URL.
        description: Optional agenda / longer body.
    """
    try:
        row = meetings_svc.create_proposal(
            thread_id=thread_id,
            actor_user_id=user_id,
            payload={
                "title": title,
                "start_time": start_time,
                "end_time": end_time,
                "location": location,
                "description": description,
            },
        )
    except meetings_svc.MeetingError as e:
        return friendly_error_message("propose the meeting", str(e))

    return {
        "status": "success",
        "task_id": row["id"],
        "thread_id": row["thread_id"],
        "meeting_status": row["status"],
        "payload": row["payload"],
        "message": f"Meeting proposal '{title}' sent. Awaiting the other side's confirmation.",
    }


def respond_to_meeting(
    user_id: str,
    task_id: str,
    action: str,
    title: str = "",
    start_time: str = "",
    end_time: str = "",
    location: str = "",
    description: str = "",
) -> dict:
    """
    Respond to an existing meeting ticket.

    Args:
        user_id: The user responding (injected).
        task_id: ID of the agent_tasks row to update.
        action: One of 'accept', 'counter', 'decline', 'cancel'.
            - accept: confirm the current payload (the other side must accept yours
                      if you were the last proposer; you cannot accept your own).
            - counter: change one or more fields of the payload and wait for them.
            - decline: refuse the proposal.
            - cancel: withdraw the ticket (initiator only, pre-scheduled).
        title, start_time, end_time, location, description: Used only when action='counter'.
            Pass just the fields you want to change.
    """
    edits: dict[str, Any] = {}
    if action == "counter":
        if title:       edits["title"] = title
        if start_time:  edits["start_time"] = start_time
        if end_time:    edits["end_time"] = end_time
        if location:    edits["location"] = location
        if description: edits["description"] = description

    try:
        row = meetings_svc.respond_to_proposal(
            task_id=task_id,
            actor_user_id=user_id,
            action=action,
            edits=edits or None,
        )
    except meetings_svc.MeetingError as e:
        return friendly_error_message("respond to the meeting", str(e))

    return {
        "status": "success",
        "task_id": row["id"],
        "thread_id": row["thread_id"],
        "meeting_status": row["status"],
        "payload": row["payload"],
        "message": f"Meeting {row['status']}.",
    }


def propose_group_meeting(
    user_id: str,
    group_id: str,
    title: str,
    start_time: str,
    end_time: str,
    location: str = "",
    description: str = "",
    time_zone: str = "",
    force: bool = False,
) -> dict:
    """
    Propose a meeting in a group room. Use this (NOT propose_meeting) when
    you're @-mentioned in a group and asked to schedule a time. Externally
    invoked calls of this tool are gated by the approval flow — the
    principal sees a card in their inbox and decides accept/decline. On
    accept, the actual calendar event is created with every other group
    member as an attendee (Google sends invitations), and a system message
    is posted to the group chat so everyone sees the confirmed slot.

    Before creating the event, this checks the asker's own calendar for a
    conflict at the requested time. If one exists (and force=False), NO
    event is created — you get back {status: "conflict", conflicting_events,
    suggested_times, message} instead. Present the conflict and
    suggested_times to the principal and ask what they want to do; only
    retry with force=true if they explicitly say to book it anyway despite
    the overlap.

    Args:
        user_id:    The principal whose calendar the event will be created on (injected).
        group_id:   The persona_groups row this meeting is scoped to (injected from group context).
        title:      Short human title, e.g. "Dev intro".
        start_time: ISO-8601 start in UTC, e.g. "2026-05-15T19:00:00Z".
        end_time:   ISO-8601 end in UTC.
        location:   Optional venue or video-call URL.
        description: Optional agenda / longer body.
        time_zone:  IANA tz of the ASKER (e.g. "Asia/Kolkata"). Used to render
                    the group chat confirmation line in their wall-clock time
                    instead of raw UTC. Pass the asker's tz from your prompt
                    context. Leave blank only if truly unknown.
        force:      Skip the conflict check and book anyway. Only set this
                    when the principal has explicitly said to double-book /
                    proceed after seeing a reported conflict.
    """
    from datetime import datetime, timezone
    import asyncio
    import config
    from api.groups import _create_event_with_attendees, _fetch_user_emails

    sb = config.get_supabase()

    g = sb.table("persona_groups").select("id, name, archived_at").eq("id", group_id).limit(1).execute()
    if not g.data or g.data[0].get("archived_at"):
        return {
            "error": "Group not found",
            "error_message": "That group doesn't exist or has been archived.",
            "hint": "Check the group name or create a new group.",
        }
    group_name = g.data[0]["name"]

    roster = (
        sb.table("persona_group_members")
        .select("user_id")
        .eq("group_id", group_id)
        .execute()
    )
    all_uids = [r["user_id"] for r in (roster.data or [])]
    if user_id not in all_uids:
        return {
            "error": "Not a group member",
            "error_message": "You need to be a member of this group to schedule a meeting there.",
            "hint": "Ask the group owner to add you, or pick a different group.",
        }
    attendee_uids = [u for u in all_uids if u != user_id]

    try:
        attendee_emails = _fetch_user_emails(attendee_uids) if attendee_uids else []
    except Exception as e:
        return friendly_error("look up attendee emails", e)

    attendees_payload = [{"email": e} for e in attendee_emails if e]
    result = _create_event_with_attendees(
        user_id=user_id,
        summary=title,
        start_time=start_time,
        end_time=end_time,
        description=description or f"Proposed in group: {group_name}",
        location=location or "",
        time_zone=time_zone or "UTC",
        attendees=attendees_payload,
        force=force,
    )
    if result.get("conflict"):
        return {
            "status": "conflict",
            "conflict": True,
            "conflicting_events": result.get("conflicting_events", []),
            "suggested_times": result.get("suggested_times", []),
            "message": result.get("error"),
        }
    if not result.get("success"):
        raw = result.get("error") or "Couldn't create the calendar event."
        meta = friendly_error_message("create the group calendar event", raw)
        return meta

    ev = result.get("event") or {}
    try:
        meta = {
            "kind": "group_meeting_proposal",
            "event_id": ev.get("id"),
            "title": title,
            "start": start_time,
            "end": end_time,
            "location": location or None,
            "html_link": ev.get("htmlLink"),
            "attendee_count": len(attendees_payload),
            "proposed_by": user_id,
            "time_zone": time_zone or None,
            "via": "persona_approval",
        }
        line = _format_group_meeting_line(
            title=title,
            start_time=start_time,
            end_time=end_time,
            time_zone=time_zone,
            attendee_count=len(attendees_payload),
        )
        sb.table("persona_group_messages").insert({
            "group_id": group_id,
            "sender_user_id": user_id,
            "sender_name": "Zynd",
            "channel": "system",
            "content": line.strip(),
            "metadata": meta,
        }).execute()
        sb.table("persona_groups").update({
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", group_id).execute()
    except Exception as e:
        # Don't fail the whole tool — event was created; the system note
        # is best-effort.
        return {
            "status": "success",
            "event_id": ev.get("id"),
            "html_link": ev.get("htmlLink"),
            "warning": f"Calendar event created but group message failed: {e}",
        }

    return {
        "status": "success",
        "event_id": ev.get("id"),
        "html_link": ev.get("htmlLink"),
        "attendee_count": len(attendees_payload),
        "message": f"Meeting '{title}' scheduled. Invitations sent to {len(attendees_payload)} member(s).",
    }


def list_pending_meetings(user_id: str) -> dict:
    """
    List the principal's open meeting tickets, split by who the next
    move belongs to. Use this when the principal asks things like
    "what meetings am I waiting on?" or "do I need to respond to anything?".
    """
    result = meetings_svc.list_pending_for_user(user_id)
    return {
        "status": "success",
        "awaiting_me_count": len(result["awaiting_me"]),
        "awaiting_them_count": len(result["awaiting_them"]),
        "awaiting_me": result["awaiting_me"],
        "awaiting_them": result["awaiting_them"],
    }
