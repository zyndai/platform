
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from supabase import create_client, Client

from app.config import settings
from app.tools.google.calendar import create_calendar_event, delete_calendar_event

logger = logging.getLogger(__name__)

_supabase_client: Client | None = None


def _supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _supabase_client


ALLOWED_TRANSITIONS: dict[tuple[str, str], str] = {
    ("proposed", "accept"): "accepted",
    ("proposed", "counter"): "countered",
    ("proposed", "decline"): "declined",
    ("proposed", "cancel"): "cancelled",
    ("countered", "accept"): "accepted",
    ("countered", "counter"): "countered",
    ("countered", "decline"): "declined",
    ("countered", "cancel"): "cancelled",
    ("accepted", "cancel"): "cancelled",
    ("scheduled", "cancel"): "cancelled",
    ("book_failed", "cancel"): "cancelled",
    ("book_failed", "accept"): "accepted",
}

PAYLOAD_FIELDS = ("title", "start_time", "end_time", "location", "description")


class MeetingError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_participants(sb, thread_id: str) -> dict[str, str]:
    t = sb.table("dm_threads").select("*").eq("id", thread_id).execute()
    if not t.data:
        raise MeetingError(f"Thread {thread_id} not found")
    row = t.data[0]
    initiator_agent_id = row["initiator_id"]
    receiver_agent_id = row["receiver_id"]

    def _user_for_agent(agent_id: str) -> str | None:
        r = sb.table("persona_agents").select("user_id").eq("agent_id", agent_id).execute()
        return r.data[0]["user_id"] if r.data else None

    initiator_user_id = _user_for_agent(initiator_agent_id)
    receiver_user_id = _user_for_agent(receiver_agent_id)

    if not initiator_user_id or not receiver_user_id:
        raise MeetingError(
            f"Both participants must be on this platform (thread {thread_id})"
        )
    return {
        "initiator_user_id": initiator_user_id,
        "initiator_agent_id": initiator_agent_id,
        "receiver_user_id": receiver_user_id,
        "receiver_agent_id": receiver_agent_id,
    }


def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
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


async def create_proposal(*, thread_id: str, actor_user_id: str, payload: dict[str, Any]) -> dict:
    sb = _supabase()
    participants = _resolve_participants(sb, thread_id)

    if actor_user_id not in (participants["initiator_user_id"], participants["receiver_user_id"]):
        raise MeetingError("Actor is not a participant of this thread.")

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
            f"(task_id={existing_row['id']}, status={existing_row['status']})."
        )

    cleaned = _clean_payload(payload)

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
        "at": _now_iso(), "actor_user_id": actor_user_id,
        "actor_agent_id": initiator_agent, "action": "proposed", "payload": cleaned,
    }]

    insert = sb.table("agent_tasks").insert({
        "thread_id": thread_id, "type": "meeting", "status": "proposed",
        "initiator_user_id": initiator_user, "recipient_user_id": recipient_user,
        "initiator_agent_id": initiator_agent, "recipient_agent_id": recipient_agent,
        "payload": cleaned, "history": history,
    }).execute()

    if not insert.data:
        raise MeetingError("Failed to insert meeting proposal.")
    logger.info(f"[meetings] Created proposal {insert.data[0]['id']} on thread {thread_id}")
    return insert.data[0]


async def respond_to_proposal(*, task_id: str, actor_user_id: str, action: str,
                               edits: dict[str, Any] | None = None) -> dict:
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
        raise MeetingError(f"Cannot {action} a task in status '{current_status}'.")

    if action == "accept":
        last = (row.get("history") or [])[-1] if row.get("history") else None
        if last and last.get("actor_user_id") == actor_user_id:
            raise MeetingError("You can't accept your own proposal — the other side has to.")

    new_status = ALLOWED_TRANSITIONS[key]
    patch: dict[str, Any] = {"status": new_status}

    if action == "counter":
        if not edits:
            raise MeetingError("counter requires at least one edit to the payload.")
        merged_payload = {**(row.get("payload") or {})}
        for k, v in edits.items():
            if k in PAYLOAD_FIELDS and v not in (None, ""):
                merged_payload[k] = v
        patch["payload"] = _clean_payload(merged_payload)

    history_entry: dict[str, Any] = {"at": _now_iso(), "actor_user_id": actor_user_id, "action": action}
    if action == "counter":
        history_entry["payload"] = patch["payload"]
    patch["history"] = _append_history(row.get("history") or [], history_entry)

    if action == "cancel" and current_status == "scheduled":
        try:
            await unbook_meeting(row)
        except Exception as e:
            logger.warning(f"[meetings] unbook failed during cancel for {task_id}: {e}")

    updated = sb.table("agent_tasks").update(patch).eq("id", task_id).execute()
    if not updated.data:
        raise MeetingError("Failed to update task.")

    new_row = updated.data[0]
    logger.info(f"[meetings] Task {task_id} {current_status} -> {new_status}")

    if action == "accept" and new_status == "accepted":
        try:
            new_row = await book_accepted_meeting(new_row)
        except Exception as e:
            logger.error(f"[meetings] booking worker crashed for {task_id}: {e}")
            new_row = await _mark_book_failed(task_id, new_row, str(e))

    return new_row


def list_for_thread(thread_id: str, include_resolved: bool = False) -> list[dict]:
    sb = _supabase()
    q = sb.table("agent_tasks").select("*").eq("thread_id", thread_id).order("created_at", desc=True)
    if not include_resolved:
        q = q.in_("status", ["proposed", "countered", "accepted"])
    r = q.execute()
    return r.data or []


def list_pending_for_user(user_id: str) -> dict:
    sb = _supabase()
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


def _build_description(row: dict, other_name: str) -> str:
    payload = row.get("payload") or {}
    parts = [f"Scheduled via Zynd AI Network with {other_name}."]
    if payload.get("description"):
        parts.append("")
        parts.append(payload["description"])
    parts.append("")
    parts.append(f"Task ID: {row['id']}")
    return "\n".join(parts)


def _participant_name(user_id: str) -> str:
    sb = _supabase()
    r = sb.table("persona_agents").select("name").eq("user_id", user_id).eq("active", True).execute()
    if r.data and r.data[0].get("name"):
        return r.data[0]["name"]
    return "Zynd user"


async def _create_event_for(user_id: str, row: dict, other_name: str) -> dict:
    payload = row.get("payload") or {}
    return await create_calendar_event(
        user_id=user_id,
        summary=payload.get("title") or "Meeting",
        start_time=payload.get("start_time") or "",
        end_time=payload.get("end_time") or "",
        description=_build_description(row, other_name),
        location=payload.get("location") or "",
    )


async def _delete_event_for(user_id: str, event_id: str) -> dict:
    try:
        return await delete_calendar_event(user_id=user_id, event_id=event_id)
    except Exception as e:
        logger.warning(f"[meetings] delete_event raised for {event_id} on {user_id}: {e}")
        return {"success": False, "error": str(e)}


async def _mark_book_failed(task_id: str, row: dict, reason: str) -> dict:
    sb = _supabase()
    history = _append_history(row.get("history") or [], {
        "at": _now_iso(), "action": "book_failed", "reason": reason,
    })
    updated = sb.table("agent_tasks").update({"status": "book_failed", "history": history}).eq("id", task_id).execute()
    new_row = updated.data[0] if updated.data else row
    logger.warning(f"[meetings] Task {task_id} -> book_failed: {reason}")
    return new_row


async def _mark_scheduled(task_id: str, row: dict, event_ids: dict[str, str]) -> dict:
    sb = _supabase()
    history = _append_history(row.get("history") or [], {
        "at": _now_iso(), "action": "booked", "calendar_event_ids": event_ids,
    })
    updated = sb.table("agent_tasks").update({
        "status": "scheduled", "history": history, "calendar_event_ids": event_ids,
    }).eq("id", task_id).execute()
    new_row = updated.data[0] if updated.data else row
    logger.info(f"[meetings] Task {task_id} scheduled — events {event_ids}")
    return new_row


async def book_accepted_meeting(row: dict) -> dict:
    task_id = row["id"]
    initiator_id = row["initiator_user_id"]
    recipient_id = row["recipient_user_id"]
    initiator_name = _participant_name(initiator_id)
    recipient_name = _participant_name(recipient_id)

    result_a = await _create_event_for(initiator_id, row, recipient_name)
    if not result_a.get("success"):
        return await _mark_book_failed(task_id, row, f"initiator calendar: {result_a.get('error') or 'unknown'}")

    event_id_a = result_a.get("event_id")

    result_b = await _create_event_for(recipient_id, row, initiator_name)
    if not result_b.get("success"):
        if event_id_a:
            await _delete_event_for(initiator_id, event_id_a)
        return await _mark_book_failed(task_id, row, f"recipient calendar: {result_b.get('error') or 'unknown'}")

    event_id_b = result_b.get("event_id")
    return await _mark_scheduled(task_id, row, {"initiator": event_id_a or "", "recipient": event_id_b or ""})


async def unbook_meeting(row: dict) -> None:
    event_ids = row.get("calendar_event_ids") or {}
    initiator_event = event_ids.get("initiator")
    recipient_event = event_ids.get("recipient")
    if initiator_event:
        r = await _delete_event_for(row["initiator_user_id"], initiator_event)
        logger.info(f"[meetings] Unbook initiator event {initiator_event}: {r.get('success')}")
    if recipient_event:
        r = await _delete_event_for(row["recipient_user_id"], recipient_event)
        logger.info(f"[meetings] Unbook recipient event {recipient_event}: {r.get('success')}")
