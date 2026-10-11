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
