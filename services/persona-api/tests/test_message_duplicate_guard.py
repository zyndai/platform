from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, db: "_FakeSupabase", name: str):
        self.db = db
        self.name = name
        self.filters: dict[str, Any] = {}

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def in_(self, key, values):
        self.filters[key] = list(values)
        return self

    def gte(self, key, value):
        self.filters[key] = value
        return self

    def insert(self, row):
        self.db.inserted.append((self.name, row))
        return self

    def execute(self):
        if self.name == "dm_threads":
            return _Result([self.db.thread])
        if self.name == "dm_messages":
            rows = list(self.db.messages)
            thread_id = self.filters.get("thread_id")
            if thread_id is not None:
                rows = [r for r in rows if r.get("thread_id") == thread_id]
            sender_id = self.filters.get("sender_id")
            if sender_id is not None:
                rows = [r for r in rows if r.get("sender_id") == sender_id]
            return _Result(rows)
        if self.name == "persona_agents":
            return _Result([{"webhook_url": "https://persona.zynd.ai/api/persona/receiver-user"}])
        return _Result([])


class _FakeSupabase:
    def __init__(self, thread: dict, messages: list[dict] | None = None):
        self.thread = thread
        self.messages = messages or []
        self.inserted: list[tuple[str, dict]] = []

    def table(self, name: str):
        return _FakeTable(self, name)


@pytest.fixture
def patched_message_env(monkeypatch):
    """Patch dependencies shared by all message_zynd_agent tests."""
    from mcp.tools import zynd_network
    import agent.persona_manager as persona_manager
    import config

    monkeypatch.setattr(config, "get_supabase", lambda: _FakeSupabase(
        thread={
            "id": "thread-1",
            "initiator_id": "zns:sender",
            "receiver_id": "zns:receiver",
            "status": "accepted",
        },
        messages=[],
    ))
    monkeypatch.setattr(
        persona_manager,
        "get_persona_status",
        lambda _user_id: {
            "deployed": True,
            "agent_id": "zns:sender",
            "name": "Sender Persona",
        },
    )

    sent: list[dict] = []

    def fake_send_via_a2a_v3(**kwargs):
        sent.append(kwargs)
        return {
            "task": {"id": "task-1", "status": {"state": "completed"}},
            "task_state": "completed",
            "reply_text": "Sounds good.",
        }

    monkeypatch.setattr(zynd_network, "_send_via_a2a_v3", fake_send_via_a2a_v3)
    return sent


def test_duplicate_recent_message_blocked(patched_message_env, monkeypatch):
    """An identical message already sent recently must not be dispatched again."""
    from mcp.tools.zynd_network import message_zynd_agent

    fake_sb = _FakeSupabase(
        thread={
            "id": "thread-1",
            "initiator_id": "zns:sender",
            "receiver_id": "zns:receiver",
            "status": "accepted",
        },
        messages=[{
            "thread_id": "thread-1",
            "sender_id": "zns:sender",
            "content": "Hey, are we still on for 3pm?",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }],
    )
    monkeypatch.setattr("config.get_supabase", lambda: fake_sb)

    result = message_zynd_agent(
        user_id="sender-user",
        target_webhook_url="https://persona.zynd.ai/api/persona/receiver-user",
        target_agent_id="zns:receiver",
        message="Hey, are we still on for 3pm?",
    )

    assert result["status"] == "duplicate"
    assert not patched_message_env, "A2A send should have been skipped"
    assert not fake_sb.inserted, "No new dm_messages row should be inserted"


def test_non_duplicate_message_sends(patched_message_env, monkeypatch):
    """A message not seen recently should be dispatched normally."""
    from mcp.tools.zynd_network import message_zynd_agent

    fake_sb = _FakeSupabase(
        thread={
            "id": "thread-1",
            "initiator_id": "zns:sender",
            "receiver_id": "zns:receiver",
            "status": "accepted",
        },
        messages=[{
            "thread_id": "thread-1",
            "sender_id": "zns:sender",
            "content": "A different earlier message",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }],
    )
    monkeypatch.setattr("config.get_supabase", lambda: fake_sb)

    result = message_zynd_agent(
        user_id="sender-user",
        target_webhook_url="https://persona.zynd.ai/api/persona/receiver-user",
        target_agent_id="zns:receiver",
        message="Hey, are we still on for 3pm?",
    )

    assert result["status"] == "success"
    assert len(patched_message_env) == 1
    assert fake_sb.inserted, "dm_messages row should be inserted"


def test_duplicate_detection_is_per_thread(patched_message_env, monkeypatch):
    """A duplicate on thread A must not block the same message on thread B."""
    from mcp.tools.zynd_network import message_zynd_agent

    fake_sb = _FakeSupabase(
        thread={
            "id": "thread-2",
            "initiator_id": "zns:sender",
            "receiver_id": "zns:other",
            "status": "accepted",
        },
        messages=[{
            "thread_id": "thread-1",  # duplicate exists, but on a different thread
            "sender_id": "zns:sender",
            "content": "Hey, are we still on for 3pm?",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }],
    )
    monkeypatch.setattr("config.get_supabase", lambda: fake_sb)

    result = message_zynd_agent(
        user_id="sender-user",
        target_webhook_url="https://persona.zynd.ai/api/persona/other-user",
        target_agent_id="zns:other",
        message="Hey, are we still on for 3pm?",
    )

    assert result["status"] == "success"
    assert len(patched_message_env) == 1
