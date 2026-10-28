"""AI-read alert email: trigger, eligibility, opt-out, throttle, and isolation from ingest."""
import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import config
from services import ai_read_alerts
from services import events as events_service
from tests.fake_supabase import FakeSupabase

OWNER = "alice@example.com"
TOKEN = "00000000-0000-4000-8000-000000000001"
REAL_SUBMIT = ai_read_alerts._submit
CLAUDE_UA = "Mozilla/5.0 (compatible; Claude-User/1.0; +https://anthropic.com)"


class RecordingMailer:
    enabled = True

    def __init__(self, error: Exception | None = None):
        self.sent: list[dict] = []
        self.error = error

    def send(self, **message) -> None:
        if self.error:
            raise self.error
        self.sent.append(message)


def card(**overrides) -> dict:
    return {"handle": "alice", "status": "published", "owner_email": OWNER, "unsubscribe_token": TOKEN,
            "notification_prefs": {"weekly_digest": True, "email_nudges": False, "morning_digest": True},
            "card": {"identity": {"name": "Alice Example"}}, **overrides}


def ai_read(handle: str = "alice", event: str = "agent_fetch", actor: str = "ai_agent",
            agent: str | None = "Claude-User") -> dict:
    return {"event": event, "handle": handle, "actor_class": actor, "meta": {"agent_name": agent} if agent else None}


def alerts(db: FakeSupabase) -> list[dict]:
    return [r for r in db.rows("card_events") if r["event"] == events_service.AI_READ_ALERT_EVENT]


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(config, "FEATURE_AI_READ_ALERTS", True)
    monkeypatch.setattr(config, "AI_READ_ALERT_COOLDOWN_HOURS", 24)
    monkeypatch.setattr(config, "FEATURE_S04_EVENTS", True)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    monkeypatch.setattr(config, "MAINTENANCE_READONLY", False)
    monkeypatch.setattr(config, "SITE_BASE_URL", "https://zynd.ai")
    monkeypatch.setattr(config, "API_BASE_URL", "https://api.zynd.ai")
    db = FakeSupabase(agent_profile_cards=[card()], card_events=[])
    monkeypatch.setattr(config, "get_supabase", lambda: db)
    monkeypatch.setattr(events_service, "_event_store", lambda: db)
    mailer = RecordingMailer()
    monkeypatch.setattr(ai_read_alerts, "get_mailer", lambda: mailer)
    # Run the background check inline so each test sees its result.
    monkeypatch.setattr(ai_read_alerts, "_submit", lambda fn, *args: fn(*args))
    ai_read_alerts._inflight.clear()
    ai_read_alerts._quiet_until.clear()
    events_service._hits.clear()
    yield db, mailer
    ai_read_alerts._inflight.clear()
    ai_read_alerts._quiet_until.clear()
    events_service._hits.clear()


def test_flag_off_is_a_no_op(world, monkeypatch):
    db, mailer = world
    monkeypatch.setattr(config, "FEATURE_AI_READ_ALERTS", False)
    submitted = []
    monkeypatch.setattr(ai_read_alerts, "_submit", lambda *args: submitted.append(args))
    assert events_service._insert_rows([ai_read()]) is True
    assert submitted == [] and mailer.sent == [] and alerts(db) == []


@pytest.mark.parametrize("actor", ["search_bot", "unknown", "human"])
def test_non_ai_reads_do_not_alert(world, actor):
    db, mailer = world
    ai_read_alerts.schedule([ai_read(actor=actor)])
    assert mailer.sent == [] and alerts(db) == []


def test_other_events_do_not_alert(world):
    db, mailer = world
    ai_read_alerts.schedule([ai_read(event="share_click"), ai_read(event="chat_message")])
    assert mailer.sent == [] and alerts(db) == []


def test_unclaimed_card_does_not_alert(world):
    db, mailer = world
    db.tables["agent_profile_cards"] = [card(owner_email=None)]
    assert ai_read_alerts.deliver("alice", "Claude-User") == "ineligible"
    assert mailer.sent == [] and alerts(db) == []


def test_unpublished_or_missing_card_does_not_alert(world):
    db, mailer = world
    db.tables["agent_profile_cards"] = [card(status="draft")]
    assert ai_read_alerts.deliver("alice", "Claude-User") == "ineligible"
    assert ai_read_alerts.deliver("nobody", "Claude-User") == "ineligible"
    assert mailer.sent == []


def test_owner_who_turned_the_digest_off_gets_nothing(world):
    db, mailer = world
    db.tables["agent_profile_cards"] = [card(notification_prefs={"weekly_digest": False, "email_nudges": False,
                                                                 "morning_digest": False})]
    assert ai_read_alerts.deliver("alice", "Claude-User") == "opted_out"
    assert mailer.sent == [] and alerts(db) == []


def test_no_unsubscribe_token_means_no_email(world):
    db, mailer = world
    db.tables["agent_profile_cards"] = [card(unsubscribe_token=None)]
    assert ai_read_alerts.deliver("alice", "Claude-User") == "opted_out"
    assert mailer.sent == []


def test_noop_mailer_does_not_spend_the_cooldown(world, monkeypatch):
    db, _ = world

    class Off:
        enabled = False

    monkeypatch.setattr(ai_read_alerts, "get_mailer", lambda: Off())
    assert ai_read_alerts.deliver("alice", "Claude-User") == "no_mailer"
    assert alerts(db) == []


def test_sends_once_then_throttled_within_cooldown(world):
    db, mailer = world
    read_at = datetime(2026, 10, 28, 14, 5, tzinfo=timezone.utc)
    assert ai_read_alerts.deliver("alice", "Claude-User", read_at) == "sent"
    assert ai_read_alerts.deliver("alice", "GPTBot", read_at + timedelta(hours=23)) == "throttled"
    assert len(mailer.sent) == 1 and len(alerts(db)) == 1

    message = mailer.sent[0]
    unsubscribe = f"https://api.zynd.ai/cards/notifications/unsubscribe/{TOKEN}"
    assert message["to"] == OWNER
    assert message["subject"] == "Claude just read your Zynd card"
    assert message["unsubscribe_url"] == unsubscribe
    for text in ("Hi Alice,", "Claude (Claude-User), as reported by the client", "28 Oct 2026, 14:05 UTC",
                 "https://zynd.ai/p/alice", "See who found you: https://zynd.ai/home",
                 "Client names are self-reported, not verified.", unsubscribe):
        assert text in message["body"]
    for text in ("Claude just read your Zynd card", "as reported by the client", 'href="https://zynd.ai/home"',
                 "Client names are self-reported, not verified.", f'href="{unsubscribe}"'):
        assert text in message["html"]
    marker = alerts(db)[0]
    assert marker["handle"] == "alice" and marker["meta"] == {"agent_name": "Claude-User"}


def test_sends_again_after_cooldown(world):
    db, mailer = world
    read_at = datetime(2026, 10, 28, 14, 5, tzinfo=timezone.utc)
    assert ai_read_alerts.deliver("alice", "Claude-User", read_at) == "sent"
    assert ai_read_alerts.deliver("alice", "GPTBot", read_at + timedelta(hours=24, minutes=1)) == "sent"
    assert [m["subject"] for m in mailer.sent] == ["Claude just read your Zynd card",
                                                   "ChatGPT / OpenAI just read your Zynd card"]
    assert len(alerts(db)) == 2


def test_cooldown_is_per_card(world):
    db, mailer = world
    db.tables["agent_profile_cards"].append(card(handle="bob", owner_email="bob@example.com"))
    assert ai_read_alerts.deliver("alice", "Claude-User") == "sent"
    assert ai_read_alerts.deliver("bob", "Claude-User") == "sent"
    assert [m["to"] for m in mailer.sent] == [OWNER, "bob@example.com"]


def test_burst_of_reads_checks_the_card_once(world, monkeypatch):
    db, mailer = world
    submitted = []
    monkeypatch.setattr(ai_read_alerts, "_submit", lambda fn, *args: submitted.append(args))
    ai_read_alerts.schedule([ai_read(), ai_read(event="view")])
    ai_read_alerts.schedule([ai_read(agent="GPTBot")])
    assert len(submitted) == 1


def test_after_a_send_the_card_skips_lookups_for_the_cooldown(world):
    db, mailer = world
    ai_read_alerts.schedule([ai_read()])
    db.tables["card_events"].clear()
    ai_read_alerts.schedule([ai_read()])
    assert len(mailer.sent) == 1 and alerts(db) == []


def test_unattributed_agent_gets_a_generic_subject(world):
    db, mailer = world
    assert ai_read_alerts.deliver("alice", "Zynd-MCP") == "sent"
    assert mailer.sent[0]["subject"] == "An AI agent just read your Zynd card"
    assert "Unidentified MCP client (Zynd-MCP), as reported by the client" in mailer.sent[0]["body"]


def test_real_background_pool_sends_off_the_calling_thread(world, monkeypatch):
    db, mailer = world
    monkeypatch.setattr(ai_read_alerts, "_submit", REAL_SUBMIT)
    monkeypatch.setattr(ai_read_alerts, "_pool", None)
    ai_read_alerts.schedule([ai_read()])
    ai_read_alerts._pool.shutdown(wait=True)
    assert len(mailer.sent) == 1 and len(alerts(db)) == 1


def test_ai_read_through_post_events_sends_the_alert(world):
    db, mailer = world
    from main import app

    response = TestClient(app).post("/events", json={"events": [{"event": "agent_fetch", "handle": "alice"}]},
                                    headers={"User-Agent": CLAUDE_UA})
    assert response.status_code == 204
    assert [m["subject"] for m in mailer.sent] == ["Claude just read your Zynd card"]
    assert len(alerts(db)) == 1


def test_mailer_exception_does_not_break_ingest(world, monkeypatch, caplog):
    db, _ = world
    monkeypatch.setattr(ai_read_alerts, "get_mailer", lambda: RecordingMailer(error=RuntimeError(f"refused {OWNER}")))
    from main import app

    with caplog.at_level(logging.INFO):
        response = TestClient(app).post("/events", json={"events": [{"event": "agent_fetch", "handle": "alice"}]},
                                        headers={"User-Agent": CLAUDE_UA})
    assert response.status_code == 204
    assert any(r["event"] == "agent_fetch" for r in db.rows("card_events"))
    # The window was claimed before sending, so a failed send is not retried on every read.
    assert len(alerts(db)) == 1
    assert "ai read alert send failed handle=alice err=RuntimeError" in caplog.text
    assert OWNER not in caplog.text


def test_lookup_failure_does_not_break_ingest(world, monkeypatch):
    db, mailer = world

    def broken(handle):
        raise RuntimeError("db down")

    monkeypatch.setattr(ai_read_alerts, "_owner_row", broken)
    assert events_service._insert_rows([ai_read()]) is True
    assert mailer.sent == []
    assert "alice" not in ai_read_alerts._inflight and "alice" not in ai_read_alerts._quiet_until


def test_public_post_events_cannot_forge_the_throttle(world):
    db, _ = world
    from main import app

    response = TestClient(app).post("/events", json={"events": [{"event": events_service.AI_READ_ALERT_EVENT,
                                                                  "handle": "alice"}]})
    assert response.status_code == 400
    assert alerts(db) == []
