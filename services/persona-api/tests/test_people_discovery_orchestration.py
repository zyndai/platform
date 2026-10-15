"""People discovery routing and tool-result handoff without external services."""

import asyncio
import json
from copy import deepcopy
from uuid import uuid4

import pytest

from agent import orchestrator


USER_ID = "00000000-0000-0000-0000-000000000123"
FILTERS = {"titles": ["Founder", "CTO"], "industries": ["Computer Software"]}
CARD_URL = "https://cards.zynd.ai/p/ada-founder"
LINKEDIN_URL = "https://www.linkedin.com/in/lin-founder/"
DISCOVERY_RESULT = {
    "zynd_network": {"status": "success", "results": [{"name": "Nia", "source_id": "zns:nia", "connection_eligible": True}]},
    "zynd_cards": {"status": "success", "results": [{"name": "Ada", "public_url": CARD_URL, "connection_eligible": False}]},
    "external_prospects": {"status": "success", "results": [{"name": "Lin", "public_url": LINKEDIN_URL, "connection_eligible": False}]},
}
FINAL_REPLY = f"Meet Ada: {CARD_URL} and Lin: {LINKEDIN_URL}."


class DiscoveryProvider:
    def __init__(self, call_tool=True):
        self.call_tool = call_tool
        self.requests = []

    def _respond(self, messages, tools):
        self.requests.append((deepcopy(messages), deepcopy(tools)))
        if len(self.requests) == 1 and self.call_tool:
            return "", [{
                "id": "call-discovery", "name": "discover_people",
                "arguments": {"query": "AI founders", "people_filters": deepcopy(FILTERS)},
            }]
        return (FINAL_REPLY if self.call_tool else "The answer is 42."), []

    def chat_with_tools(self, messages, tools):
        return self._respond(messages, tools)

    def chat_with_tools_stream(self, messages, tools):
        text, tool_calls = self._respond(messages, tools)
        yield {"type": "turn_done", "text": text, "tool_calls": tool_calls}

    def build_assistant_tool_message(self, text, calls):
        return {"role": "assistant", "content": text, "tool_calls": calls}

    def build_tool_result_message(self, call_id, content, tool_name=None):
        return {"role": "tool", "tool_call_id": call_id, "content": content}


@pytest.fixture
def discovery_environment(monkeypatch):
    import agent.digital_twin as digital_twin
    import agent.persona_manager as persona_manager

    provider = DiscoveryProvider()
    calls = []
    persisted = []

    async def empty_memory(*_args):
        return type("MemoryContext", (), {"assertions": []})()

    async def empty_style(*_args):
        return {}

    async def no_ingest(*_args):
        return None

    def fake_call(name, args):
        calls.append((name, deepcopy(args)))
        assert name == "discover_people"
        return deepcopy(DISCOVERY_RESULT)

    monkeypatch.setattr(persona_manager, "get_persona_status", lambda _id: {
        "name": "Test Principal", "description": "Interested in AI founders", "capabilities": [], "profile": {},
    })
    monkeypatch.setattr(orchestrator, "_get_user_email", lambda _id: None)
    monkeypatch.setattr(orchestrator, "_format_user_brief", lambda *_args, **_kwargs: "Interested in AI founders")
    monkeypatch.setattr(orchestrator, "_load_history_from_db", lambda *_args: [])
    monkeypatch.setattr(orchestrator, "_persist_chat_message", lambda *args: persisted.append(args))
    monkeypatch.setattr(orchestrator, "list_connected_providers", lambda _id: [])
    monkeypatch.setattr(orchestrator, "is_linkedin_scraped", lambda _id: False)
    monkeypatch.setattr(orchestrator, "load_memory_context", empty_memory)
    monkeypatch.setattr(orchestrator, "ingest_conversation", no_ingest)
    monkeypatch.setattr(digital_twin, "_load_style_profile", empty_style)
    monkeypatch.setattr(orchestrator, "_get_provider", lambda: provider)
    monkeypatch.setattr(orchestrator.mcp_server, "_call", fake_call)
    yield provider, calls, persisted
    orchestrator._conversations.clear()


def test_prompt_routes_people_and_preserves_source_boundaries(discovery_environment):
    prompt = orchestrator._build_system_prompt(USER_ID, [], time_zone="UTC")
    assert "discover_people" in prompt
    assert '"who should I meet"' in prompt
    assert '"via Zynd" alone does NOT' in prompt
    assert '"Zynd members only"' in prompt
    assert "network_only=true" in prompt
    assert "known Brief/goals/interests" in prompt
    assert "Never invent filters" in prompt
    assert "Cards results are public cards, not proof of a messageable persona" in prompt
    assert "never merge identities across sources by name".lower() in prompt.lower()
    assert "verified public profile links" in prompt
    assert "Do NOT search the network" in prompt


def test_discovery_generic_schema_advertises_nested_filters(discovery_environment):
    registered = next(t for t in orchestrator.mcp_server.get_capabilities()["tools"] if t["name"] == "discover_people")
    assert {"query", "user_id", "people_filters", "network_only"} <= {p["name"] for p in registered["parameters"]}
    tool = next(t for t in orchestrator._capabilities_to_generic_tools() if t["name"] == "discover_people")
    schema = tool["properties"]["people_filters"]
    assert schema["type"] == "object"
    for key in FILTERS:
        assert schema["properties"][key]["type"] == "array"
        assert schema["properties"][key]["items"] == {"type": "string"}
    assert schema["properties"]["cities"]["items"] == {"type": "string"}

    from google.genai import types

    gemini = orchestrator.GeminiProvider.__new__(orchestrator.GeminiProvider)
    gemini._types = types
    declaration = gemini._convert_tools([tool])[0]
    gemini_filters = declaration.parameters.properties["people_filters"]
    assert gemini_filters.type == types.Type.OBJECT
    assert gemini_filters.properties["titles"].type == types.Type.ARRAY
    assert gemini_filters.properties["titles"].items.type == types.Type.STRING
    assert gemini_filters.properties["cities"].items.type == types.Type.STRING


def test_discovery_is_never_available_to_external_agents():
    for permissions in (None, {}, {key: True for key in orchestrator.EXTERNAL_PERMISSION_GATES}):
        for group_context in (False, True):
            assert "discover_people" not in orchestrator._allowed_external_tools(permissions, group_context)


def test_discovery_action_summary_counts_source_scoped_people():
    result = deepcopy(DISCOVERY_RESULT)
    result["zynd_cards"]["results"][0]["source_id"] = "zns:nia"
    result["external_prospects"]["results"][0]["source_id"] = LINKEDIN_URL
    result["external_prospects"]["results"].append({"source_id": LINKEDIN_URL})
    summary = orchestrator._build_action_summary([{"tool": "discover_people", "result": result}])
    assert {"status": "done", "label": "Found 3 relevant people", "icon": "✅"} in summary


@pytest.mark.parametrize("stream", [False, True], ids=["normal", "streaming"])
def test_discovery_result_reaches_next_model_turn_and_final_reply(discovery_environment, stream):
    provider, calls, persisted = discovery_environment
    conversation_id = f"discovery-{uuid4()}"

    async def run():
        if stream:
            events = [event async for event in orchestrator.handle_user_message_stream(
                USER_ID, "Suggest AI founders I can connect to via Zynd", conversation_id=conversation_id,
            )]
            assert len([event for event in events if event["type"] == "tool_result"]) == 1
            assert events[-1]["type"] == "done"
            return events[-1]
        return await orchestrator.handle_user_message(
            USER_ID, "Suggest AI founders I can connect to via Zynd", conversation_id=conversation_id,
        )

    result = asyncio.run(run())
    assert len(provider.requests) == 2
    assert any(t["name"] == "discover_people" for t in provider.requests[0][1])
    assert calls == [("discover_people", {"query": "AI founders", "people_filters": FILTERS, "user_id": USER_ID})]
    tool_messages = [m for m in provider.requests[1][0] if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert json.loads(tool_messages[0]["content"]) == DISCOVERY_RESULT
    assert CARD_URL in tool_messages[0]["content"]
    assert LINKEDIN_URL in tool_messages[0]["content"]
    assert result["actions_taken"] == [{"tool": "discover_people", "args": calls[0][1], "result": DISCOVERY_RESULT}]
    assert result["reply"] == FINAL_REPLY
    assert persisted[-1][3] == FINAL_REPLY


@pytest.mark.parametrize("stream", [False, True], ids=["normal", "streaming"])
def test_unrelated_question_is_answered_without_tool_call(discovery_environment, stream):
    provider, calls, _ = discovery_environment
    provider.call_tool = False

    async def run():
        if stream:
            events = [event async for event in orchestrator.handle_user_message_stream(
                USER_ID, "What is six times seven?", conversation_id=f"direct-{uuid4()}",
            )]
            return events[-1]
        return await orchestrator.handle_user_message(
            USER_ID, "What is six times seven?", conversation_id=f"direct-{uuid4()}",
        )

    result = asyncio.run(run())
    assert len(provider.requests) == 1
    assert calls == []
    assert result["actions_taken"] == []
    assert result["reply"] == "The answer is 42."
