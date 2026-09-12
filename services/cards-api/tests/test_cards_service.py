"""
Tests for services/cards.py ownership + claim logic — Supabase/embed mocked.

Run: cd backend && python -m pytest tests/test_cards_service.py -v
"""
from unittest.mock import MagicMock

import pytest

from models.card import AgentProfileCard
from services import cards as cards_service


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self.payload = None

    def select(self, *args):
        return self

    def eq(self, *args, **kwargs):
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def execute(self):
        return MagicMock(data=self._rows)


@pytest.fixture
def mock_sb(monkeypatch):
    query = _FakeQuery([{"owner_email": None}])
    sb = MagicMock()
    sb.table.return_value = query
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(cards_service.embed, "card_search_text", lambda card: "search text")
    monkeypatch.setattr(cards_service.embed, "embed_text", lambda text: [0.1, 0.2])
    return query


def _card() -> AgentProfileCard:
    return AgentProfileCard(
        id="testid",
        status="published",
        handle="alice",
        identity={"name": "Alice", "headline": "Engineer", "location": "", "avatar_url": "", "links": {}},
        summary="Engineer.",
    )


def test_update_card_claims_unowned_legacy_card(mock_sb):
    ok = cards_service.update_card("alice", _card(), "alice@example.com")

    assert ok is True
    assert mock_sb.payload["owner_email"] == "alice@example.com"


def test_update_card_allows_existing_owner(mock_sb):
    mock_sb._rows = [{"owner_email": "alice@example.com"}]

    ok = cards_service.update_card("alice", _card(), "alice@example.com")

    assert ok is True
    assert mock_sb.payload["owner_email"] == "alice@example.com"


def test_update_card_rejects_different_owner(mock_sb):
    mock_sb._rows = [{"owner_email": "someone-else@example.com"}]

    ok = cards_service.update_card("alice", _card(), "alice@example.com")

    assert ok is False
    assert mock_sb.payload is None


def test_update_card_returns_false_when_handle_missing(mock_sb):
    mock_sb._rows = []

    ok = cards_service.update_card("ghost", _card(), "alice@example.com")

    assert ok is False
    assert mock_sb.payload is None


def test_pick_avatar_priority_linkedin_x_github():
    assert cards_service.pick_avatar(
        "https://media.licdn.com/a.jpg",
        "https://pbs.twimg.com/b.jpg",
        "https://avatars.githubusercontent.com/c",
    ) == "https://media.licdn.com/a.jpg"


def test_pick_avatar_falls_back_when_linkedin_missing():
    assert cards_service.pick_avatar(
        None, "https://pbs.twimg.com/b.jpg", "https://avatars.githubusercontent.com/c"
    ) == "https://pbs.twimg.com/b.jpg"
    assert cards_service.pick_avatar(None, None, "https://avatars.githubusercontent.com/c") == (
        "https://avatars.githubusercontent.com/c"
    )


def test_pick_avatar_skips_invalid_and_returns_empty():
    assert cards_service.pick_avatar("not-a-url", "", "data:text/plain,hi") == ""
    assert cards_service.pick_avatar(None, None, None) == ""