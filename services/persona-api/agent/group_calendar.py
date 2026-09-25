"""
Group calendar helpers — free/busy aggregation across members and the
slot-finding logic that powers the Schedule tab's "everyone is free"
list.

Privacy model
-------------
We use Google Calendar's `freebusy.query` API, NOT `events.list`, so the
only information that ever crosses a member boundary is "busy from X to
Y" — no event titles, attendees, or descriptions. Each member's busy
blocks are read with that member's own Google credentials; we never
touch a calendar the user hasn't authorized.

A member without Google connected is treated as "no availability data";
the UI surfaces this explicitly rather than silently treating them as
always-free.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Iterable

logger = logging.getLogger(__name__)


@dataclass
class BusyBlock:
    start: datetime  # UTC
    end: datetime    # UTC

    def to_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass
class MemberAvailability:
    user_id: str
    display_name: str
    has_calendar: bool
    busy: list[BusyBlock]
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "display_name": self.display_name,
            "has_calendar": self.has_calendar,
            "busy": [b.to_dict() for b in self.busy],
            "error": self.error,
        }


def _parse_iso_utc(value: str) -> datetime:
    """Lenient ISO 8601 parse that lands at UTC."""
    s = value.rstrip("Z")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fetch_one_member_freebusy(
    user_id: str,
    start: datetime,
    end: datetime,
) -> tuple[bool, list[BusyBlock], str | None]:
    """
    Call Google Calendar `freebusy.query` for one user. Returns
    (has_calendar, busy_blocks, error). On any failure short of "no
    credentials at all", we treat the member as having no calendar so
    the UI doesn't claim phantom free time.
    """
    try:
        # Import inside the function — the calendar module pulls in
        # google-api-client which we don't want to require at import
        # time for users with no Google integration.
        from mcp.tools.google.calendar import _get_service
        service = _get_service(user_id)
    except Exception as e:
        return False, [], f"no_calendar: {e}"

    body = {
        "timeMin": start.astimezone(timezone.utc).isoformat(),
        "timeMax": end.astimezone(timezone.utc).isoformat(),
        "items": [{"id": "primary"}],
    }
    try:
        resp = service.freebusy().query(body=body).execute()
    except Exception as e:
        logger.warning(f"[group-calendar] freebusy failed for {user_id}: {e}")
        return False, [], str(e)

    cal = (resp.get("calendars") or {}).get("primary") or {}
    raw_busy = cal.get("busy") or []
    busy: list[BusyBlock] = []
    for b in raw_busy:
        try:
            busy.append(BusyBlock(
                start=_parse_iso_utc(b["start"]),
                end=_parse_iso_utc(b["end"]),
            ))
        except Exception:
            continue
    return True, busy, None


async def aggregate_member_availability(
    members: list[dict],
    start: datetime,
    end: datetime,
) -> list[MemberAvailability]:
    """
    Fan out to each member's calendar concurrently and collect busy
    blocks. `members` rows must carry `user_id` and `display_name`.

    Each call is wrapped in `asyncio.to_thread` because the Google
    client is sync; concurrent across members so the response time is
    O(slowest member) rather than O(sum).
    """
    async def _one(m: dict) -> MemberAvailability:
        has_cal, blocks, err = await asyncio.to_thread(
            _fetch_one_member_freebusy, m["user_id"], start, end
        )
        return MemberAvailability(
            user_id=m["user_id"],
            display_name=m.get("display_name") or "Someone",
            has_calendar=has_cal,
            busy=blocks,
            error=err,
        )

    return await asyncio.gather(*[_one(m) for m in members])


# ── Slot finder ─────────────────────────────────────────────────────────
@dataclass
class CommonSlot:
    start: datetime
    end: datetime
    participants: list[str]  # user_ids that are free in this slot

    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "participants": self.participants,
        }


def find_common_slots(
    availabilities: list[MemberAvailability],
    *,
    window_start: datetime,
    window_end: datetime,
    duration_minutes: int = 30,
    step_minutes: int = 30,
    business_hours: tuple[int, int] = (9, 18),  # 9am–6pm local-ish
    weekdays_only: bool = True,
    require_calendar: bool = True,
    max_slots: int = 12,
    viewer_tz_offset_minutes: int = 0,
) -> list[CommonSlot]:
    """
    Walk the [window_start, window_end] range in `step_minutes` increments
    and return slots of length `duration_minutes` where every eligible
    member is free.

    * ``business_hours`` is interpreted in the viewer's local time via
      ``viewer_tz_offset_minutes`` — pass the browser's
      ``-new Date().getTimezoneOffset()`` so 9am-6pm means 9am-6pm for the
      person looking at the page.
    * ``require_calendar=True`` means members without a connected calendar
      are SKIPPED entirely (excluded from the participants list of any
      returned slot). False would include them as "presumed free", which
      is misleading; we keep the conservative default.
    * Returns at most ``max_slots`` slots so the UI stays scannable.
    """
    eligible = [a for a in availabilities if a.has_calendar] if require_calendar else availabilities
    if not eligible:
        return []

    def _is_busy(av: MemberAvailability, slot_start: datetime, slot_end: datetime) -> bool:
        for b in av.busy:
            if b.start < slot_end and b.end > slot_start:
                return True
        return False

    duration = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=step_minutes)
    tz_offset = timedelta(minutes=viewer_tz_offset_minutes)
    biz_start_h, biz_end_h = business_hours

    out: list[CommonSlot] = []
    cursor = window_start
    while cursor + duration <= window_end and len(out) < max_slots:
        slot_end = cursor + duration
        # Project into viewer-local time for the business-hours / weekday
        # gates so a UTC cursor at 02:00 doesn't accidentally count as
        # "lunchtime" for a Pacific user.
        local = cursor + tz_offset
        local_h = local.hour
        local_weekday = local.weekday()  # 0=Mon, 6=Sun
        if weekdays_only and local_weekday >= 5:
            cursor += step
            continue
        if local_h < biz_start_h or (local_h + duration_minutes / 60) > biz_end_h:
            cursor += step
            continue

        free_participants = [
            a.user_id for a in eligible if not _is_busy(a, cursor, slot_end)
        ]
        if len(free_participants) == len(eligible):
            out.append(CommonSlot(start=cursor, end=slot_end, participants=free_participants))
        cursor += step

    return out
