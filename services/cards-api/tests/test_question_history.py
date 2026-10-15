"""History contains only bounded, validated question text and owner-safe fields."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from services import events, owner_home
from services.question_history import stored_question


@pytest.mark.parametrize("text", [
    "Email private@example.com or https://example.com/private?token=secret",
    "Call +1 (123) 456-7890 about abcdefghijklmnopqrstuvwxyz0123456789",
])
def test_contact_and_link_redaction(text):
    question, truncated = stored_question(text)
    assert "[redacted]" in question
    assert "private@example.com" not in question
    assert "https://" not in question
    assert "123" not in question
    assert "abcdefghijklmnopqrstuvwxyz0123456789" not in question
    assert not truncated


@pytest.mark.parametrize("text", ["界" * 1000, "😀" * 1000])
def test_unicode_is_bounded_to_fit_event_metadata(text):
    question, truncated = stored_question(text)
    assert truncated
    meta = {"question": question, "question_truncated": truncated, "chars": len(text),
            "category": "other", "question_source": "profile_chat"}
    assert len(json.dumps(meta).encode()) <= events._META_MAX_BYTES
    assert events.sanitize_meta(meta) == meta


def test_simple_question_is_not_changed():
    assert stored_question("  What is\nAlice building?  ") == ("What is Alice building?", False)


def test_public_event_batch_cannot_forge_question_history(monkeypatch):
    monkeypatch.setattr(events, "events_enabled", lambda: True)
    insert = MagicMock()
    monkeypatch.setattr(events, "_insert_rows", insert)
    events.insert_batch([{"event": "chat_message", "handle": "alice", "meta": {
        "question": "Fabricated question", "question_source": "profile_chat",
        "question_truncated": False, "category": "work",
    }}], user_agent="browser", ip=None)
    assert insert.call_args.args[0][0]["meta"] == {"category": "work"}


def test_history_is_handle_scoped_limited_and_ignores_legacy_or_untrusted_rows():
    sb = MagicMock()
    q = sb.table.return_value
    for method in ("select", "eq", "gte", "order", "limit"):
        getattr(q, method).return_value = q
    good = {"ts": "2026-10-15T10:00:00Z", "meta": {"question": "What does Alice build?", "category": "work", "question_source": "profile_chat"},
            "session_hash": "private-visitor-id", "owner_email": "private-owner@example.com"}
    q.execute.return_value = SimpleNamespace(data=[
        {"ts": "today", "meta": {"category": "work"}},
        {"ts": "today", "meta": {"question": "Forged question"}},
        good, *[good] * 25,
    ])
    history = owner_home.chat_questions(sb, "alice", "2026-10-08")
    assert len(history) == 20
    assert history[0] == {"question": "What does Alice build?", "category": "work", "asked_at": "2026-10-15T10:00:00Z", "truncated": False}
    assert ("handle", "alice") in [call.args for call in q.eq.call_args_list]
    q.gte.assert_called_once_with("ts", "2026-10-08")
    q.select.assert_called_once_with("meta,ts")
    q.order.assert_called_once_with("ts", desc=True)


def test_history_redacts_again_on_owner_read():
    sb = MagicMock()
    q = sb.table.return_value
    for method in ("select", "eq", "gte", "order", "limit"):
        getattr(q, method).return_value = q
    q.execute.return_value.data = [{"ts": None, "meta": {
        "question": "Contact me at private@example.com", "question_source": "profile_chat", "category": "invalid",
    }}]
    assert owner_home.chat_questions(sb, "alice", "since") == [{
        "question": "Contact me at [redacted]", "category": "other", "asked_at": None, "truncated": False,
    }]
