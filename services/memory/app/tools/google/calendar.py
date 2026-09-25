
import asyncio
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build

from app.tools.google.common import get_google_creds


def _parse_iso(value: str) -> datetime:
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _get_service(user_id: str):
    creds = get_google_creds(user_id=user_id)
    return build("calendar", "v3", credentials=creds)


async def create_calendar_event(
    user_id: str,
    summary: str,
    start_time: str,
    end_time: str | None = None,
    description: str = "",
    location: str = "",
    time_zone: str = "UTC",
) -> dict:
    def _create() -> dict:
        try:
            service = _get_service(user_id)
            start_dt = _parse_iso(start_time)
            if end_time:
                end_dt = _parse_iso(end_time)
            else:
                end_dt = start_dt + timedelta(hours=1)
            event_body = {
                "summary": summary,
                "description": description,
                "location": location,
                "start": {"dateTime": start_dt.isoformat(), "timeZone": time_zone},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": time_zone},
            }
            event = service.events().insert(calendarId="primary", body=event_body).execute()
            return {
                "success": True,
                "event_id": event["id"],
                "link": event.get("htmlLink"),
                "summary": summary,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_create)


async def list_calendar_events(user_id: str, max_results: int = 10) -> dict:
    def _list() -> dict:
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

    return await asyncio.to_thread(_list)


async def delete_calendar_event(user_id: str, event_id: str) -> dict:
    def _delete() -> dict:
        try:
            service = _get_service(user_id)
            service.events().delete(calendarId="primary", eventId=event_id).execute()
            return {"success": True, "deleted": event_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_delete)
