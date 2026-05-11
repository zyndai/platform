"""
Google Calendar MCP Tools

Registered via the ContextAware framework so the agent can:
  - create_event    — add an event to the user's primary calendar
  - list_events     — list upcoming events
  - delete_event    — remove an event by ID

All functions accept a `user_id` to look up stored Google OAuth tokens.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from mcp.tools.google.common import get_google_creds
from googleapiclient.discovery import build
import config


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


def create_event(
    user_id: str,
    summary: str,
    start_time: str,
    end_time: str | None = None,
    description: str = "",
    location: str = "",
    time_zone: str = "UTC",
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

    Returns:
        dict: Created event data or error
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

        print(f"[calendar] Sending request to Google for user {user_id}...")
        event = service.events().insert(calendarId="primary", body=event_body).execute()
        print(f"[calendar] Event created! ID: {event['id']}")
        return {
            "success": True,
            "event_id": event["id"],
            "link": event.get("htmlLink"),
            "summary": summary,
        }
    except Exception as e:
        print(f"[calendar] EXCEPTION in create_event: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def list_events(user_id: str, max_results: int = 10) -> dict:
    """
    List upcoming Google Calendar events.

    Args:
        user_id (str): The platform user ID
        max_results (int): Number of events to fetch

    Returns:
        dict: List of upcoming events
    """
    try:
        service = _get_service(user_id)

        now = datetime.utcnow().isoformat() + "Z"
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

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
        return {"success": False, "error": str(e)}


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
        return {"success": False, "error": str(e)}
