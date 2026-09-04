"""
Tests for the X bot — all X API calls are mocked.
Run: cd backend && python -m pytest tests/test_x_bot.py -v
"""
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ── Patch config before any module import ────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_config(monkeypatch):
    monkeypatch.setattr("config.X_BEARER_TOKEN", "fake-bearer")
    monkeypatch.setattr("config.X_USER_ACCESS_TOKEN", "fake-token")
    monkeypatch.setattr("config.X_USER_REFRESH_TOKEN", "")
    monkeypatch.setattr("config.X_CLIENT_ID", "fake-client-id")
    monkeypatch.setattr("config.X_CLIENT_SECRET", "")
    monkeypatch.setattr("config.APIFY_API_KEY", "fake-apify-key")
    monkeypatch.setattr("config.SITE_BASE_URL", "https://zynd.ai")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Command parsing
# ═══════════════════════════════════════════════════════════════════════════════

from x.commands import Command, parse_command, strip_mention


@pytest.mark.parametrize("text,expected", [
    ("@ZyndAI create my profile",    Command.CREATE_PROFILE),
    ("@ZyndAI make my profile",      Command.CREATE_PROFILE),
    ("@ZyndAI build my profile",     Command.CREATE_PROFILE),
    ("@ZyndAI generate my profile",  Command.CREATE_PROFILE),
    ("@ZyndAI update my profile",    Command.UPDATE_PROFILE),
    ("@ZyndAI edit my profile",      Command.UPDATE_PROFILE),
    ("@ZyndAI",                      Command.HELP),
    ("@ZyndAI hello",                Command.HELP),
    ("@ZyndAI who should I meet?",   Command.FIND_CONNECTIONS),
])
def test_parse_command(text, expected):
    assert parse_command(text) == expected


def test_parse_command_onboarding_answer():
    # A reply to a bot tweet should always be treated as an answer
    assert parse_command("@ZyndAI building AI infra in Rust", is_reply_to_bot=True) == Command.ONBOARDING_ANSWER


def test_strip_mention():
    assert strip_mention("@ZyndAI create my profile") == "create my profile"
    assert strip_mention("@ZyndAI") == ""
    assert strip_mention("@zyndai hello world", bot_handle="zyndai") == "hello world"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Idempotency — mention_seen
# ═══════════════════════════════════════════════════════════════════════════════

def test_mention_seen_returns_false_for_unknown(monkeypatch):
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    monkeypatch.setattr("x.conversation.config.get_supabase", lambda: mock_sb)

    from x.conversation import mention_seen
    assert mention_seen("tweet-999") is False


def test_mention_seen_returns_true_for_known(monkeypatch):
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{"id": 1}]
    monkeypatch.setattr("x.conversation.config.get_supabase", lambda: mock_sb)

    from x import conversation
    # Reload to pick up monkeypatched config
    import importlib; importlib.reload(conversation)
    assert conversation.mention_seen("tweet-123") is True


# ═══════════════════════════════════════════════════════════════════════════════
# 3. next_question skips already-answered fields
# ═══════════════════════════════════════════════════════════════════════════════

from x.conversation import next_question, ONBOARDING_QUESTIONS


def test_next_question_all_unanswered():
    field, _ = next_question({})
    assert field == ONBOARDING_QUESTIONS[0][0]


def test_next_question_skips_answered():
    answered = {ONBOARDING_QUESTIONS[0][0]: "something"}
    field, _ = next_question(answered)
    assert field == ONBOARDING_QUESTIONS[1][0]


def test_next_question_all_answered():
    answered = {f: "v" for f, _ in ONBOARDING_QUESTIONS}
    assert next_question(answered) is None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. _missing_fields respects already-scraped card data
# ═══════════════════════════════════════════════════════════════════════════════

from x.mentions import _missing_fields


def _make_card(**kwargs):
    from models.card import AgentProfileCard, Identity
    return AgentProfileCard(
        id="test-id",
        identity=Identity(location=kwargs.get("location", "")),
        working_on=kwargs.get("working_on", []),
        can_help_with=kwargs.get("can_help_with", []),
        love_talking_about=kwargs.get("love_talking_about", []),
        connect_with=kwargs.get("connect_with", []),
    )


def test_missing_fields_skips_populated():
    card = _make_card(location="SF", working_on=["AI infra"])
    missing_fields = [f for f, _ in _missing_fields(card, {})]
    assert "location" not in missing_fields
    assert "working_on" not in missing_fields


def test_missing_fields_skips_answered():
    card = _make_card()
    missing_fields = [f for f, _ in _missing_fields(card, {"location": "NYC"})]
    assert "location" not in missing_fields


def test_missing_fields_all_present():
    card = _make_card(
        location="SF",
        working_on=["x"],
        can_help_with=["y"],
        love_talking_about=["z"],
        connect_with=["w"],
    )
    assert _missing_fields(card, {}) == []


# ═══════════════════════════════════════════════════════════════════════════════
# 5. reply helpers compose correct text
# ═══════════════════════════════════════════════════════════════════════════════

def test_reply_help_contains_username(monkeypatch):
    posted: list[str] = []
    monkeypatch.setattr("x.replies.get_write_client", lambda: MagicMock(
        create_tweet=lambda text, reply: posted.append(text) or MagicMock(data={"id": "1"})
    ))
    from x import replies
    replies.reply_help("alice", "tweet-1")
    assert "@alice" in posted[0]
    assert "ZyndAI" in posted[0] or "zynd" in posted[0].lower()


def test_reply_profile_ready_includes_url(monkeypatch):
    posted: list[str] = []
    monkeypatch.setattr("x.replies.get_write_client", lambda: MagicMock(
        create_tweet=lambda text, reply: posted.append(text) or MagicMock(data={"id": "1"})
    ))
    from x import replies
    replies.reply_profile_ready("bob", "tweet-2", "bob-handle", None)
    assert "zynd.ai/p/bob-handle" in posted[0]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. apply_answers_to_card merges without destroying existing data
# ═══════════════════════════════════════════════════════════════════════════════

from x.mentions import _apply_answers_to_card


def test_apply_answers_does_not_overwrite_location():
    card = _make_card(location="Berlin")
    _apply_answers_to_card(card, {"location": "NYC"})
    # Existing location should be preserved (not overwritten)
    assert card.identity.location == "Berlin"


def test_apply_answers_sets_missing_location():
    card = _make_card(location="")
    _apply_answers_to_card(card, {"location": "NYC"})
    assert card.identity.location == "NYC"


def test_apply_answers_sets_working_on():
    card = _make_card()
    _apply_answers_to_card(card, {"working_on": "AI infra, Rust"})
    assert "AI infra" in card.working_on
    assert "Rust" in card.working_on
