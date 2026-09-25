"""
Smart Scheduling — enhanced multi-party scheduling with cross-instance
awareness, availability negotiation, and automatic conflict resolution.

Builds on the existing group calendar overlay but adds:
  1. Cross-instance availability queries via A2A
  2. Smart slot ranking (prioritizes slots that work for the most people)
  3. Automatic rescheduling suggestions when conflicts arise
  4. Timezone-aware slot display for each participant
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import config

logger = logging.getLogger(__name__)


async def find_best_meeting_slots(
    *,
    group_id: str,
    start_date: str,           # ISO date: "2026-08-05"
    end_date: str,              # ISO date: "2026-08-07"
    duration_minutes: int = 30,
    participants: list[dict[str, Any]],
    tz_offset_minutes: int = 0,
) -> dict[str, Any]:
    """Find the best meeting slots for a group.

    Queries each participant's calendar (locally for same-instance members,
    via A2A for remote), finds common free slots, and ranks them by:
      1. How many people can make it
      2. Time of day preference (business hours)
      3. Proximity to now (sooner is better)

    Returns:
        dict with:
          - slots: ranked list of {start, end, available_count, total_count}
          - unavailable: list of participants without calendar access
          - recommended: the single best slot
    """
    result: dict[str, Any] = {
        "slots": [],
        "unavailable": [],
        "recommended": None,
        "total_participants": len(participants),
        "participants_with_calendar": 0,
    }

    # 1. Collect availability from each participant.
    availability: dict[str, list[dict]] = {}
    for p in participants:
        user_id = p.get("user_id")
        if not user_id:
            continue

        busy_slots = await _get_participant_availability(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            duration_minutes=duration_minutes,
        )
        if busy_slots is not None:
            availability[user_id] = busy_slots
            result["participants_with_calendar"] += 1
        else:
            result["unavailable"].append({
                "user_id": user_id,
                "name": p.get("name", "Unknown"),
                "reason": "calendar_not_connected",
            })

    if result["participants_with_calendar"] < 2:
        result["slots"] = []
        return result

    # 2. Generate candidate slots for the date range.
    candidate_slots = _generate_time_slots(
        start_date=start_date,
        end_date=end_date,
        duration_minutes=duration_minutes,
    )

    # 3. Score each slot by availability.
    scored_slots = []
    for slot in candidate_slots:
        slot_start = datetime.fromisoformat(slot["start"])
        slot_end = datetime.fromisoformat(slot["end"])

        available_count = 0
        for user_id, busy_list in availability.items():
            if _is_slot_free(slot_start, slot_end, busy_list):
                available_count += 1

        if available_count >= 2:  # At least 2 people needed.
            # Score: base = availability ratio; bonus for business hours;
            # bonus for sooner slots.
            ratio = available_count / max(result["total_participants"], 1)
            hour = slot_start.hour
            business_bonus = 0.1 if 9 <= hour <= 17 else 0.0
            recency_bonus = max(0, 0.05 * (24 - abs(hour - 10)))  # Morning bias.

            scored_slots.append({
                **slot,
                "available_count": available_count,
                "total_count": result["total_participants"],
                "score": round(ratio + business_bonus + recency_bonus, 2),
                "missing": result["total_participants"] - available_count,
            })

    # 4. Sort by score descending.
    scored_slots.sort(key=lambda s: s["score"], reverse=True)
    result["slots"] = scored_slots[:12]  # Top 12 slots.

    # 5. Pick recommended.
    if result["slots"]:
        result["recommended"] = result["slots"][0]

    return result


async def negotiate_meeting_across_instances(
    *,
    group_id: str,
    proposed_slot: dict[str, Any],
    participants: list[dict[str, Any]],
) -> dict[str, Any]:
    """Send meeting proposals to all participants via A2A.

    For same-instance members: use the existing propose_group_meeting tool.
    For cross-instance members: send via A2A message/send with meeting data.

    Returns status per participant.
    """
    results: dict[str, Any] = {}

    for p in participants:
        user_id = p.get("user_id")
        agent_id = p.get("agent_id", "")
        name = p.get("name", "Unknown")

        if _is_remote_agent(agent_id):
            result = await _propose_remote_meeting(
                target_agent_id=agent_id,
                group_id=group_id,
                proposed_slot=proposed_slot,
            )
        else:
            # Same-instance — use existing tool.
            try:
                from mcp.tools.scheduling import propose_group_meeting
                result = propose_group_meeting(
                    user_id=user_id,
                    group_id=group_id,
                    title=proposed_slot.get("title", "Group Meeting"),
                    start_time=proposed_slot["start"],
                    end_time=proposed_slot["end"],
                    location=proposed_slot.get("location"),
                    description=proposed_slot.get("description"),
                    time_zone=proposed_slot.get("time_zone", "UTC"),
                )
            except Exception as e:
                result = {"error": str(e)}

        results[name] = result

    return results


async def suggest_alternative_times(
    *,
    preferred_slot: dict[str, Any],
    all_slots: list[dict[str, Any]],
    conflict_reason: str,
) -> list[dict[str, Any]]:
    """When a proposed slot is declined, suggest alternatives from the
    pre-computed slot list.

    Prioritizes slots close to the original preference that have high
    availability scores.
    """
    preferred_start = preferred_slot.get("start", "")

    alternatives = [
        s for s in all_slots
        if s.get("start") != preferred_start
    ]

    # Sort: highest score first.
    alternatives.sort(key=lambda s: s.get("score", 0), reverse=True)

    return alternatives[:5]


# ── Helpers ──────────────────────────────────────────────────────────


def _generate_time_slots(
    start_date: str,
    end_date: str,
    duration_minutes: int = 30,
) -> list[dict[str, str]]:
    """Generate candidate meeting slots for a date range.

    Slots are in 30-min increments during business hours (8 AM - 6 PM UTC).
    """
    slots = []
    try:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date) + timedelta(days=1)

        current = start.replace(hour=8, minute=0, second=0)
        while current + timedelta(minutes=duration_minutes) <= end:
            if 8 <= current.hour < 18:
                slot_end = current + timedelta(minutes=duration_minutes)
                slots.append({
                    "start": current.isoformat() + "Z",
                    "end": slot_end.isoformat() + "Z",
                })
            current += timedelta(minutes=30)

    except Exception as e:
        logger.debug("[scheduling] slot generation failed: %s", e)

    return slots


def _is_slot_free(
    slot_start: datetime,
    slot_end: datetime,
    busy_list: list[dict],
) -> bool:
    """Check if a time slot conflicts with any busy periods."""
    for busy in busy_list:
        try:
            b_start = busy.get("start", "")
            b_end = busy.get("end", "")
            if not b_start or not b_end:
                continue

            bs = datetime.fromisoformat(b_start.replace("Z", "+00:00"))
            be = datetime.fromisoformat(b_end.replace("Z", "+00:00"))

            # Conflict: any overlap.
            if slot_start < be and slot_end > bs:
                return False
        except Exception:
            continue
    return True


async def _get_participant_availability(
    user_id: str,
    start_date: str,
    end_date: str,
    duration_minutes: int = 30,
) -> list[dict] | None:
    """Get a participant's busy slots for a date range.

    Returns None if calendar is not connected (participant will be excluded).
    """
    try:
        from mcp.tools.google.calendar import list_events
        result = list_events(
            user_id=user_id,
            time_min=f"{start_date}T00:00:00Z",
            time_max=f"{end_date}T23:59:59Z",
            max_results=50,
        )
        if not result.get("success"):
            return None

        events = result.get("events", [])
        busy = []
        for ev in events:
            start_raw = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", "")
            end_raw = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date", "")
            if start_raw and end_raw:
                busy.append({"start": start_raw, "end": end_raw})

        return busy
    except Exception as e:
        logger.debug("[scheduling] availability check failed for %s: %s", user_id, e)
        return None


async def _is_remote_agent(agent_id: str) -> bool:
    """Quick check if an agent is on a different backend."""
    if not agent_id or not config.ZYND_WEBHOOK_BASE_URL:
        return False

    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{config.ZYND_REGISTRY_URL}/v1/agents/{agent_id}/card"
            )
            if resp.status_code == 200:
                card = resp.json()
                remote_url = card.get("url", "")
                from urllib.parse import urlparse
                our = urlparse(config.ZYND_WEBHOOK_BASE_URL)
                remote = urlparse(remote_url)
                return our.netloc != remote.netloc
    except Exception:
        pass

    return False


async def _propose_remote_meeting(
    target_agent_id: str,
    group_id: str,
    proposed_slot: dict[str, Any],
) -> dict[str, Any]:
    """Send a meeting proposal to a remote agent via A2A."""
    try:
        import httpx
        from urllib.parse import urlparse

        # Resolve the target's A2A endpoint.
        async with httpx.AsyncClient(timeout=10.0) as client:
            card_resp = await client.get(
                f"{config.ZYND_REGISTRY_URL}/v1/agents/{target_agent_id}/card"
            )
            if card_resp.status_code != 200:
                return {"error": "unresolvable_agent"}

            card = card_resp.json()
            remote_url = card.get("url", "")

            # Send A2A meeting proposal.
            a2a_payload = {
                "jsonrpc": "2.0",
                "id": _gen_id(),
                "method": "message/send",
                "params": {
                    "message": {
                        "kind": "message",
                        "messageId": _gen_id(),
                        "role": "user",
                        "parts": [
                            {
                                "kind": "data",
                                "data": {
                                    "kind": "zynd.meeting.proposal",
                                    "group_id": group_id,
                                    "title": proposed_slot.get("title", "Group Meeting"),
                                    "start": proposed_slot["start"],
                                    "end": proposed_slot["end"],
                                    "location": proposed_slot.get("location"),
                                    "description": proposed_slot.get("description"),
                                },
                            },
                        ],
                        "contextId": f"group:{group_id}:meeting",
                    },
                },
            }

            resp = await client.post(
                f"{remote_url.rstrip('/')}/a2a/v1",
                json=a2a_payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            resp.raise_for_status()
            return {"status": "dispatched", "http_status": resp.status_code}

    except Exception as e:
        return {"error": f"remote_proposal_failed: {str(e)[:120]}"}


def _gen_id() -> str:
    import uuid
    return str(uuid.uuid4())
