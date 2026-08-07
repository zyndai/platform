from __future__ import annotations

import pytest


@pytest.fixture
def stub_persona(monkeypatch):
    """Avoid hitting Supabase when building the system prompt."""
    import agent.persona_manager as persona_manager

    monkeypatch.setattr(
        persona_manager,
        "get_persona_status",
        lambda _user_id: {
            "deployed": True,
            "agent_id": "zns:test-agent",
            "name": "Test Persona",
            "description": "A test persona.",
            "capabilities": [],
            "profile": {},
        },
    )


def _normalized_prompt(**kwargs):
    from agent.orchestrator import _build_system_prompt

    return " ".join(_build_system_prompt(**kwargs).split())


def test_meeting_protocol_prefers_direct_proposal(stub_persona):
    """
    The internal-mode system prompt should instruct the agent to propose a
    meeting card directly on accepted Zynd connections, not ask the other
    agent for availability first.
    """
    prompt = _normalized_prompt(
        user_id="00000000-0000-0000-0000-000000000001",
        connected_providers=[],
        is_external=False,
        sender_agent_id=None,
        time_zone="UTC",
    )
    assert "the meeting card IS the negotiation mechanism" in prompt
    assert "do not ask the other agent when they are free first" in prompt.lower()
    assert "Negotiate availability by sending a message" not in prompt
    assert "ONLY THEN call `propose_meeting`" not in prompt


def test_autonomy_prompt_presents_reasonable_defaults(stub_persona):
    """The agent should be encouraged to act rather than pause for permission."""
    prompt = _normalized_prompt(
        user_id="00000000-0000-0000-0000-000000000001",
        connected_providers=[],
        is_external=False,
        sender_agent_id=None,
        time_zone="UTC",
    )
    assert "You are an autonomous agent, not a chatbot" in prompt
    assert "complete as much of the workflow as you can" in prompt
    assert 'Only ask your principal a question when you genuinely cannot proceed' in prompt


def test_propose_meeting_tool_description_is_autonomous():
    """The scheduling tool docstring no longer forbids cold proposals."""
    from mcp.tools.scheduling import propose_meeting

    doc = " ".join((propose_meeting.__doc__ or "").lower().split())
    assert "the other side receives the proposal as a meeting card" in doc
    assert "do not ask the other agent for availability first" in doc
    assert "only call this after you have already negotiated availability" not in doc
    assert "never propose cold" not in doc
