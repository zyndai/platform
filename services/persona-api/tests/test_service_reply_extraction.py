"""
Tests for extracting replies from A2A service-call Tasks.

Agents on the network reply in two shapes: a TextPart (plain or
JSON-encoded string), or a DataPart carrying a structured object
(competitor-monitor returns ``{"mode": "chat", "response": "…"}``). The
DataPart shape was previously dropped — the call reported ``empty_result``
even though the agent replied. These lock in both shapes.
"""

from __future__ import annotations

from mcp.tools.zynd_services import (
    _extract_reply_from_task,
    classify_task_result,
)


def _task(parts):
    return {"artifacts": [{"parts": parts}], "status": {"state": "completed"}}


def test_text_part_reply():
    text, structured = _extract_reply_from_task(_task([{"kind": "text", "text": "Hello"}]))
    assert text == "Hello"
    assert structured is None


def test_json_encoded_text_part_becomes_structured():
    text, structured = _extract_reply_from_task(
        _task([{"kind": "text", "text": '{"translated": "bonjour"}'}])
    )
    assert structured == {"translated": "bonjour"}


def test_data_part_reply_pulls_response_field():
    # competitor-monitor's shape — was previously lost.
    text, structured = _extract_reply_from_task(
        _task([{"kind": "data", "data": {"mode": "chat", "response": "Understood!"}}])
    )
    assert text == "Understood!"
    assert structured == {"mode": "chat", "response": "Understood!"}


def test_data_part_only_structured_is_not_empty():
    text, structured = _extract_reply_from_task(
        _task([{"kind": "data", "data": {"count": 5, "items": [1, 2]}}])
    )
    assert text == ""  # no readable field
    assert structured == {"count": 5, "items": [1, 2]}
    # A completed task with structured-but-no-text must classify as success.
    status, _ = classify_task_result("completed", text, structured)
    assert status == "success"


def test_status_message_parts_preferred():
    task = {
        "status": {
            "state": "completed",
            "message": {"parts": [{"kind": "text", "text": "from status"}]},
        },
        "artifacts": [{"parts": [{"kind": "text", "text": "from artifact"}]}],
    }
    text, _ = _extract_reply_from_task(task)
    assert text == "from status"


def test_truly_empty_completed_is_empty_result():
    text, structured = _extract_reply_from_task(
        _task([{"kind": "data", "data": {"mode": "chat", "response": "", "result": None}}])
    )
    # response is empty string, but the object itself is non-empty → structured set.
    status, _ = classify_task_result("completed", text, structured)
    assert status == "success"  # we still have structured output to show

    # Genuinely nothing back → empty_result.
    status2, _ = classify_task_result("completed", "", None)
    assert status2 == "empty_result"
