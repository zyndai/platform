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

from typing import Any

from services import meetings as meetings_svc


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
    Formalise a meeting proposal as a ticket on the given DM thread.

    ONLY call this AFTER you have already negotiated availability via
    message_zynd_agent and your principal has explicitly confirmed a
    specific start/end time in plain text. Never propose cold.

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
        return {"error": str(e)}

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
        return {"error": str(e)}

    return {
        "status": "success",
        "task_id": row["id"],
        "thread_id": row["thread_id"],
        "meeting_status": row["status"],
        "payload": row["payload"],
        "message": f"Meeting {row['status']}.",
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
