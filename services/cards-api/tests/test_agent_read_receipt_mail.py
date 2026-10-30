from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
from api.internal import router
from services import owner_notifications as notes, profile_feedback as feedback, read_receipt_topics as topics

NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)
AUTH = {"Authorization": "Bearer test-cron"}


@pytest.fixture
def mail(monkeypatch):
    for key, value in {"CRON_SECRET": "test-cron", "FEATURE_S10_HOME": True,
                       "SUPABASE_DB_SCHEMA": "cards", "FEATURE_S10_DIGEST": True,
                       "SMTP_HOST": "smtp.test", "SMTP_FROM": "team@example.com",
                       "OPENROUTER_API_KEY": ""}.items():
        monkeypatch.setattr(config, key, value)
    row = {"id": "c1", "handle": "alice", "owner_email": "alice@example.com", "status": "published",
           "created_at": (NOW - timedelta(days=4)).isoformat(), "unsubscribe_token": "unsub",
           "card": {"identity": {"name": "Alice Chen"}},
           "notification_prefs": {"weekly_digest": True, "email_nudges": False}}
    data = {"handle": "alice", "name": "Alice Chen", "activity": {
        "available": True, "views": 2, "agent_hits": 14, "queries": [],
        "chat_questions": [{"question": "Does Alice use Rust? Email me at private@example.com", "category": "skills"}]},
        "inbox_count": 0, "completeness": {"score": 80}, "nudges": [],
        "notification_prefs": row["notification_prefs"]}
    adapter = MagicMock(enabled=True)
    monkeypatch.setattr(notes, "get_mailer", lambda: adapter)
    rows = MagicMock(return_value=[row])
    monkeypatch.setattr(notes, "notification_rows", rows)
    monkeypatch.setattr(notes.owner_home, "status", AsyncMock(return_value=data))
    monkeypatch.setattr(notes.owner_home, "current_row", lambda email: row)
    claims = set()

    def claim(email, kind, period):
        key = (email, kind, period)
        if key in claims:
            return None
        claims.add(key)
        return "delivery-1"

    monkeypatch.setattr(notes, "claim_delivery", claim)
    sb = MagicMock()
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    app = FastAPI()
    app.include_router(router, prefix="/internal")
    return SimpleNamespace(row=row, data=data, adapter=adapter, claims=claims, rows=rows,
                           sb=sb, client=TestClient(app))


@pytest.mark.parametrize("endpoint", ["weekly-agent-digest", "profile-feedback"])
def test_mail_endpoints_require_cron_before_scanning_or_sending(mail, endpoint):
    assert mail.client.post("/internal/" + endpoint).status_code == 401
    mail.rows.assert_not_called()
    mail.adapter.send.assert_not_called()


@pytest.mark.asyncio
async def test_weekly_endpoint_shares_deduplication_and_respects_dashboard_preference(mail, monkeypatch):
    render = MagicMock(wraps=notes.render_weekly)
    monkeypatch.setattr(notes, "render_weekly", render)
    response = mail.client.post("/internal/weekly-agent-digest", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["sent"] == 1
    message = mail.adapter.send.call_args.kwargs
    assert "14 agent hits" in message["body"]
    assert "profile-assistant questions" in message["body"]
    assert "private@example.com" not in message["body"]
    assert "[redacted]" in message["body"]
    assert "Topics asked about in your profile assistant: Skills" in message["body"]
    assert message["unsubscribe_url"].endswith("/unsub")
    # Existing scheduled job uses the same weekly claim as the new endpoint.
    await notes.run_notifications()
    mail.adapter.send.assert_called_once()
    render.assert_called_once()
    mail.row["notification_prefs"]["weekly_digest"] = False
    await notes.run_notifications(now=NOW + timedelta(days=14), weekly_only=True)
    mail.adapter.send.assert_called_once()


@pytest.mark.asyncio
async def test_weekly_only_does_not_send_nudges_and_rechecks_consent(mail, monkeypatch):
    mail.row["notification_prefs"]["email_nudges"] = True
    mail.data["nudges"] = [{"title": "Review facts", "created_at": NOW.isoformat()}]
    monkeypatch.setattr(notes.owner_home, "current_row", lambda email: {
        **mail.row, "notification_prefs": {"weekly_digest": False, "email_nudges": True}})
    result = await notes.run_notifications(now=NOW, weekly_only=True)
    assert result["sent"] == 0
    assert result["skipped"] == 1
    mail.adapter.send.assert_not_called()
    assert len(mail.claims) == 1


def test_feedback_endpoint_dry_run_does_not_claim_or_send(mail):
    response = mail.client.post("/internal/profile-feedback?dry_run=true", headers=AUTH)
    assert response.status_code == 200
    preview = response.json()["previews"][0]
    assert preview["subject"] == feedback.SUBJECT
    assert "Hey Alice," in preview["body"]
    assert feedback.CALENDAR_URL in preview["body"] and feedback.FORM_URL in preview["body"]
    assert not mail.claims
    mail.adapter.send.assert_not_called()


@pytest.mark.asyncio
async def test_feedback_sends_once_per_owner_even_across_weeks_and_duplicate_cards(mail):
    mail.rows.return_value = [mail.row, {**mail.row, "id": "duplicate", "owner_email": "ALICE@example.com"}]
    first = await feedback.run_feedback(now=NOW)
    second = await feedback.run_feedback(now=NOW + timedelta(days=14))
    assert first["sent"] == 1 and second["sent"] == 0
    mail.adapter.send.assert_called_once()
    assert mail.claims == {("alice@example.com", "profile_feedback", "once")}


@pytest.mark.parametrize("reason", ["new", "opted_out", "private", "other_recipient"])
@pytest.mark.asyncio
async def test_feedback_skips_ineligible_owners(mail, reason):
    if reason == "new":
        mail.row["created_at"] = (NOW - timedelta(days=2)).isoformat()
    if reason == "opted_out":
        mail.row["notification_prefs"] = {"weekly_digest": False, "email_nudges": False}
    if reason == "private":
        mail.row["status"] = "private"
    await feedback.run_feedback(now=NOW, email="other@example.com" if reason == "other_recipient" else None)
    assert not mail.claims
    mail.adapter.send.assert_not_called()


@pytest.mark.asyncio
async def test_feedback_failure_is_not_automatically_resent(mail):
    mail.adapter.send.side_effect = RuntimeError("ambiguous SMTP failure")
    assert (await feedback.run_feedback(now=NOW))["failed"] == 1
    assert (await feedback.run_feedback(now=NOW))["skipped"] == 1
    mail.adapter.send.assert_called_once()


@pytest.mark.asyncio
async def test_feedback_rechecks_opt_out_before_smtp(mail, monkeypatch):
    monkeypatch.setattr(notes.owner_home, "current_row", lambda email: {
        **mail.row, "notification_prefs": {"weekly_digest": False, "email_nudges": False}})
    result = await feedback.run_feedback(now=NOW)
    assert result["sent"] == 0 and result["skipped"] == 1
    assert len(mail.claims) == 1
    mail.adapter.send.assert_not_called()


def test_topics_are_grounded_in_questions_and_never_invented(mail, monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test")
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content='{"topics":["Rust","Not mentioned","Alice","[redacted]"]}'))])
    monkeypatch.setattr(config, "get_llm_client", lambda: client)
    insights = topics.question_insights(mail.data["activity"], "Alice Chen")
    assert insights["topics"] == ["Rust"]
    assert "private@example.com" not in str(client.chat.completions.create.call_args)
    client.chat.completions.create.side_effect = RuntimeError("offline")
    assert topics.question_insights(mail.data["activity"])["topics"] == ["Skills"]
    client.reset_mock()
    assert topics.question_insights({}) == {"questions": [], "topics": []}
    client.chat.completions.create.assert_not_called()


def test_feedback_html_escapes_recipient_and_includes_requested_links():
    body, markup = feedback.render_feedback("<Alice> Chen", "https://cards.test/unsubscribe")
    assert "Hey <Alice>," in body
    assert "Hey &lt;Alice&gt;," in markup and "<Alice>" not in markup
    assert f'href="{feedback.CALENDAR_URL}"' in markup
    assert f'href="{feedback.FORM_URL}"' in markup


def test_weekly_digest_includes_matches_without_sending_intro_requests(mail):
    mail.data["suggestions"] = {"people": [{"name": "Sarah <Founder>", "handle": "sarah",
        "why": ["Looking for go-to-market help"]}]}
    body, markup = notes.render_weekly(mail.data, None)
    assert "Zynd matches" in body and "Looking for go-to-market help" in body
    assert "https://cards.zynd.ai/home#zynd-matches" in body + markup
    assert "Sarah &lt;Founder&gt;" in markup and "Sarah <Founder>" not in markup
    assert "they decide whether to connect" in markup
    assert body.index("Zynd matches") < body.index("human views") < body.index("People who visited")
    assert markup.index("Zynd matches</h2>") < markup.index("Human audience") < markup.index("People who viewed your profile")
    assert markup.count("Zynd matches</h2>") == 1
    assert 'href="https://cards.zynd.ai/p/sarah"' in markup
    assert 'WHY CONNECT' in markup
    mail.adapter.send.assert_not_called()
    mail.sb.table.assert_not_called()


def test_weekly_recipient_filter_never_sends_to_other_owners(mail):
    mail.rows.return_value = [{**mail.row, "id": "other", "owner_email": "other@example.com"}, mail.row]
    response = mail.client.post("/internal/weekly-agent-digest?email=ALICE%40example.com", headers=AUTH)
    assert response.status_code == 200 and response.json()["sent"] == 1
    mail.adapter.send.assert_called_once()
    assert mail.adapter.send.call_args.kwargs["to"] == "alice@example.com"
    notes.owner_home.status.assert_awaited_once_with("alice@example.com", persist=True)
    assert all(key[0] == "alice@example.com" for key in mail.claims)


@pytest.mark.parametrize("email,expected", [("not-an-email", 422), ("", 422), ("missing@example.com", 404)])
def test_weekly_invalid_or_missing_owner_never_sends(mail, email, expected):
    response = mail.client.post("/internal/weekly-agent-digest", params={"email": email}, headers=AUTH)
    assert response.status_code == expected
    mail.adapter.send.assert_not_called()


@pytest.mark.parametrize("endpoint,kind", [("weekly-agent-digest", "weekly"), ("profile-feedback", "feedback")])
def test_explicit_test_endpoints_resend_without_changing_real_delivery_state(mail, endpoint, kind):
    mail.row["notification_prefs"] = {"weekly_digest": False, "email_nudges": False}
    mail.data["notification_prefs"] = mail.row["notification_prefs"]
    mail.row["created_at"] = NOW.isoformat()  # The feedback age restriction is bypassed too.
    mail.claims.update({("alice@example.com", "weekly", notes.week_key(NOW)),
                        ("alice@example.com", "profile_feedback", "once")})
    existing_claims = mail.claims.copy()
    for _ in range(2):
        response = mail.client.post(f"/internal/{endpoint}/test?email=alice@example.com", headers=AUTH)
        assert response.status_code == 200
        assert response.json() == {"sent": 1, "to": "alice@example.com", "kind": kind, "test": True}
    assert mail.adapter.send.call_count == 2
    assert mail.claims == existing_claims
    mail.sb.table.assert_not_called()
    message = mail.adapter.send.call_args.kwargs
    assert message["subject"].startswith("[TEST]")
    assert message["unsubscribe_url"] is None
    assert "email preferences and delivery limits were bypassed" in message["body"]
    if kind == "feedback":
        assert feedback.CALENDAR_URL in message["body"] and feedback.FORM_URL in message["body"]


@pytest.mark.parametrize("endpoint", ["weekly-agent-digest", "profile-feedback"])
def test_resend_endpoints_require_authorization_and_validate_recipient(mail, endpoint):
    path = f"/internal/{endpoint}/test"
    assert mail.client.post(path, params={"email": "alice@example.com"}).status_code == 401
    if endpoint == "weekly-agent-digest":
        assert mail.client.post(path, headers=AUTH).status_code == 422
    assert mail.client.post(path, params={"email": "bad"}, headers=AUTH).status_code == 422
    notes.owner_home.status.assert_not_called()
    mail.adapter.send.assert_not_called()


def test_weekly_includes_client_names_consented_people_and_latest_five_questions(mail):
    mail.data["activity"]["agent_clients"] = [
        {"provider": "ChatGPT / OpenAI", "name": "ChatGPT-User", "count": 8},
        {"provider": "Claude", "name": "Claude-MCP", "count": 5},
        {"provider": "Unidentified MCP client", "name": "Zynd-MCP", "count": 1},
    ]
    mail.data["visitors"] = {"available": True, "items": [
        {"name": "Sam Rivera", "visits": 2, "email": "private-visitor@example.com"},
        {"name": "<img src=x onerror=bad>", "visits": 1},
    ]}
    mail.data["activity"]["chat_questions"] = [
        {"question": f"Latest question about library_{i}?", "category": "skills"} for i in range(7)]
    body, markup = notes.render_weekly(mail.data, None)
    for text in ["ChatGPT / OpenAI — ChatGPT-User: 8 requests", "Claude — Claude-MCP: 5 requests",
                 "Unidentified MCP client — Zynd-MCP: 1 request", "Sam Rivera (2 visits)"]:
        assert text in body
    for text in ["ChatGPT / OpenAI", "ChatGPT-User", "8 requests", "Claude-MCP", "5 requests", "Zynd-MCP", "1 request", "Sam Rivera", "2 visits"]:
        assert text in markup
    for i in range(5):
        assert f"Latest question about library_{i}?" in body
        assert f"Latest question about library_{i}?" in markup
    assert "library_5" not in body and "library_6" not in markup
    assert "private-visitor@example.com" not in body + markup
    assert "<img src=x" not in markup and "&lt;img src=x" in markup
    assert "Names appear only for visitors who chose to share them" in body


def test_weekly_does_not_expose_unavailable_visitor_data_or_invent_agent_names(mail):
    mail.data["visitors"] = {"available": False, "items": [{"name": "Do not disclose"}]}
    body, markup = notes.render_weekly(mail.data, None)
    assert "Do not disclose" not in body + markup
    assert "Visitor names are unavailable." in body
    assert "Agent client identities are unavailable." in body
    assert "ChatGPT" not in body and "Claude" not in body


def test_weekly_email_design_is_self_contained_and_places_people_before_agents(mail, monkeypatch):
    monkeypatch.setattr(config, "SITE_BASE_URL", "https://cards.test")
    body, markup = notes.render_weekly(mail.data, "https://cards.test/unsubscribe")
    assert body.index("People who visited") < body.index("AI clients that accessed")
    assert markup.index("People who viewed your profile") < markup.index("AI clients that accessed")
    assert 'role="presentation"' in markup and "max-width:800px" in markup
    assert 'href="https://cards.zynd.ai/home"' in markup
    assert "Owner home: https://cards.zynd.ai/home" in body
    assert "https://cards.test/home" not in body + markup
    assert 'href="https://cards.test/p/alice"' in markup
    assert 'href="https://cards.test/unsubscribe"' in markup
    assert "<script" not in markup and "tailwindcss" not in markup
    assert 'href="#"' not in markup and "zynd.id" not in markup
    assert "Unique browser" not in markup and "+14%" not in markup


def test_weekly_zero_traffic_has_no_fake_percentages_or_counts(mail):
    mail.data["activity"].update({"views": 0, "agent_hits": 0, "agent_clients": [], "chat_questions": []})
    mail.data["visitors"] = {"available": True, "items": []}
    _, markup = notes.render_weekly(mail.data, None)
    assert "No AI client requests recorded this week." in markup
    assert "No visitors chose to share their name this week." in markup
    assert "% of listed requests" not in markup
    assert "No profile-assistant questions recorded this week." in markup
    assert "Zynd matches</h2>" not in markup


def test_feedback_design_has_both_actions_and_real_profile_and_preferences_links():
    body, markup = feedback.render_feedback("Alice Chen", "https://cards.test/unsubscribe", handle="alice")
    assert "Hey Alice," in body and "Hey Alice," in markup
    assert "Would you be open to a quick 15-minute call with us?" in markup
    assert markup.index("Book a quick chat") < markup.index("Share your thoughts")
    assert f'href="{feedback.CALENDAR_URL}"' in markup
    assert f'href="{feedback.FORM_URL}"' in markup
    assert 'href="https://cards.zynd.ai/p/alice"' in markup
    assert 'href="https://cards.zynd.ai/home"' in markup
    assert 'href="https://cards.test/unsubscribe"' in markup
    assert 'role="presentation"' in markup and "max-width:640px" in markup
    assert "<script" not in markup and "tailwindcss" not in markup and 'href="#"' not in markup
    assert "firewalls" not in markup and "Google Meet" not in markup
    assert "delivery limits were bypassed" not in markup


def test_feedback_test_notice_is_inside_email_footer_with_no_live_unsubscribe():
    notice = "Test email requested manually; email preferences and delivery limits were bypassed."
    _, markup = feedback.render_feedback("Alice", None, handle="alice", preview_label=notice)
    assert notice in markup
    assert markup.index(notice) < markup.index("</body>")
    assert "Unsubscribe" not in markup and "Preview only" not in markup


def test_weekly_visitor_links_use_only_available_consented_profile_handles(mail):
    mail.data["visitors"] = {"available": True, "items": [
        {"name": "Sam Rivera", "handle": "sam-rivera", "visits": 2},
        {"name": "No published profile", "handle": None, "visits": 1},
        {"name": "Empty handle", "handle": " ", "visits": 1},
    ]}
    body, markup = notes.render_weekly(mail.data, None)
    url = "https://cards.zynd.ai/p/sam-rivera"
    assert f"Sam Rivera (2 visits) — {url}" in body
    assert f'href="{url}"' in markup
    assert "View profile &rarr;" in markup
    assert "No published profile (1 visit) —" not in body
    assert "Empty handle (1 visit) —" not in body
    mail.data["visitors"]["available"] = False
    body, markup = notes.render_weekly(mail.data, None)
    assert url not in body + markup and "Sam Rivera" not in body + markup


def test_visitor_profile_handles_cannot_inject_link_attributes():
    from services.weekly_email import visitor_profile_url
    assert visitor_profile_url({"handle": 'sam/" onmouseover="bad'}) == 'https://cards.zynd.ai/p/sam%2F%22%20onmouseover%3D%22bad'
    assert visitor_profile_url({"handle": None}) is None


@pytest.mark.asyncio
async def test_weekly_stays_enabled_with_legacy_flag_off_and_preserves_opt_out_and_limits(mail, monkeypatch):
    monkeypatch.setattr(config, "FEATURE_S10_DIGEST", False)
    mail.row["notification_prefs"]["email_nudges"] = True
    mail.data["nudges"] = [{"title": "A legacy nudge", "created_at": NOW.isoformat()}]
    first = await notes.run_notifications(now=NOW)
    assert first["sent"] == 1
    assert mail.claims == {("alice@example.com", "weekly", notes.week_key(NOW))}
    assert (await notes.run_notifications(now=NOW, weekly_only=True))["sent"] == 0
    mail.row["notification_prefs"]["weekly_digest"] = False
    assert (await notes.run_notifications(now=NOW + timedelta(days=7), weekly_only=True))["sent"] == 0
    mail.adapter.send.assert_called_once()
