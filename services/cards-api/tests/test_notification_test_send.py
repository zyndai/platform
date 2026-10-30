"""Test-send stays recipient-scoped and never consumes scheduled deliveries."""
import smtplib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
from api.internal import router
from services import owner_notifications as notifications


@pytest.fixture
def test_send(monkeypatch):
    monkeypatch.setattr(config, "CRON_SECRET", "test-cron")
    monkeypatch.setattr(config, "FEATURE_S10_HOME", True)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    monkeypatch.setattr(config, "FEATURE_S10_DIGEST", False)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(config, "SMTP_FROM", "test@example.com")
    data = {
        "handle": "alice", "name": "Alice", "activity": {"available": False, "queries": []},
        "inbox_count": 0, "completeness": {"score": 80}, "nudges": [],
        "notification_prefs": {"weekly_digest": False, "email_nudges": False},
    }
    status = AsyncMock(return_value=data)
    adapter = SimpleNamespace(enabled=True, send=MagicMock())
    claim = MagicMock(side_effect=AssertionError("Test sends must not claim deliveries"))
    db = MagicMock(side_effect=AssertionError("No global scan or delivery writes"))
    monkeypatch.setattr(notifications.owner_home, "status", status)
    monkeypatch.setattr(notifications, "get_mailer", lambda: adapter)
    monkeypatch.setattr(notifications, "claim_delivery", claim)
    monkeypatch.setattr(config, "get_supabase", db)
    app = FastAPI()
    app.include_router(router, prefix="/internal")
    return TestClient(app), status, adapter, claim, db


URL = "/internal/owner-notifications/test"
AUTH = {"Authorization": "Bearer test-cron"}


def post(client, *, params=None, **kwargs):
    return client.post(URL, params={"email": "alice@example.com", **(params or {})}, **kwargs)


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_requires_cron_secret_before_loading_or_sending(test_send, headers):
    client, status, adapter, _, _ = test_send
    assert post(client, headers=headers).status_code == 401
    status.assert_not_called()
    adapter.send.assert_not_called()


@pytest.mark.parametrize("kind", ["weekly", "reminder"])
def test_repeat_send_bypasses_preferences_and_delivery_limits(test_send, kind):
    client, status, adapter, claim, db = test_send
    for _ in range(2):
        response = post(client, params={"kind": kind, "email": "alice@example.com"}, headers=AUTH)
        assert response.status_code == 200
        assert response.json() == {"sent": 1, "to": "alice@example.com", "kind": kind, "test": True}
    assert status.await_count == 2
    status.assert_awaited_with("alice@example.com", persist=False)
    assert adapter.send.call_count == 2
    message = adapter.send.call_args.kwargs
    assert message["to"] == "alice@example.com"
    assert message["subject"].startswith("[TEST]")
    assert message["unsubscribe_url"] is None
    assert "preferences and delivery limits were bypassed" in message["body"]
    assert "Preview only" not in message["html"]
    if kind == "reminder":
        assert "Sample reminder" in message["body"]
    claim.assert_not_called()
    db.assert_not_called()


def test_reminder_uses_actual_eligible_nudges(test_send):
    client, status, adapter, _, _ = test_send
    status.return_value["nudges"] = [{"title": "Review <Python> facts"}]
    assert post(client, params={"kind": "reminder"}, headers=AUTH).status_code == 200
    message = adapter.send.call_args.kwargs
    assert "Review <Python> facts" in message["body"]
    assert "Review &lt;Python&gt; facts" in message["html"]
    assert "Sample reminder" not in message["body"]


@pytest.mark.parametrize("email", ["", "not-an-email", "alice@example.com\r\nBcc:victim@example.com"])
def test_invalid_recipient_never_sends(test_send, email):
    client, status, adapter, _, _ = test_send
    assert post(client, params={"email": email}, headers=AUTH).status_code == 422
    status.assert_not_called()
    adapter.send.assert_not_called()


def test_noop_mailer_reports_configuration_error(test_send):
    client, status, adapter, _, _ = test_send
    adapter.enabled = False
    response = post(client, headers=AUTH)
    assert response.status_code == 503
    assert "S10_MAILER=smtp" in response.json()["detail"]
    status.assert_not_called()
    adapter.send.assert_not_called()


def test_owner_without_card_is_not_sent_mail(test_send):
    client, status, adapter, _, _ = test_send
    status.return_value = None
    assert post(client, headers=AUTH).status_code == 404
    adapter.send.assert_not_called()


@pytest.mark.parametrize("kind", ["all", "unknown"])
def test_invalid_kind_is_rejected(test_send, kind):
    client, status, adapter, _, _ = test_send
    assert post(client, params={"kind": kind}, headers=AUTH).status_code == 422
    status.assert_not_called()
    adapter.send.assert_not_called()


def test_smtp_failure_is_actionable_without_exposing_provider_text(test_send):
    client, _, adapter, _, _ = test_send
    adapter.send.side_effect = smtplib.SMTPAuthenticationError(535, b"secret provider details")
    response = post(client, headers=AUTH)
    assert response.status_code == 502
    assert "authentication failed" in response.json()["detail"]
    assert "secret provider details" not in response.text


def test_database_failure_is_reported_without_sending(test_send):
    client, status, adapter, _, _ = test_send
    status.side_effect = RuntimeError("private database details")
    response = post(client, headers=AUTH)
    assert response.status_code == 503
    assert "private database details" not in response.text
    adapter.send.assert_not_called()


@pytest.mark.parametrize("unsubscribe", [None, "https://api.test/unsubscribe/token"])
def test_smtp_headers_distinguish_explicit_tests_from_scheduled_mail(test_send, monkeypatch, unsubscribe):
    from services.mailer import SmtpMailer
    smtp = MagicMock()
    monkeypatch.setattr(smtplib, "SMTP", smtp)
    SmtpMailer().send(to="alice@example.com", subject="Test", body="Text", html="<p>Text</p>", unsubscribe_url=unsubscribe)
    transport = smtp.return_value.__enter__.return_value
    transport.starttls.assert_called_once()
    message = transport.send_message.call_args.args[0]
    if unsubscribe:
        assert message["List-Unsubscribe"] == f"<{unsubscribe}>"
        assert message["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    else:
        assert message["List-Unsubscribe"] is None
        assert message["List-Unsubscribe-Post"] is None


def test_selected_address_is_normalized_and_is_only_recipient(test_send):
    client, status, adapter, _, db = test_send
    response = post(client, params={"email": "  Bob@Example.com  "}, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["to"] == "bob@example.com"
    status.assert_awaited_once_with("bob@example.com", persist=False)
    assert adapter.send.call_args.kwargs["to"] == "bob@example.com"
    db.assert_not_called()


@pytest.mark.parametrize("kind", ["weekly", "reminder"])
def test_omitted_email_sends_to_all_owners_and_continues_after_failure(test_send, monkeypatch, kind):
    client, status, adapter, claim, db = test_send
    monkeypatch.setattr(notifications, "_test_owner_emails", lambda: ["alice@example.com", "bob@example.com"])
    adapter.send.side_effect = [smtplib.SMTPRecipientsRefused({}), None]
    for _ in range(2):
        adapter.send.side_effect = [smtplib.SMTPRecipientsRefused({}), None]
        response = client.post(URL, params={"kind": kind}, headers=AUTH)
        assert response.status_code == 200
        result = response.json()
        assert result["sent"] == 1 and result["failed"] == 1
        assert result["errors"][0]["email"] == "alice@example.com"
    assert status.await_count == 4
    assert {c.args[0] for c in status.await_args_list} == {"alice@example.com", "bob@example.com"}
    claim.assert_not_called()
    db.assert_not_called()


def test_bulk_missing_credentials_does_not_scan_or_send(test_send):
    client, status, adapter, _, db = test_send
    assert client.post(URL).status_code == 401
    db.assert_not_called()
    status.assert_not_called()
    adapter.send.assert_not_called()


def test_bulk_feedback_resends_to_all_owners_without_consuming_deliveries(test_send, monkeypatch):
    client, status, adapter, claim, db = test_send
    owners = MagicMock(return_value=["alice@example.com", "bob@example.com"])
    monkeypatch.setattr(notifications, "_test_owner_emails", owners)
    path = "/internal/profile-feedback/test"
    assert client.post(path).status_code == 401
    owners.assert_not_called()
    for _ in range(2):
        adapter.send.side_effect = [smtplib.SMTPRecipientsRefused({}), None]
        response = client.post(path, headers=AUTH)
        assert response.status_code == 200
        result = response.json()
        assert result["sent"] == 1 and result["failed"] == 1
        assert result["kind"] == "feedback" and result["test"] is True
        assert result["errors"][0]["email"] == "alice@example.com"
    assert status.await_count == 4
    assert [c.kwargs["to"] for c in adapter.send.call_args_list] == [
        "alice@example.com", "bob@example.com", "alice@example.com", "bob@example.com"]
    assert all(c.kwargs["subject"].startswith("[TEST] How’s your Zynd profile")
               for c in adapter.send.call_args_list)
    claim.assert_not_called()
    db.assert_not_called()


def test_bulk_owner_list_deduplicates_normalized_emails_and_pages(monkeypatch):
    sb = MagicMock()
    q = sb.table.return_value
    for method in ("select", "neq", "order", "range"):
        getattr(q, method).return_value = q
    q.not_.is_.return_value = q
    q.execute.side_effect = [
        SimpleNamespace(data=[{"owner_email": "Alice@Example.com"}] * 499 + [{"owner_email": "  alice@example.com  "}]),
        SimpleNamespace(data=[{"owner_email": "bob@example.com"}, {"owner_email": ""}, {"owner_email": None}]),
    ]
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    assert notifications._test_owner_emails() == ["alice@example.com", "bob@example.com"]
    assert [c.args for c in q.range.call_args_list] == [(0, 499), (500, 999)]
    q.neq.assert_called_with("status", "merged")
    q.select.assert_called_with("owner_email")
