from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
from api import agents, cards
from models.card import AgentProfileCard
from services import events, owner_home, ua_class


@pytest.mark.parametrize("header,name", [
    ("Mozilla/5.0 Claude-User/1.0", "Claude-User"),
    ("claudebot/1.0", "ClaudeBot"),
    ("ChatGPT-User/1.0", "ChatGPT-User"),
    ("GPTBot/1.0", "GPTBot"),
    ("PerplexityBot", "PerplexityBot"),
    ("curl/8.0", None), (None, None), ("Mozilla/5.0", None),
])
def test_attribution_on_both_event_paths(monkeypatch, header, name):
    monkeypatch.setattr(config, "FEATURE_S04_EVENTS", True)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    insert = MagicMock()
    monkeypatch.setattr(events, "_insert_rows", insert)
    meta = {"endpoint": "data.json", "agent_name": "forged"}
    events.insert_batch([{"event": "agent_fetch", "handle": "alice", "meta": meta}], user_agent=header, ip=None)
    events.emit("view", handle="alice", meta=meta, user_agent=header)
    for call in insert.call_args_list:
        row = call.args[0][0]
        assert row["meta"].get("agent_name") == name
        assert row["meta"]["endpoint"] == "data.json"
        assert row["actor_class"] == ua_class.classify(header)
    assert meta["agent_name"] == "forged"  # Don't mutate caller data.


@pytest.mark.parametrize("path,event,endpoint", [
    ("/cards/by-handle/alice/view", "view", "card-view"),
    ("/v1/agents/c1", "agent_fetch", "agent-profile"),
])
def test_profile_endpoints_record_only_successful_public_fetches(monkeypatch, path, event, endpoint):
    card = AgentProfileCard(id="c1", handle="alice", identity={"name": "Alice"})
    monkeypatch.setattr(cards.cards_service, "get_card_by_handle", lambda _: card)
    monkeypatch.setattr(cards.cards_service, "get_card", lambda _: card)
    monkeypatch.setattr(cards.cards_service, "card_is_claimed", lambda _: True)
    monkeypatch.setattr(config, "FEATURE_S03_UNCLAIMED_TIERING", True)
    emit = MagicMock()
    monkeypatch.setattr(events, "emit", emit)
    app = FastAPI()
    app.include_router(cards.router, prefix="/cards")
    app.include_router(agents.router, prefix="/v1/agents")
    client = TestClient(app)
    assert client.get(path, headers={"User-Agent": "Claude-User"}).status_code == 200
    emit.assert_called_once()
    assert emit.call_args.args == (event,)
    assert emit.call_args.kwargs["handle"] == "alice"
    assert emit.call_args.kwargs["meta"] == {"endpoint": endpoint}
    assert emit.call_args.kwargs["request"].headers["user-agent"] == "Claude-User"
    emit.reset_mock()
    monkeypatch.setattr(cards.cards_service, "card_is_claimed", lambda _: False)
    assert client.get(path).status_code == 404
    emit.assert_not_called()
    card = None
    assert client.get(path).status_code == 404
    emit.assert_not_called()


def test_agent_breakdown_groups_known_clients_and_preserves_legacy_unknown():
    sb = MagicMock()
    q = sb.table.return_value
    for method in ("select", "eq", "in_", "gte", "order", "limit"):
        getattr(q, method).return_value = q
    q.execute.return_value = SimpleNamespace(data=[
        {"meta": {"agent_name": "Claude-User"}},
        {"meta": {"agent_name": "Claude-User"}},
        {"meta": {"agent_name": "GPTBot"}},
        {"meta": None}, {"meta": {"agent_name": "forged"}},
    ])
    result = owner_home.agent_clients(sb, "alice", "2026-10-20")
    assert {r["name"]: r["count"] for r in result} == {"Claude-User": 2, "GPTBot": 1, "Unknown": 2}
    assert result[0]["provider"] == "Claude"
    q.eq.assert_any_call("handle", "alice")
    q.eq.assert_any_call("actor_class", "ai_agent")
    q.gte.assert_called_once_with("ts", "2026-10-20")
    q.in_.assert_called_once_with("event", ["view", "agent_fetch"])
    q.limit.assert_called_once_with(1000)
    q.execute.side_effect = RuntimeError("unavailable")
    assert owner_home.agent_clients(sb, "alice", "2026-10-20") is None
