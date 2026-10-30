"""S04: UA classifier, event validation, rate limit, session hash, attribution."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import config
from services import events as events_service
from services import ua_class


@pytest.fixture(autouse=True)
def _reset_rate_hits():
    events_service._hits.clear()
    yield
    events_service._hits.clear()


# ── UA classifier ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "ua, expected",
    [
        ("Mozilla/5.0 GPTBot/1.0", "ai_agent"),
        ("ClaudeBot", "ai_agent"),
        ("Mozilla/5.0 (compatible; Googlebot/2.1)", "search_bot"),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X) Chrome/120.0", "human"),
        ("", "unknown"),
        (None, "unknown"),
        ("curl/8.0", "unknown"),
    ],
)
def test_ua_classify(ua, expected):
    assert ua_class.classify(ua) == expected


# ── session hash ─────────────────────────────────────────────────────────────

def test_session_hash_none_for_missing_ip():
    assert events_service.session_hash_for_ip(None) is None
    assert events_service.session_hash_for_ip("") is None
    assert events_service.session_hash_for_ip("  ") is None


def test_session_hash_changes_with_utc_date(monkeypatch):
    monkeypatch.setattr(config, "EVENTS_IP_SALT", "test-salt")
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "jwt")
    d1 = datetime(2026, 10, 11, tzinfo=timezone.utc)
    d2 = datetime(2026, 10, 12, tzinfo=timezone.utc)
    h1 = events_service.session_hash_for_ip("1.2.3.4", d1)
    h2 = events_service.session_hash_for_ip("1.2.3.4", d2)
    assert h1 and h2 and h1 != h2
    assert "1.2.3.4" not in h1


def test_sanitize_utm_drops_unknown_keys():
    assert events_service.sanitize_utm({"utm_source": "li", "evil": "x"}) == {"utm_source": "li"}
    assert events_service.sanitize_utm("not-json") is None
    assert events_service.sanitize_utm('{"utm_medium":"cpc"}') == {"utm_medium": "cpc"}


# ── POST /events ─────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "FEATURE_S04_EVENTS", True)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    monkeypatch.setattr(config, "MAINTENANCE_READONLY", False)
    sb = MagicMock()
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    monkeypatch.setattr(events_service, "_event_store", lambda: sb)
    from main import app

    return TestClient(app), sb


def test_post_events_flag_off_204(monkeypatch):
    monkeypatch.setattr(config, "FEATURE_S04_EVENTS", False)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    monkeypatch.setattr(config, "MAINTENANCE_READONLY", False)
    from main import app

    with TestClient(app) as c:
        r = c.post("/events", json={"events": [{"event": "view"}]})
    assert r.status_code == 204


def test_post_events_unknown_name_400(client):
    c, sb = client
    r = c.post("/events", json={"events": [{"event": "not_a_real_event"}]})
    assert r.status_code == 400
    sb.table.assert_not_called()


def test_s08_funnel_events_allowlisted(client):
    """S08 step events must be accepted so drop-off can be computed."""
    c, sb = client
    for name in (
        "question_answered",
        "first_win_ask",
        "first_win_looking",
        "first_win_share",
        "first_win_connect",
    ):
        r = c.post("/events", json={"events": [{"event": name, "handle": "alice"}]})
        assert r.status_code == 204, name
    assert sb.table.call_count >= 5


def test_create_page_funnel_events_allowlisted(client):
    """The create page's build started / draft ready / publish clicked steps (cards-web create/)."""
    c, sb = client
    names = ["create_build_started", "create_draft_ready", "create_publish_click"]
    r = c.post("/events", json={"events": [{"event": name, "meta": {"sources": 1}} for name in names]})
    assert r.status_code == 204
    rows = sb.table.return_value.insert.call_args.args[0]
    assert [row["event"] for row in rows] == names


def test_visitor_cta_click_allowlisted_and_stored_with_card_handle(client):
    c, sb = client
    r = c.post("/events", json={"events": [
        {"event": "visitor_cta_click", "handle": "alice", "meta": {"target": "card_bar"}},
    ]})
    assert r.status_code == 204
    rows = sb.table.return_value.insert.call_args.args[0]
    assert rows[0]["event"] == "visitor_cta_click"
    assert rows[0]["handle"] == "alice"
    assert rows[0]["meta"]["target"] == "card_bar"


def test_post_events_batch_too_large_400(client):
    c, sb = client
    r = c.post("/events", json={"events": [{"event": "view"}] * 21})
    assert r.status_code == 400
    sb.table.assert_not_called()


def test_post_events_ok_inserts(client):
    c, sb = client
    r = c.post(
        "/events",
        json={"events": [{"event": "view", "handle": "alice", "meta": {"endpoint": "x"}}]},
        headers={"User-Agent": "Mozilla/5.0 Chrome/120", "X-Forwarded-For": "9.9.9.9"},
    )
    assert r.status_code == 204
    sb.table.assert_called_with("card_events")
    rows = sb.table.return_value.insert.call_args.args[0]
    assert rows[0]["event"] == "view"
    assert rows[0]["actor_class"] == "human"
    assert rows[0]["session_hash"]
    assert "9.9.9.9" not in str(rows)


def test_post_events_rate_limit_429(client, monkeypatch):
    c, _sb = client
    monkeypatch.setattr(events_service, "_MAX_PER_WINDOW", 2)
    headers = {"X-Forwarded-For": "8.8.8.8", "User-Agent": "Mozilla/5.0"}
    assert c.post("/events", json={"events": [{"event": "view"}]}, headers=headers).status_code == 204
    assert c.post("/events", json={"events": [{"event": "view"}]}, headers=headers).status_code == 204
    assert c.post("/events", json={"events": [{"event": "view"}]}, headers=headers).status_code == 429


def _card():
    from models.card import AgentProfileCard

    return AgentProfileCard(
        id="testid",
        status="published",
        handle="alice",
        identity={"name": "Alice", "headline": "Engineer", "location": "", "avatar_url": "", "links": {}},
        summary="Engineer.",
    )


def test_insert_card_attribution_only_on_cards_schema(monkeypatch):
    from services import cards as cards_service

    sb = MagicMock()
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(cards_service.config, "WRITES_OWNER_USER_ID", True)
    monkeypatch.setattr(cards_service, "_assign_handle", lambda *a: "alice")
    monkeypatch.setattr(cards_service.embed, "card_search_text", lambda card: "t")
    monkeypatch.setattr(cards_service.embed, "embed_text", lambda text: [0.1])

    cards_service.insert_card(
        _card(), None, None,
        source="/",
        ref="li",
        utm={"utm_source": "linkedin", "evil": "no"},
        created_via="web",
    )
    row = sb.table.return_value.upsert.call_args.args[0]
    assert row["source"] == "/"
    assert row["ref"] == "li"
    assert row["utm"] == {"utm_source": "linkedin"}
    assert row["created_via"] == "web"


def test_insert_card_skips_attribution_on_public_schema(monkeypatch):
    from services import cards as cards_service

    sb = MagicMock()
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(cards_service.config, "WRITES_OWNER_USER_ID", False)
    monkeypatch.setattr(cards_service, "_assign_handle", lambda *a: "alice")
    monkeypatch.setattr(cards_service.embed, "card_search_text", lambda card: "t")
    monkeypatch.setattr(cards_service.embed, "embed_text", lambda text: [0.1])

    cards_service.insert_card(_card(), None, None, source="/", ref="li", created_via="web")
    row = sb.table.return_value.upsert.call_args.args[0]
    assert "source" not in row
    assert "ref" not in row


def test_emit_swallows_insert_errors(monkeypatch):
    monkeypatch.setattr(config, "FEATURE_S04_EVENTS", True)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")

    def boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(events_service, "_insert_rows", boom)
    # Should not raise
    events_service.emit("agent_fetch", meta={"endpoint": "ask"})


# ── Networking funnel: server-emitted `search` event ────────────────────────────────

def test_search_is_a_server_event_the_public_endpoint_cannot_forge():
    from services import events as events_service
    assert "search" in events_service.SERVER_EVENTS
    assert "search" not in events_service.ALLOWED_EVENTS


def test_agents_search_records_counts_and_handles_but_never_the_query(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import agents as agents_api

    seen = []
    monkeypatch.setattr(agents_api.events_service, "emit", lambda event, **kw: seen.append((event, kw)))
    monkeypatch.setattr(agents_api.search_service, "search_agents", lambda *a: [
        {"handle": f"h{i}", "match_score": 0.9} for i in range(7)])
    monkeypatch.setattr(agents_api.cards_service, "claimed_by_handles", lambda handles: {h: True for h in handles})
    app = FastAPI()
    app.include_router(agents_api.router, prefix="/v1/agents")

    resp = TestClient(app).get("/v1/agents/search", params={"q": "my secret query", "role": "investor", "limit": 7})

    assert resp.status_code == 200
    (event, kw), = seen
    assert event == "search"
    meta = kw["meta"]
    assert {k: meta[k] for k in ("n", "top", "filters", "text")} == {
        "n": 7, "top": ["h0", "h1", "h2", "h3", "h4"], "filters": ["role"], "text": True}
    assert meta["via"] == "web" and meta["search_id"] == resp.json()["search_id"]
    assert "secret" not in repr(kw)


# ── Phase 3.5: search ids, who searched, and what a search led to ──────────────────

def test_search_context_keeps_a_valid_uuid_and_makes_one_otherwise():
    from services import events as events_service
    mine = "3f2b8c4e-6a51-4c43-9d1e-0b5a1f7e2d90"
    assert events_service.search_context(mine, "memory") == (mine, "memory")
    assert events_service.search_context(mine.upper(), "MCP")[0] == mine           # normalised
    for bad in ("", "not-a-uuid", "x" * 64, None):
        sid, via = events_service.search_context(bad, "nonsense")
        assert len(sid) == 36 and sid != mine and via == "web"                      # unknown via: the default
    assert events_service.search_context(None, None, default="ask")[1] == "ask"


def test_result_actions_are_a_server_event_the_public_endpoint_cannot_forge():
    from services import events as events_service
    assert "search_result_action" in events_service.SERVER_EVENTS
    assert "search_result_action" not in events_service.ALLOWED_EVENTS


def test_a_result_action_carries_the_search_never_the_query_or_a_user(monkeypatch):
    from services import events as events_service
    seen = []
    monkeypatch.setattr(events_service, "emit", lambda event, **kw: seen.append((event, kw)))
    sid = "3f2b8c4e-6a51-4c43-9d1e-0b5a1f7e2d90"
    events_service.record_result_action(search_id=sid, rank=2, source="card", action="connect", handle="ada",
                                        connection_id="c-1")
    events_service.record_result_action(search_id=sid, rank=1, source="linkedin", action="invite", handle="grace",
                                        invite_id="i-1")
    events_service.record_result_action(search_id=sid, rank=1, source="made-up", action="connect", handle="x")
    events_service.record_result_action(search_id=sid, rank=1, source="card", action="delete", handle="x")
    assert seen == [
        ("search_result_action", {"handle": "ada", "meta": {"search_id": sid, "rank": 2, "source": "card",
                                                            "action": "connect", "connection_id": "c-1"}}),
        ("search_result_action", {"handle": "grace", "meta": {"search_id": sid, "rank": 1, "source": "linkedin",
                                                              "action": "invite", "invite_id": "i-1"}}),
    ]                                                      # an unknown source or action is dropped


def _agents_client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import agents as agents_api

    seen = []
    monkeypatch.setattr(agents_api.events_service, "emit", lambda event, **kw: seen.append((event, kw)))
    monkeypatch.setattr(agents_api.search_service, "search_agents", lambda *a, **k: [{"handle": "h0", "match_score": 0.9}])
    monkeypatch.setattr(agents_api.lookup_service, "lookup_by_name", lambda *a: [{"handle": "h0"}])
    monkeypatch.setattr(agents_api.lookup_service, "allow", lambda request: True)
    monkeypatch.setattr(agents_api.cards_service, "claimed_by_handles", lambda handles: {h: True for h in handles})
    app = FastAPI()
    app.include_router(agents_api.router, prefix="/v1/agents")
    return TestClient(app), seen


def test_search_and_lookup_echo_the_callers_search_id_and_record_who_searched(monkeypatch):
    client, seen = _agents_client(monkeypatch)
    sid = "3f2b8c4e-6a51-4c43-9d1e-0b5a1f7e2d90"
    one = client.get("/v1/agents/search", params={"q": "x", "search_id": sid, "via": "memory"}).json()
    two = client.get("/v1/agents/lookup", params={"name": "chandan", "search_id": sid, "via": "mcp"}).json()
    assert one["search_id"] == two["search_id"] == sid
    assert [(e, kw["meta"]["search_id"], kw["meta"]["via"]) for e, kw in seen] == [
        ("search", sid, "memory"), ("search", sid, "mcp")]


def test_ask_is_counted_as_a_search_of_its_own_kind(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import ask as ask_api

    seen = []
    monkeypatch.setattr(ask_api.events_service, "emit", lambda event, **kw: seen.append((event, kw)))
    monkeypatch.setattr(ask_api.search_service, "search_agents", lambda *a, **k: [{"handle": "h0"}])
    monkeypatch.setattr(ask_api.cards_service, "claimed_by_handles", lambda handles: {h: True for h in handles})
    app = FastAPI()
    app.include_router(ask_api.router, prefix="/ask")
    client = TestClient(app)
    body = client.get("/ask", params={"q": "find a rust dev"}).json()
    web = client.post("/ask", params={"via": "web"}, json={"q": "x"}).json()
    searches = [kw["meta"] for e, kw in seen if e == "search"]
    assert [m["via"] for m in searches] == ["ask", "web"] and len(body["search_id"]) == 36 and web["search_id"]
    assert "rust" not in repr(searches)
