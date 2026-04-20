"""
Meetings service — core logic for the agent_tasks ticket store.

This module is the single source of truth for meeting proposal state
transitions. Both the MCP tool layer (AI-driven) and the REST API layer
(UI-driven) call into these functions so the rules stay in one place.

State machine for type='meeting':

    proposed ──accept──▶ accepted ──(Chunk 4 booking worker)──▶ scheduled
        │                                                           │
        ├──counter──▶ countered ──accept──▶ accepted                │
        │                │                                          │
        │                └──decline──▶ declined                     │
        │                                                           │
        ├──decline──▶ declined                                      │
        │                                                           │
        └──cancel───▶ cancelled                                     │
                                                                    ▼
                                                              book_failed

Anyone can cancel a ticket they're a participant of at any terminal-ish
time before 'scheduled'. Once scheduled, use a separate cancel_meeting
flow (Chunk 4).

Notes:
  - v1 is same-platform: both users live in our Supabase, so there's one
    shared row and RLS lets either participant read+update it.
  - Realtime broadcasts land on the existing `system_pings` channel so
    both sides' frontends learn about task_created / task_updated events
    without polling.
  - All timestamps in the payload are stored as ISO-8601 strings exactly
    as the caller provided them. No parsing here; the calendar booking
    worker (Chunk 4) will normalise when it hits the Google API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import config

logger = logging.getLogger(__name__)


# ── Valid state transitions ──────────────────────────────────────────
# Keys are (current_status, action); values are the resulting status.
# Actions: accept, counter, decline, cancel.
ALLOWED_TRANSITIONS: dict[tuple[str, str], str] = {
    ("proposed",  "accept"):  "accepted",
    ("proposed",  "counter"): "countered",
    ("proposed",  "decline"): "declined",
    ("proposed",  "cancel"):  "cancelled",
    ("countered", "accept"):  "accepted",
    ("countered", "counter"): "countered",  # either side can keep countering
    ("countered", "decline"): "declined",
    ("countered", "cancel"):  "cancelled",
    ("accepted",  "cancel"):  "cancelled",  # pull-back after accept but before booking completes
    # Once booked onto calendars, either side can still cancel — we'll
    # delete the events from both calendars in the booking unwind path.
    ("scheduled", "cancel"):  "cancelled",
    # 'book_failed' is a terminal state set automatically after a failed
    # booking attempt. The user can retry by re-accepting from the UI,
    # which bounces it back through the flow.
    ("book_failed", "cancel"): "cancelled",
    ("book_failed", "accept"): "accepted",  # user retry
}

PAYLOAD_FIELDS = ("title", "start_time", "end_time", "location", "description")


class MeetingError(ValueError):
    """Raised for invalid state transitions or bad payloads."""


# ── Supabase + realtime helpers ──────────────────────────────────────

def _supabase():
    from supabase import create_client
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def _supabase_anon():
    from supabase import create_client
    return create_client(config.SUPABASE_URL, config.SUPABASE_ANON_KEY)


def _broadcast(event: str, payload: dict[str, Any]) -> None:
    """Fire-and-forget realtime broadcast on the shared `system_pings` channel."""
    try:
        _supabase_anon().channel("system_pings").send({
            "type": "broadcast",
            "event": event,
            "payload": payload,
        })
    except Exception as e:
        logger.warning(f"[meetings] broadcast failed for {event}: {e}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Thread lookup: translate a thread_id into a participant pair ─────

def _resolve_participants(sb, thread_id: str) -> dict[str, str]:
    """
    Given a thread, return the user_id + agent_id for both sides.
    Assumes both participants are on this platform (same-DB v1).
    """
    t = sb.table("dm_threads").select("*").eq("id", thread_id).execute()
    if not t.data:
        raise MeetingError(f"Thread {thread_id} not found")
    row = t.data[0]

    initiator_agent_id = row["initiator_id"]
    receiver_agent_id  = row["receiver_id"]

    def _user_for_agent(agent_id: str) -> str | None:
        r = sb.table("persona_agents").select("user_id").eq("agent_id", agent_id).execute()
        return r.data[0]["user_id"] if r.data else None

    initiator_user_id = _user_for_agent(initiator_agent_id)
    receiver_user_id  = _user_for_agent(receiver_agent_id)

    if not initiator_user_id or not receiver_user_id:
        raise MeetingError(
            "Both participants must be on this platform for v1 meeting scheduling "
            f"(thread {thread_id} has initiator={initiator_agent_id}, receiver={receiver_agent_id})"
        )

    return {
        "initiator_user_id":  initiator_user_id,
        "initiator_agent_id": initiator_agent_id,
        "receiver_user_id":   receiver_user_id,
        "receiver_agent_id":  receiver_agent_id,
    }


# ── Payload validation ───────────────────────────────────────────────

def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep only known payload fields; strip empty values."""
    out: dict[str, Any] = {}
    for k in PAYLOAD_FIELDS:
        v = payload.get(k)
        if v is None or v == "":
            continue
        out[k] = v
    if not out.get("title"):
        raise MeetingError("title is required")
    if not out.get("start_time") or not out.get("end_time"):
        raise MeetingError("start_time and end_time are required")
    return out


def _append_history(history: list[dict], entry: dict) -> list[dict]:
    return [*history, entry]


# ── Public API ───────────────────────────────────────────────────────

def create_proposal(
    *,
    thread_id: str,
    actor_user_id: str,
    payload: dict[str, Any],
) -> dict:
    """
    Create a new meeting proposal in 'proposed' state. The actor must be
    a participant of the given thread. The ticket is written to the DB
    and a realtime `task_created` event is broadcast to both sides.

    Returns the newly-inserted agent_tasks row.
    """
    sb = _supabase()
    participants = _resolve_participants(sb, thread_id)

    # The actor must be one of the two participants
    if actor_user_id not in (participants["initiator_user_id"], participants["receiver_user_id"]):
        raise MeetingError("Actor is not a participant of this thread.")

    # Idempotency guard: refuse if an active proposal already exists on this
    # thread. Either side can duplicate if they call propose_meeting twice in
    # a row (e.g. LLM doesn't realize the peer already created one), so hard-
    # enforce "one open proposal per thread" here.
    existing = (
        sb.table("agent_tasks")
        .select("id,status,initiator_user_id,recipient_user_id,payload")
        .eq("thread_id", thread_id)
        .eq("type", "meeting")
        .in_("status", ["proposed", "countered", "accepted"])
        .execute()
    )
    if existing.data:
        existing_row = existing.data[0]
        raise MeetingError(
            f"There is already an active meeting proposal on this thread "
            f"(task_id={existing_row['id']}, status={existing_row['status']}). "
            f"Respond to it with respond_to_meeting (accept/counter/decline) "
            f"instead of creating a duplicate."
        )

    cleaned = _clean_payload(payload)

    # Figure out which side the actor is so the row's initiator/recipient
    # columns reflect who *proposed*, not just who started the thread.
    if actor_user_id == participants["initiator_user_id"]:
        initiator_user = participants["initiator_user_id"]
        initiator_agent = participants["initiator_agent_id"]
        recipient_user = participants["receiver_user_id"]
        recipient_agent = participants["receiver_agent_id"]
    else:
        initiator_user = participants["receiver_user_id"]
        initiator_agent = participants["receiver_agent_id"]
        recipient_user = participants["initiator_user_id"]
        recipient_agent = participants["initiator_agent_id"]

    history = [{
        "at": _now_iso(),
        "actor_user_id": actor_user_id,
        "actor_agent_id": initiator_agent,
        "action": "proposed",
        "payload": cleaned,
    }]

    insert = sb.table("agent_tasks").insert({
        "thread_id":          thread_id,
        "type":               "meeting",
        "status":             "proposed",
        "initiator_user_id":  initiator_user,
        "recipient_user_id":  recipient_user,
        "initiator_agent_id": initiator_agent,
        "recipient_agent_id": recipient_agent,
        "payload":            cleaned,
        "history":            history,
    }).execute()

    if not insert.data:
        raise MeetingError("Failed to insert meeting proposal.")

    row = insert.data[0]
    _broadcast("task_created", {
        "task_id": row["id"],
        "thread_id": thread_id,
        "initiator_user_id": initiator_user,
        "recipient_user_id": recipient_user,
        "status": "proposed",
    })
    logger.info(f"[meetings] Created proposal {row['id']} on thread {thread_id}")
    return row


def respond_to_proposal(
    *,
    task_id: str,
    actor_user_id: str,
    action: str,
    edits: dict[str, Any] | None = None,
) -> dict:
    """
    Apply a response action to an existing proposal. `action` ∈
    {accept, counter, decline, cancel}. For counter, `edits` should
    contain the new payload fields (any subset of PAYLOAD_FIELDS).

    Returns the updated row.
    """
    if action not in {"accept", "counter", "decline", "cancel"}:
        raise MeetingError(f"Invalid action '{action}'")

    sb = _supabase()
    existing = sb.table("agent_tasks").select("*").eq("id", task_id).execute()
    if not existing.data:
        raise MeetingError(f"Task {task_id} not found")
    row = existing.data[0]

    if actor_user_id not in (row["initiator_user_id"], row["recipient_user_id"]):
        raise MeetingError("Actor is not a participant of this task.")

    current_status = row["status"]
    key = (current_status, action)
    if key not in ALLOWED_TRANSITIONS:
        raise MeetingError(
            f"Cannot {action} a task in status '{current_status}'. "
            f"Allowed transitions from {current_status}: "
            f"{sorted([a for (s, a) in ALLOWED_TRANSITIONS if s == current_status]) or 'none'}."
        )

    # `accept` and `cancel` must be done by the OTHER party (not the one
    # who last proposed/countered). Enforce that so you can't auto-accept
    # your own proposal.
    if action == "accept":
        # The last history entry tells us who last moved; they can't
        # also be the one accepting.
        last = (row.get("history") or [])[-1] if row.get("history") else None
        if last and last.get("actor_user_id") == actor_user_id:
            raise MeetingError("You can't accept your own proposal — the other side has to.")

    new_status = ALLOWED_TRANSITIONS[key]
    patch: dict[str, Any] = {"status": new_status}

    # Merge counter edits into payload
    if action == "counter":
        if not edits:
            raise MeetingError("counter requires at least one edit to the payload.")
        merged_payload = {**(row.get("payload") or {})}
        for k, v in edits.items():
            if k in PAYLOAD_FIELDS and v not in (None, ""):
                merged_payload[k] = v
        # Re-validate (title/start/end still required)
        patch["payload"] = _clean_payload(merged_payload)

    # Append to audit history
    history_entry: dict[str, Any] = {
        "at": _now_iso(),
        "actor_user_id": actor_user_id,
        "action": action,
    }
    if action == "counter":
        history_entry["payload"] = patch["payload"]
    patch["history"] = _append_history(row.get("history") or [], history_entry)

    # If the user is cancelling a task that was already booked onto both
    # calendars, clean up the calendar events first. We do this BEFORE the
    # DB update so the row still has the event IDs when we read them.
    if action == "cancel" and current_status == "scheduled":
        try:
            unbook_meeting(row)
        except Exception as e:
            # Don't block the cancel on Google API trouble — just log.
            logger.warning(f"[meetings] unbook failed during cancel for {task_id}: {e}")

    updated = sb.table("agent_tasks").update(patch).eq("id", task_id).execute()
    if not updated.data:
        raise MeetingError("Failed to update task.")

    new_row = updated.data[0]
    _broadcast("task_updated", {
        "task_id": task_id,
        "thread_id": new_row["thread_id"],
        "status": new_status,
        "initiator_user_id": new_row["initiator_user_id"],
        "recipient_user_id": new_row["recipient_user_id"],
    })
    logger.info(f"[meetings] Task {task_id} {current_status} -> {new_status} (action={action})")

    # If the accept just landed, kick off the calendar booking synchronously.
    # book_accepted_meeting does its own DB update + broadcast on completion
    # (to 'scheduled' on success, 'book_failed' on failure) so the return
    # value below is the final row the UI should render.
    if action == "accept" and new_status == "accepted":
        try:
            new_row = book_accepted_meeting(new_row)
        except Exception as e:
            logger.error(f"[meetings] booking worker crashed for {task_id}: {e}")
            new_row = _mark_book_failed(task_id, new_row, f"booking worker crashed: {e}")

    return new_row


def list_for_thread(thread_id: str, include_resolved: bool = False) -> list[dict]:
    """Return all tasks on a thread, newest first. By default hides terminal states."""
    sb = _supabase()
    q = sb.table("agent_tasks").select("*").eq("thread_id", thread_id).order("created_at", desc=True)
    if not include_resolved:
        q = q.in_("status", ["proposed", "countered", "accepted"])
    r = q.execute()
    return r.data or []


def list_pending_for_user(user_id: str) -> dict:
    """
    Return a user's open tickets, split into:
      - awaiting_me: the next action is mine
      - awaiting_them: I'm waiting on the other side
    Used by the UI and by the AI when the principal asks "what's on my plate?".
    """
    sb = _supabase()
    # Get all active tickets the user participates in
    r1 = sb.table("agent_tasks").select("*").eq("initiator_user_id", user_id).in_("status", ["proposed", "countered", "accepted"]).execute()
    r2 = sb.table("agent_tasks").select("*").eq("recipient_user_id", user_id).in_("status", ["proposed", "countered", "accepted"]).execute()
    rows = (r1.data or []) + (r2.data or [])

    awaiting_me: list[dict] = []
    awaiting_them: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        # The next move belongs to whichever side did NOT make the last move.
        history = row.get("history") or []
        last_actor = history[-1].get("actor_user_id") if history else None
        if last_actor and last_actor != user_id:
            awaiting_me.append(row)
        else:
            awaiting_them.append(row)
    return {"awaiting_me": awaiting_me, "awaiting_them": awaiting_them}


def get(task_id: str) -> dict | None:
    sb = _supabase()
    r = sb.table("agent_tasks").select("*").eq("id", task_id).execute()
    return r.data[0] if r.data else None


# ── Calendar booking worker ──────────────────────────────────────────
#
# When a task flips to 'accepted', we immediately try to write the
# event onto both users' Google Calendars. Success → status='scheduled'
# and the event IDs are stored on the row. Failure → 'book_failed' with
# the error captured in history so both sides can see what went wrong.
#
# v1 keeps this inline (no queue worker): the extra latency on the
# respond endpoint is small and keeps the code path trivial to reason
# about. If Google's API becomes slow enough to matter, move this into
# a background task triggered off the realtime channel.

def _build_description(row: dict, other_name: str) -> str:
    """Compose the Google Calendar event description from the task payload."""
    payload = row.get("payload") or {}
    parts = [
        f"Scheduled via Zynd AI Network with {other_name}.",
    ]
    if payload.get("description"):
        parts.append("")
        parts.append(payload["description"])
    parts.append("")
    parts.append(f"Task ID: {row['id']}")
    return "\n".join(parts)


def _participant_name(user_id: str) -> str:
    """Best-effort display name for a user via their persona row."""
    sb = _supabase()
    r = (
        sb.table("persona_agents")
        .select("name")
        .eq("user_id", user_id)
        .eq("active", True)
        .execute()
    )
    if r.data and r.data[0].get("name"):
        return r.data[0]["name"]
    return "Zynd user"


def _create_event_for(user_id: str, row: dict, other_name: str) -> dict:
    """
    Create a calendar event for a single participant. Returns the raw
    create_event tool result (has 'success', 'event_id', 'link' OR 'error').
    """
    from mcp.tools.google.calendar import create_event

    payload = row.get("payload") or {}
    return create_event(
        user_id=user_id,
        summary=payload.get("title") or "Meeting",
        start_time=payload.get("start_time") or "",
        end_time=payload.get("end_time") or "",
        description=_build_description(row, other_name),
        location=payload.get("location") or "",
    )


def _delete_event_for(user_id: str, event_id: str) -> dict:
    """Best-effort delete of an event. Failures logged, not raised."""
    from mcp.tools.google.calendar import delete_event
    try:
        return delete_event(user_id=user_id, event_id=event_id)
    except Exception as e:
        logger.warning(f"[meetings] delete_event raised for {event_id} on {user_id}: {e}")
        return {"success": False, "error": str(e)}


def _mark_book_failed(task_id: str, row: dict, reason: str) -> dict:
    """Flip a task to book_failed, log the reason to history, broadcast."""
    sb = _supabase()
    history = _append_history(row.get("history") or [], {
        "at": _now_iso(),
        "action": "book_failed",
        "reason": reason,
    })
    updated = sb.table("agent_tasks").update({
        "status": "book_failed",
        "history": history,
    }).eq("id", task_id).execute()
    new_row = updated.data[0] if updated.data else row
    _broadcast("task_updated", {
        "task_id": task_id,
        "thread_id": new_row["thread_id"],
        "status": "book_failed",
        "initiator_user_id": new_row["initiator_user_id"],
        "recipient_user_id": new_row["recipient_user_id"],
    })
    logger.warning(f"[meetings] Task {task_id} → book_failed: {reason}")
    return new_row


def _mark_scheduled(task_id: str, row: dict, event_ids: dict[str, str]) -> dict:
    """Flip a task to scheduled and store the calendar event IDs."""
    sb = _supabase()
    history = _append_history(row.get("history") or [], {
        "at": _now_iso(),
        "action": "booked",
        "calendar_event_ids": event_ids,
    })
    updated = sb.table("agent_tasks").update({
        "status": "scheduled",
        "history": history,
        "calendar_event_ids": event_ids,
    }).eq("id", task_id).execute()
    new_row = updated.data[0] if updated.data else row
    _broadcast("task_updated", {
        "task_id": task_id,
        "thread_id": new_row["thread_id"],
        "status": "scheduled",
        "initiator_user_id": new_row["initiator_user_id"],
        "recipient_user_id": new_row["recipient_user_id"],
    })
    logger.info(f"[meetings] Task {task_id} scheduled — events {event_ids}")
    return new_row


def book_accepted_meeting(row: dict) -> dict:
    """
    Perform calendar booking for a task that just entered 'accepted'.
    Writes the event onto BOTH participants' primary calendars, stores
    the resulting event IDs on the row, and flips the row to 'scheduled'.

    On failure: rolls back any half-created events and flips to
    'book_failed' with a reason. Returns the final (possibly updated)
    task row so callers can return it straight to the UI.
    """
    task_id = row["id"]

    initiator_id = row["initiator_user_id"]
    recipient_id = row["recipient_user_id"]

    initiator_name = _participant_name(initiator_id)
    recipient_name = _participant_name(recipient_id)

    # Step 1: book on initiator's calendar
    result_a = _create_event_for(initiator_id, row, recipient_name)
    if not result_a.get("success"):
        err = result_a.get("error") or "unknown error"
        return _mark_book_failed(task_id, row, f"initiator calendar: {err}")

    event_id_a = result_a.get("event_id")

    # Step 2: book on recipient's calendar
    result_b = _create_event_for(recipient_id, row, initiator_name)
    if not result_b.get("success"):
        # Roll back the initiator event so we don't leave an orphan.
        if event_id_a:
            _delete_event_for(initiator_id, event_id_a)
        err = result_b.get("error") or "unknown error"
        return _mark_book_failed(task_id, row, f"recipient calendar: {err}")

    event_id_b = result_b.get("event_id")

    return _mark_scheduled(task_id, row, {
        "initiator": event_id_a or "",
        "recipient": event_id_b or "",
    })


def unbook_meeting(row: dict) -> None:
    """
    Best-effort removal of both calendar events for a scheduled task.
    Called from respond_to_proposal when a scheduled task is cancelled.
    Failures are logged but don't block the cancel — leaving a stale
    event in a user's calendar is annoying but not catastrophic, and
    the task's audit history records what happened.
    """
    event_ids = row.get("calendar_event_ids") or {}
    initiator_event = event_ids.get("initiator")
    recipient_event = event_ids.get("recipient")

    if initiator_event:
        r = _delete_event_for(row["initiator_user_id"], initiator_event)
        logger.info(f"[meetings] Unbook initiator event {initiator_event}: {r.get('success')}")
    if recipient_event:
        r = _delete_event_for(row["recipient_user_id"], recipient_event)
        logger.info(f"[meetings] Unbook recipient event {recipient_event}: {r.get('success')}")
