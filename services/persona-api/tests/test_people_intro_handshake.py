from __future__ import annotations

from types import SimpleNamespace

import pytest


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, db, name: str):
        self.db = db
        self.name = name
        self.filters: dict[str, object] = {}
        self.inserted = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def insert(self, row):
        self.inserted = row
        return self

    def execute(self):
        if self.name == "dm_threads":
            return _Result([self.db.thread])
        if self.name == "dm_messages":
            row = {"id": "msg-1", **(self.inserted or {})}
            self.db.inserted_messages.append(row)
            return _Result([row])
        if self.name == "persona_agents":
            if "agent_id" in self.filters:
                return _Result([{"webhook_url": self.db.partner_webhook_url}])
            if "user_id" in self.filters:
                return _Result([{"derivation_index": 0, "public_key": "ed25519:test"}])
        return _Result([])


class _FakeSupabase:
    def __init__(self, thread: dict):
        self.thread = thread
        self.partner_webhook_url = "https://persona.zynd.ai/api/persona/receiver-user"
        self.inserted_messages: list[dict] = []

    def table(self, name: str):
        return _FakeTable(self, name)


@pytest.mark.asyncio
async def test_agent_send_marks_pending_intro_as_connection_request(monkeypatch):
    from api import persona
    import agent.persona_manager as persona_manager
    import agent.zynd_identity as zynd_identity
    import agent.a2a.transport as transport

    thread = {
        "id": "thread-1",
        "initiator_id": "zns:sender",
        "receiver_id": "zns:receiver",
        "status": "pending",
    }
    fake_sb = _FakeSupabase(thread)
    captured = {}

    monkeypatch.setattr(persona, "_supabase", lambda: fake_sb)
    monkeypatch.setattr(
        persona,
        "get_persona_status",
        lambda _user_id: {
            "deployed": True,
            "agent_id": "zns:sender",
            "name": "Sender Persona",
        },
    )
    monkeypatch.setattr(persona_manager, "_load_developer_seed", lambda: b"dev-seed")
    monkeypatch.setattr(
        persona_manager,
        "_derive_agent_keypair",
        lambda _seed, _index: (b"persona-seed", b"persona-public-key"),
    )
    monkeypatch.setattr(zynd_identity, "keypair_from_seed", lambda _seed: object())
    monkeypatch.setattr(zynd_identity, "build_derivation_proof", lambda *_args: {})

    async def fake_dispatch(_client, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            transport=SimpleNamespace(value="push"),
            task={"id": "task-1", "status": {"state": "submitted"}},
            callback_id="callback-1",
        )

    monkeypatch.setattr(transport, "dispatch", fake_dispatch)

    result = await persona.agent_channel_send(
        "sender-user",
        persona.AgentChannelSend(thread_id="thread-1", content="Hello from the intro flow"),
    )

    assert result["delivery"]["delivered"] is True
    assert captured["context_id"] == "thread-1"
    assert captured["text"] == "Hello from the intro flow"
    assert captured["data"]["kind"] == persona.CONNECTION_REQUEST_DATA_KIND
    assert captured["data"]["sender_agent_id"] == "zns:sender"
    assert captured["data"]["text"] == "Hello from the intro flow"


@pytest.mark.asyncio
async def test_agent_send_leaves_accepted_messages_as_plain_text(monkeypatch):
    from api import persona
    import agent.persona_manager as persona_manager
    import agent.zynd_identity as zynd_identity
    import agent.a2a.transport as transport

    thread = {
        "id": "thread-1",
        "initiator_id": "zns:sender",
        "receiver_id": "zns:receiver",
        "status": "accepted",
    }
    fake_sb = _FakeSupabase(thread)
    captured = {}

    monkeypatch.setattr(persona, "_supabase", lambda: fake_sb)
    monkeypatch.setattr(
        persona,
        "get_persona_status",
        lambda _user_id: {
            "deployed": True,
            "agent_id": "zns:sender",
            "name": "Sender Persona",
        },
    )
    monkeypatch.setattr(persona_manager, "_load_developer_seed", lambda: b"dev-seed")
    monkeypatch.setattr(
        persona_manager,
        "_derive_agent_keypair",
        lambda _seed, _index: (b"persona-seed", b"persona-public-key"),
    )
    monkeypatch.setattr(zynd_identity, "keypair_from_seed", lambda _seed: object())
    monkeypatch.setattr(zynd_identity, "build_derivation_proof", lambda *_args: {})

    async def fake_dispatch(_client, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            transport=SimpleNamespace(value="send"),
            task={"id": "task-1", "status": {"state": "completed"}},
            callback_id=None,
        )

    monkeypatch.setattr(transport, "dispatch", fake_dispatch)

    await persona.agent_channel_send(
        "sender-user",
        persona.AgentChannelSend(thread_id="thread-1", content="Normal accepted-thread message"),
    )

    assert captured["data"] is None
