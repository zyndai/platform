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
    ("python-httpx/0.28 Codex", "Codex"),
    ("python-httpx/0.28 ChatGPT-MCP", "ChatGPT-MCP"),
    ("python-httpx/0.28 Claude-MCP", "Claude-MCP"),
    ("Mozilla/5.0 Zynd-MCP", "Zynd-MCP"),
    ("curl/8.0", None), (None, None), ("Mozilla/5.0", None),
])
def test_attribution_on_both_event_paths(monkeypatch, header, name):
    monkeypatch.setattr(config, "FEATURE_S04_EVENTS", True)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    insert = MagicMock()
    monkeypatch.setattr(events, "_insert_rows", insert)
    meta = {"endpoint": "data.json", "agent_name": "forged"}
    events.insert_batch([{"event": "agent_fetch", "handle": "alice", "meta": meta}], user_agent=header, ip=None,
                        server_observed=True)
    events.emit("view", handle="alice", meta=meta, user_agent=header)
    assert insert.call_count == 2
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


def _request(headers: dict):
    from starlette.datastructures import Headers

    return SimpleNamespace(headers=Headers(headers), client=None)


def test_node_stays_unknown_and_internal_website_reads_are_not_events(monkeypatch):
    monkeypatch.setattr(config, "FEATURE_S04_EVENTS", True)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    monkeypatch.setattr(config, "EVENTS_SERVER_TOKEN", "server-token")
    insert = MagicMock()
    monkeypatch.setattr(events, "_insert_rows", insert)
    # #given our own server reading a card to render it, with the token
    for ua in (ua_class.INTERNAL_CARDS_CLIENT, ua_class.INTERNAL_MEMORY_CLIENT):
        events.emit("view", handle="alice", request=_request({"User-Agent": ua, "X-Zynd-Server-Event": "server-token"}))
    # #then it is not a reader
    insert.assert_not_called()
    events.emit("view", handle="alice", user_agent="node")
    row = insert.call_args.args[0][0]
    assert row["actor_class"] == "unknown"
    assert row["meta"] == {"client_name": "Node.js"}
    assert events.attributed_meta({"client_name": "ChatGPT"}, "curl/8") == {"client_name": "curl"}


@pytest.mark.parametrize("token_header", [None, "wrong"])
def test_internal_user_agent_alone_does_not_hide_a_read(monkeypatch, token_header):
    monkeypatch.setattr(config, "FEATURE_S04_EVENTS", True)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    monkeypatch.setattr(config, "EVENTS_SERVER_TOKEN", "server-token")
    insert = MagicMock()
    monkeypatch.setattr(events, "_insert_rows", insert)
    headers = {"User-Agent": ua_class.INTERNAL_CARDS_CLIENT}
    if token_header:
        headers["X-Zynd-Server-Event"] = token_header
    events.emit("view", handle="alice", request=_request(headers))
    row = insert.call_args.args[0][0]
    assert row["actor_class"] == "unknown" and row["meta"] == {"client_name": "Unidentified"}


def test_cards_web_sentinel_for_a_missing_user_agent_is_unidentified():
    # lib/track.ts sends this when the visitor sent no User-Agent, instead of Node's own "node".
    assert ua_class.classify("Zynd-Unidentified-Visitor") == "unknown"
    assert ua_class.unidentified_client("Zynd-Unidentified-Visitor") == "Unidentified"


def test_unidentified_breakdown_is_separate_and_excludes_legacy_internal_reads():
    sb = MagicMock()
    q = sb.table.return_value
    for method in ("select", "eq", "in_", "gte", "order", "limit"):
        getattr(q, method).return_value = q
    q.execute.return_value = SimpleNamespace(data=[
        {"meta": {"client_name": "Node.js"}, "ts": "2026-10-28T05:34:18Z"},
        {"meta": {"client_name": "Node.js"}, "ts": "2026-10-28T05:30:00Z"},
        {"meta": None}, {"meta": {"client_name": "ChatGPT"}},
    ])
    assert owner_home.unidentified_clients(sb, "alice", "2026-10-20") == [
        {"name": "Node.js", "count": 2, "last_seen": "2026-10-28T05:34:18Z"}]
    q.eq.assert_any_call("actor_class", "unknown")
    q.in_.assert_any_call("meta->>client_name", list(ua_class.UNIDENTIFIED_CLIENTS))
    q.execute.side_effect = RuntimeError("unavailable")
    assert owner_home.unidentified_clients(sb, "alice", "2026-10-20") is None


def test_event_write_failure_is_not_acknowledged_as_success(monkeypatch):
    from api.events import router
    monkeypatch.setattr(config, "FEATURE_S04_EVENTS", True)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.side_effect = RuntimeError("connection failed")
    monkeypatch.setattr(events, "_event_store", lambda: sb)
    app = FastAPI()
    app.include_router(router)
    events._hits.clear()
    assert TestClient(app).post("/events", json={"events": [{"event": "view", "handle": "alice"}]}).status_code == 503


def test_event_connection_uses_http1_and_preserves_schema(monkeypatch):
    import httpx
    import supabase
    real_client = httpx.Client
    clients = []

    def client(**kwargs):
        assert kwargs["http2"] is False and kwargs["http1"] is True
        result = real_client(**kwargs)
        clients.append(result)
        return result

    create = MagicMock()
    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setattr(supabase, "create_client", create)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    events._event_store.cache_clear()
    try:
        events._event_store()
        events._event_store()
        create.assert_called_once()
        options = create.call_args.kwargs["options"]
        assert options.schema == "cards"
        assert options.httpx_client is clients[0]
    finally:
        events._event_store.cache_clear()
        for transport in clients:
            transport.close()


def _stored_batch(monkeypatch, batch, *, server_observed):
    monkeypatch.setattr(config, "FEATURE_S04_EVENTS", True)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    insert = MagicMock(return_value=True)
    monkeypatch.setattr(events, "_insert_rows", insert)
    assert events.insert_batch(batch, user_agent="ChatGPT-User/1.0", ip=None, server_observed=server_observed) is True
    return insert.call_args.args[0] if insert.called else []


def test_client_sent_agent_fetch_is_dropped_but_other_events_are_kept(monkeypatch):
    # #given a public POST mixing a forged AI read with a real browser event
    rows = _stored_batch(monkeypatch, [{"event": "agent_fetch", "handle": "alice"},
                                       {"event": "share_click", "handle": "alice"}], server_observed=False)
    # #then only the browser event is stored
    assert [r["event"] for r in rows] == ["share_click"]
    assert _stored_batch(monkeypatch, [{"event": "agent_fetch", "handle": "alice"}], server_observed=False) == []


def test_attested_agent_fetch_is_stored(monkeypatch):
    rows = _stored_batch(monkeypatch, [{"event": "agent_fetch", "handle": "alice"}], server_observed=True)
    assert [(r["event"], r["actor_class"]) for r in rows] == [("agent_fetch", "ai_agent")]


@pytest.mark.parametrize("server_observed, keeps_query", [(False, False), (True, True)])
def test_query_meta_needs_the_server_token(monkeypatch, server_observed, keeps_query):
    meta = {"endpoint": "ask", "query": "find me a rust engineer", "question": "forged", "question_source": "x"}
    rows = _stored_batch(monkeypatch, [{"event": "view", "handle": "alice", "meta": meta}],
                         server_observed=server_observed)
    stored = rows[0]["meta"]
    assert ("query" in stored) is keeps_query
    # Question history is only ever written by the chat handler, attested or not.
    assert "question" not in stored and "question_source" not in stored
    assert stored["endpoint"] == "ask"


def test_public_post_cannot_forge_agent_reads_through_the_api(monkeypatch):
    from api.events import router

    monkeypatch.setattr(config, "FEATURE_S04_EVENTS", True)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    monkeypatch.setattr(config, "EVENTS_SERVER_TOKEN", "server-token")
    sb = MagicMock()
    monkeypatch.setattr(events, "_event_store", lambda: sb)
    app = FastAPI()
    app.include_router(router)
    events._hits.clear()
    body = {"events": [{"event": "agent_fetch", "handle": "alice"}]}
    client = TestClient(app)
    assert client.post("/events", json=body, headers={"User-Agent": "ChatGPT-User/1.0"}).status_code == 204
    sb.table.assert_not_called()
    assert client.post("/events", json=body, headers={"User-Agent": "ChatGPT-User/1.0",
                                                       "X-Zynd-Server-Event": "server-token"}).status_code == 204
    assert sb.table.return_value.insert.call_args.args[0][0]["event"] == "agent_fetch"
