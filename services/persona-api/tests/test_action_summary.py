"""
Focused tests for issue #11 — Action Summary.

These tests exercise the non-streaming orchestrator and the
`_build_action_summary` heuristic directly, confirming the backend returns
a clean, user-facing status summary at the end of a turn.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

# Add this backend's root to sys.path (must match the copy under test,
# not a hardcoded absolute path that could point at the prod clone).
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "TEST_TOKEN")

import config  # noqa: E402
from unittest.mock import MagicMock

config.get_supabase = MagicMock(return_value=MagicMock())

from agent import orchestrator  # noqa: E402


class _FakeProvider:
    """Provider that simulates one tool call then a final answer."""

    def chat_with_tools(self, messages, tools):
        if len(messages) == 2:  # system + user only
            return "", [
                {
                    "id": "tc_1",
                    "name": "search_zynd_personas",
                    "arguments": {"query": "AI founders", "top_k": 3},
                }
            ]
        return "I found 3 AI founders and drafted outreach for them.", None

    def build_assistant_tool_message(self, content, tool_calls):
        return {
            "role": "assistant",
            "content": content or "",
            "tool_calls": tool_calls,
        }

    def build_tool_result_message(self, tool_call_id, result, tool_name="unknown"):
        return {"role": "tool", "tool_call_id": tool_call_id, "content": result}


def _fake_mcp_call(name: str, args: dict):
    if name == "search_zynd_personas":
        return {
            "status": "success",
            "count": 3,
            "results": [
                {"name": "Alice", "agent_id": "zns:alice"},
                {"name": "Bob", "agent_id": "zns:bob"},
                {"name": "Carol", "agent_id": "zns:carol"},
            ],
        }
    return {"success": True}


def test_orchestrator_returns_action_summary():
    # Patch provider and tools
    orchestrator._get_provider = lambda: _FakeProvider()
    orchestrator.mcp_server._call = _fake_mcp_call

    # Patch DB/context helpers so no real infra is needed
    orchestrator._persist_chat_message = lambda *a, **k: None
    async def _noop_ingest(*a, **k):
        pass
    orchestrator.ingest_conversation = _noop_ingest
    orchestrator._load_history_from_db = lambda *a, **k: []
    orchestrator._format_user_brief = lambda *a, **k: "Test user brief"
    orchestrator.list_connected_providers = lambda uid: []
    orchestrator.is_linkedin_scraped = lambda uid: False

    user_id = str(uuid.uuid4())
    conversation_id = f"conv-{uuid.uuid4()}"

    result = asyncio.run(
        orchestrator.handle_user_message(
            user_id=user_id,
            message="Find 3 AI founders and draft outreach",
            conversation_id=conversation_id,
            time_zone="UTC",
        )
    )

    print("\n--- Orchestrator result keys ---")
    for key in result:
        print(f"  {key}: {type(result[key]).__name__}")
    print("--- action_summary ---")
    print(json.dumps(result.get("action_summary"), indent=2, default=str))

    assert "reply" in result
    assert "actions_taken" in result
    assert "conversation_id" in result

    # This is the requirement under test.
    assert "action_summary" in result, (
        "Expected the orchestrator to return a structured action_summary, "
        f"but got only these keys: {list(result.keys())}"
    )

    summary = result["action_summary"]
    assert len(summary) > 0
    first = summary[0]
    assert first["status"] == "done"
    assert "3" in first["label"]


def test_action_summary_deduplicates_search_results():
    """Two searches that share a result should not inflate the person count."""
    actions = [
        {
            "tool": "search_zynd_personas",
            "args": {"query": "founder"},
            "result": {
                "status": "success",
                "results": [
                    {"agent_id": "zns:alice", "name": "Alice"},
                    {"agent_id": "zns:bob", "name": "Bob"},
                ],
            },
        },
        {
            "tool": "search_zynd_personas",
            "args": {"query": "startup"},
            "result": {
                "status": "success",
                "results": [
                    {"agent_id": "zns:bob", "name": "Bob"},
                    {"agent_id": "zns:carol", "name": "Carol"},
                ],
            },
        },
    ]
    summary = orchestrator._build_action_summary(actions)
    found_items = [s for s in summary if s["label"].startswith("Found")]
    assert len(found_items) == 1
    assert "3" in found_items[0]["label"], f"Expected 3 unique people, got: {found_items[0]['label']}"


def test_action_summary_filters_birthday_reminders():
    """All-day birthday reminders should not count as scheduled meetings."""
    actions = [
        {
            "tool": "list_calendar_events",
            "args": {},
            "result": {
                "success": True,
                "events": [
                    {"id": "1", "summary": "Happy birthday!", "start": "2026-08-23"},
                    {"id": "2", "summary": "John's Birthday", "start": "2026-09-10"},
                    {"id": "3", "summary": "Team Standup", "start": "2026-08-04T10:00:00Z"},
                ],
            },
        },
    ]
    summary = orchestrator._build_action_summary(actions)
    meeting_items = [s for s in summary if "meeting" in s["label"].lower()]
    assert len(meeting_items) == 1
    assert "1 meeting" in meeting_items[0]["label"], f"Expected 1 real meeting, got: {meeting_items[0]['label']}"


def test_action_summary_no_meetings():
    """An empty calendar should produce 'No meetings scheduled'."""
    actions = [
        {
            "tool": "list_calendar_events",
            "args": {},
            "result": {"success": True, "events": []},
        },
    ]
    summary = orchestrator._build_action_summary(actions)
    assert any(s["label"] == "No meetings scheduled" for s in summary)


def test_extract_action_summary_tag():
    """The orchestrator can extract a structured summary from agent-authored tags."""
    text = (
        "I found some people and drafted outreach for them.\n\n"
        "<action_summary>\n"
        "✅ Found 3 relevant people\n"
        "✅ Drafted outreach for 3 people\n"
        "📅 No meetings scheduled\n"
        "</action_summary>"
    )
    summary, cleaned = orchestrator._extract_action_summary_tag(text)

    assert len(summary) == 3
    assert summary[0] == {"status": "done", "label": "Found 3 relevant people", "icon": "✅"}
    assert summary[1] == {"status": "done", "label": "Drafted outreach for 3 people", "icon": "✅"}
    assert summary[2] == {"status": "none", "label": "No meetings scheduled", "icon": "📅"}

    assert "<action_summary>" not in cleaned
    assert "Found 3 relevant people" not in cleaned
    assert "I found some people" in cleaned


def test_resolve_action_summary_prefers_tag():
    """When the agent provides tags, those override the heuristic fallback."""
    text = (
        "Done.\n\n"
        "<action_summary>\n"
        "✅ Found 2 relevant people\n"
        "</action_summary>"
    )
    actions = [
        {
            "tool": "search_zynd_personas",
            "args": {},
            "result": {
                "status": "success",
                "results": [
                    {"agent_id": "zns:alice", "name": "Alice"},
                    {"agent_id": "zns:bob", "name": "Bob"},
                ],
            },
        },
    ]
    summary, cleaned = orchestrator._resolve_action_summary(text, actions)
    assert len(summary) == 1
    assert summary[0]["label"] == "Found 2 relevant people"
    assert "<action_summary>" not in cleaned


if __name__ == "__main__":
    test_orchestrator_returns_action_summary()
    test_action_summary_deduplicates_search_results()
    test_action_summary_filters_birthday_reminders()
    test_action_summary_no_meetings()
    test_extract_action_summary_tag()
    test_resolve_action_summary_prefers_tag()
    print("\nPASS")
