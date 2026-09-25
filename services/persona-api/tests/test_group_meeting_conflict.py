"""
Regression test: group-meeting creation used to call
`service.events().insert()` directly with no conflict check at all, unlike
the single-user `create_event` path — so a group meeting could double-book
the asker's calendar with no warning, even though the 1:1 flow already
warned about conflicts. `_create_event_with_attendees` now reuses the same
`_find_conflicts`/`_suggest_free_slots` helpers and gates the insert behind
`force`, exactly like `create_event`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from api.groups import _create_event_with_attendees


def _common_kwargs():
    return dict(
        user_id="u1",
        summary="Sync",
        start_time="2026-05-15T19:00:00Z",
        end_time="2026-05-15T19:30:00Z",
        description="",
        location="",
        time_zone="UTC",
        attendees=[{"email": "a@example.com"}],
    )


def test_conflicting_group_meeting_is_not_created():
    fake_service = MagicMock()
    conflict = [{
        "id": "evt1",
        "summary": "Existing meeting",
        "start": "2026-05-15T19:00:00Z",
        "end": "2026-05-15T19:30:00Z",
    }]

    with patch("mcp.tools.google.calendar._get_service", return_value=fake_service), \
         patch("mcp.tools.google.calendar._find_conflicts", return_value=conflict) as mock_find, \
         patch("mcp.tools.google.calendar._suggest_free_slots", return_value=[]):
        result = _create_event_with_attendees(**_common_kwargs())

    assert result["success"] is False
    assert result["conflict"] is True
    assert result["conflicting_events"] == conflict
    # No event should have been inserted.
    fake_service.events.return_value.insert.assert_not_called()
    mock_find.assert_called_once()


def test_force_skips_conflict_check_and_creates_event():
    fake_service = MagicMock()
    fake_service.events.return_value.insert.return_value.execute.return_value = {
        "id": "evt2",
        "htmlLink": "https://calendar.google.com/evt2",
    }

    with patch("mcp.tools.google.calendar._get_service", return_value=fake_service), \
         patch("mcp.tools.google.calendar._find_conflicts") as mock_find:
        result = _create_event_with_attendees(**_common_kwargs(), force=True)

    assert result["success"] is True
    assert result["event"]["id"] == "evt2"
    mock_find.assert_not_called()
    fake_service.events.return_value.insert.assert_called_once()


def test_no_conflict_creates_event_normally():
    fake_service = MagicMock()
    fake_service.events.return_value.insert.return_value.execute.return_value = {
        "id": "evt3",
        "htmlLink": "https://calendar.google.com/evt3",
    }

    with patch("mcp.tools.google.calendar._get_service", return_value=fake_service), \
         patch("mcp.tools.google.calendar._find_conflicts", return_value=[]), \
         patch("mcp.tools.google.calendar._suggest_free_slots", return_value=[]):
        result = _create_event_with_attendees(**_common_kwargs())

    assert result["success"] is True
    assert result["event"]["id"] == "evt3"
