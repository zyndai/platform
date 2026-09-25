"""
Tests for `agent.a2a_router._ping_inbound_dm`.

The function must gate on the per-side mode columns (`initiator_mode` /
`receiver_mode`) — NOT the legacy single-column `dm_threads.mode` flag,
which is nullable and stale. Trusting the old column silently swallowed
every Telegram ping because `(None or "agent").lower() == "agent" != "human"`.

Each test stubs:
  - `agent.persona_manager.get_persona_status` so we control which side
    the recipient maps to.
  - `services.telegram_notify.notify_user` with an awaitable spy so we
    can assert exact call count without hitting Telegram.

The send path uses `asyncio.create_task` when a running loop exists and
falls back to a detached thread otherwise. We drive it from a running
loop (the test functions are `pytest.mark.asyncio`) so the task path is
exercised and we can `await asyncio.sleep(0)` to let it run.
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest


def _install_persona_stub(monkeypatch, *, agent_id: str | None):
    """Stub agent.persona_manager so the function under test can resolve
    the recipient's agent_id without hitting Supabase."""
    fake = types.ModuleType("agent.persona_manager")
    fake.get_persona_status = lambda user_id: {
        "deployed": agent_id is not None,
        "agent_id": agent_id,
    }
    if "agent" not in sys.modules:
        monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.persona_manager", fake)


class _NotifySpy:
    """Awaitable spy compatible with `services.telegram_notify.notify_user`'s
    signature `(user_id, text, *, parse_mode=...)`."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, user_id, text, *, parse_mode="Markdown"):
        self.calls.append((user_id, text))
        return True


def _install_notify_spy(monkeypatch) -> _NotifySpy:
    spy = _NotifySpy()
    # Replace on the live module so the `from services.telegram_notify
    # import notify_user` inside the function under test resolves to spy.
    from services import telegram_notify

    monkeypatch.setattr(telegram_notify, "notify_user", spy)
    return spy


@pytest.mark.asyncio
async def test_ping_fires_when_receiver_side_is_human(monkeypatch):
    """User is the receiver and they've taken over → ping must fire."""
    from agent.a2a_router import _ping_inbound_dm

    _install_persona_stub(monkeypatch, agent_id="agent_me")
    spy = _install_notify_spy(monkeypatch)

    thread = {
        "initiator_id": "agent_other",
        "initiator_name": "Sarah",
        "initiator_mode": "agent",
        "receiver_id": "agent_me",
        "receiver_name": "Me",
        "receiver_mode": "human",
    }

    _ping_inbound_dm(
        recipient_user_id="user_1",
        thread=thread,
        sender_entity_id="agent_other",
        inbound_text="Hey, can we meet?",
    )

    # Let the scheduled create_task() run.
    await asyncio.sleep(0)

    assert len(spy.calls) == 1
    user_id, text = spy.calls[0]
    assert user_id == "user_1"
    assert "Sarah" in text
    assert "Hey, can we meet?" in text


@pytest.mark.asyncio
async def test_ping_fires_when_initiator_side_is_human(monkeypatch):
    """User is the initiator and they've taken over → ping must fire."""
    from agent.a2a_router import _ping_inbound_dm

    _install_persona_stub(monkeypatch, agent_id="agent_me")
    spy = _install_notify_spy(monkeypatch)

    thread = {
        "initiator_id": "agent_me",
        "initiator_name": "Me",
        "initiator_mode": "human",
        "receiver_id": "agent_other",
        "receiver_name": "Sarah",
        "receiver_mode": "agent",
    }

    _ping_inbound_dm(
        recipient_user_id="user_1",
        thread=thread,
        sender_entity_id="agent_other",
        inbound_text="Following up on Tuesday.",
    )

    await asyncio.sleep(0)

    assert len(spy.calls) == 1
    user_id, text = spy.calls[0]
    assert user_id == "user_1"
    # Partner name is the sender side; sender_entity_id != initiator_id
    # so we render the receiver_name as the partner.
    assert "Sarah" in text


@pytest.mark.asyncio
async def test_ping_skipped_when_recipient_side_still_agent(monkeypatch):
    """User is the receiver but their side is still 'agent' → no ping
    (their persona will reply for them)."""
    from agent.a2a_router import _ping_inbound_dm

    _install_persona_stub(monkeypatch, agent_id="agent_me")
    spy = _install_notify_spy(monkeypatch)

    thread = {
        "initiator_id": "agent_other",
        "initiator_name": "Sarah",
        "initiator_mode": "agent",
        "receiver_id": "agent_me",
        "receiver_name": "Me",
        "receiver_mode": "agent",
    }

    _ping_inbound_dm(
        recipient_user_id="user_1",
        thread=thread,
        sender_entity_id="agent_other",
        inbound_text="Hey, can we meet?",
    )

    await asyncio.sleep(0)

    assert spy.calls == []
