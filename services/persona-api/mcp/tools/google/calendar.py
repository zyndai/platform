"""
Google Calendar MCP Tools

Registered via the ContextAware framework so the agent can:
  - create_event    — add an event to the user's primary calendar
  - list_events     — list upcoming events
  - delete_event    — remove an event by ID

All functions accept a `user_id` to look up stored Google OAuth tokens.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from mcp.tools.google.common import get_google_creds
from googleapiclient.discovery import build
import config
from mcp.tools.error_utils import friendly_error

def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp the LLM (or scheduler) gave us.

    Python 3.10's ``datetime.fromisoformat`` doesn't accept the trailing
    ``Z`` (UTC) suffix that's the standard wire format we get from the
    orchestrator and Google APIs — 3.11+ does. We normalize ``Z`` → ``+00:00``
    so 3.10 parses cleanly. Naive timestamps are assumed UTC since every
    caller in this codebase serializes UTC.
    """
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def _get_service(user_id: str):
    """Build a Google Calendar API service from stored tokens."""
    print(f"[calendar] Building service for user {user_id}")
    creds = get_google_creds(user_id=user_id)

    print(f"[calendar] Using access token: {creds.token[:10]}...")
    service = build("calendar", "v3", credentials=creds)
    print(f"[calendar] Service built successfully for {user_id}")
    return service

def _event_time_range(e: dict) -> tuple[datetime, datetime] | None:
    """Parse an event's (start, end) as timezone-aware datetimes.

    Handles both timed events (`dateTime`) and all-day events (`date`,
    which has no time component — treated as spanning the whole day) so
    conflict detection and slot suggestion don't silently ignore all-day
    events.
    """
    start_raw = e.get("start", {}).get("dateTime")
    end_raw = e.get("end", {}).get("dateTime")
    if start_raw and end_raw:
        try:
            return _parse_iso(start_raw), _parse_iso(end_raw)
        except Exception:
            return None
    start_date = e.get("start", {}).get("date")
    end_date = e.get("end", {}).get("date")
    if start_date and end_date:
        try:
            start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
            return start_dt, end_dt
        except Exception:
            return None
    return None

def _business_hour_ok(dt: datetime, time_zone: str) -> bool:
    """True if `dt` falls within 9am–6pm in the given IANA timezone."""
    try:
        from zoneinfo import ZoneInfo
        local = dt.astimezone(ZoneInfo(time_zone))
    except Exception:
        local = dt
    return 9 <= local.hour < 18

def _find_conflicts(service, start_dt: datetime, end_dt: datetime) -> list[dict]:
    """Existing primary-calendar events overlapping [start_dt, end_dt).

    Google's timeMin/timeMax are exactly the overlap test we want here:
    timeMin filters to events ending after it, timeMax to events starting
    before it — together, any event returned overlaps the window.
    """
    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=start_dt.isoformat(),
            timeMax=end_dt.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    conflicts = []
    for e in events_result.get("items", []):
        rng = _event_time_range(e)
        if not rng:
            continue
        conflicts.append({
            "id": e["id"],
            "summary": e.get("summary", "(No title)"),
            "start": e["start"].get("dateTime") or e["start"].get("date"),
            "end": e["end"].get("dateTime") or e["end"].get("date"),
        })
    return conflicts

def _suggest_free_slots(
    service, start_dt: datetime, end_dt: datetime, time_zone: str, max_suggestions: int = 3,
) -> list[dict]:
    """Find up to `max_suggestions` free slots of the same duration as the
    requested (but conflicting) one — 30-minute steps within business hours
    (9am–6pm local), searching forward up to 2 days from the requested start.
    """
    duration = end_dt - start_dt
    search_limit = start_dt + timedelta(days=2)

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=start_dt.isoformat(),
            timeMax=search_limit.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    busy: list[tuple[datetime, datetime]] = []
    for e in events_result.get("items", []):
        rng = _event_time_range(e)
        if rng:
            busy.append(rng)

    suggestions: list[dict] = []
    candidate = start_dt
    while candidate < search_limit and len(suggestions) < max_suggestions:
        candidate_end = candidate + duration
        if _business_hour_ok(candidate, time_zone) and not any(
            candidate < b_end and candidate_end > b_start for b_start, b_end in busy
        ):
            suggestions.append({
                "start": candidate.isoformat(),
                "end": candidate_end.isoformat(),
            })
        candidate += timedelta(minutes=30)
    return suggestions

def create_event(
    user_id: str,
    summary: str,
    start_time: str,
    end_time: str | None = None,
    description: str = "",
    location: str = "",
    time_zone: str = "UTC",
    # Bare `list[str]`, not `list[str] | None` — ContextAware._generate_schema
    # reads `annotation.__name__` for the JSON-schema type, and a `| None`
    # union has no `__name__`, so it'd silently fall back to "string" and
    # break the LLM's tool call.
    attendees: list[str] = None,
    force: bool = False,
) -> dict:
    """
    Create a Google Calendar event.

    Args:
        user_id (str): The platform user ID
        summary (str): Event title
        start_time (str): ISO 8601 datetime string (e.g. 2026-04-01T10:00:00).
            If naive (no offset), it is interpreted in `time_zone`.
        end_time (str): ISO 8601 end time (defaults to start + 1 hour)
        description (str): Event description
        location (str): Event location
        time_zone (str): IANA timezone name (e.g. "America/Los_Angeles").
            Defaults to UTC. The orchestrator passes the user's browser
            timezone so events land at the wall-clock time they meant.
        attendees (list[str]): Guest email addresses to invite. Google sends
            each one a calendar invite automatically.
        force (bool): Skip the conflict check and create the event even if
            it overlaps an existing one. Only set this when the principal
            has explicitly said to double-book / book it anyway after
            seeing the conflict.

    Returns:
        dict: Created event data, or on a conflict (and force=False):
              {"success": False, "conflict": True, "conflicting_events":
              [...], "suggested_times": [...], "error": "..."}
    """
    try:
        print(f"[calendar] Creating event for {user_id}: {summary} at {start_time} ({time_zone})")
        service = _get_service(user_id)

        # Parse start time and default end to +1 hour. _parse_iso accepts
        # the `Z` suffix that 3.10's stdlib rejects — the LLM tends to
        # emit `2026-05-20T14:00:00Z`.
        start_dt = _parse_iso(start_time)
        if end_time:
            end_dt = _parse_iso(end_time)
        else:
            end_dt = start_dt + timedelta(hours=1)

        if not force:
            conflicts = _find_conflicts(service, start_dt, end_dt)
            if conflicts:
                suggested_times = _suggest_free_slots(service, start_dt, end_dt, time_zone)
                conflict_desc = "; ".join(
                    f"\"{c['summary']}\" ({c['start']}–{c['end']})" for c in conflicts
                )
                print(f"[calendar] Conflict detected for {user_id}: {conflict_desc}")
                return {
                    "success": False,
                    "conflict": True,
                    "conflicting_events": conflicts,
                    "suggested_times": suggested_times,
                    "error": (
                        f"Requested time overlaps existing event(s): {conflict_desc}. "
                        "Present the conflict and the suggested_times to the principal "
                        "instead of creating this event. If they explicitly want it "
                        "anyway, call create_calendar_event again with force=true."
                    ),
                }

        event_body = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": time_zone,
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": time_zone,
            },
        }
        if attendees:
            event_body["attendees"] = [{"email": e} for e in attendees if e]

        print(f"[calendar] Sending request to Google for user {user_id}...")
        # sendUpdates="all" is what actually triggers Google to email the
        # invite — without it, attendees are added to the event silently.
        event = service.events().insert(
            calendarId="primary", body=event_body, sendUpdates="all"
        ).execute()
        print(f"[calendar] Event created! ID: {event['id']}")
        return {
            "success": True,
            "event_id": event["id"],
            "link": event.get("htmlLink"),
            "summary": summary,
            "attendees": [a["email"] for a in event.get("attendees", [])],
        }
    except Exception as e:
        print(f"[calendar] EXCEPTION in create_event: {str(e)}")
        import traceback
        traceback.print_exc()
        return friendly_error("create the calendar event", e)

def list_events(
    user_id: str,
    max_results: int = 10,
    time_min: str | None = None,
    time_max: str | None = None,
) -> dict:
    """
    List Google Calendar events.

    Args:
        user_id (str): The platform user ID
        max_results (int): Number of events to fetch
        time_min (str): ISO 8601 lower bound. Defaults to now (i.e. only
            upcoming events) when omitted.
        time_max (str): ISO 8601 upper bound. Omitted entirely means no
            upper bound.

    Returns:
        dict: List of events in the range
    """
    try:
        service = _get_service(user_id)

        list_kwargs: dict = {
            "calendarId": "primary",
            "timeMin": time_min or (datetime.utcnow().isoformat() + "Z"),
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_max:
            list_kwargs["timeMax"] = time_max
        events_result = service.events().list(**list_kwargs).execute()

        events = events_result.get("items", [])
        return {
            "success": True,
            "events": [
                {
                    "id": e["id"],
                    "summary": e.get("summary", "(No title)"),
                    "start": e["start"].get("dateTime", e["start"].get("date")),
                    "end": e["end"].get("dateTime", e["end"].get("date")),
                }
                for e in events
            ],
        }
    except Exception as e:
        return friendly_error("read your calendar", e)

def delete_event(user_id: str, event_id: str) -> dict:
    """
    Delete a Google Calendar event.

    Args:
        user_id (str): The platform user ID
        event_id (str): The event ID to delete

    Returns:
        dict: Deletion result
    """
    try:
        service = _get_service(user_id)
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return {"success": True, "deleted": event_id}
    except Exception as e:
        return friendly_error("delete the calendar event", e)
