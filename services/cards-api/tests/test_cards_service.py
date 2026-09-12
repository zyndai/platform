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


def test_merge_scraped_posts_injects_both_platforms():
    from models.card import WritingSample

    llm = [WritingSample(platform="x", excerpt="LLM-picked tweet.", url="https://x.com/a/status/9", posted_at="2026-01-01")]

    x_posts = [{"platform": "x", "excerpt": "Real tweet one.", "url": "https://x.com/a/status/1", "posted_at": "2026-01-02"},
               {"platform": "x", "excerpt": "Real tweet two.", "url": "https://x.com/a/status/2", "posted_at": "2026-01-03"}]
    li_posts = [{"platform": "linkedin", "excerpt": "Real LI post one.", "url": "https://ln/p/1", "posted_at": "2026-01-04"}]

    merged = cards_service.merge_scraped_posts(llm, x_posts, li_posts)

    platforms = [w.platform for w in merged]
    assert platforms == ["x", "linkedin", "x", "x"]  # interleaved scraped, then LLM fill
    # Scraped posts come before the LLM fill
    assert merged[0].url == "https://x.com/a/status/1"
    assert merged[-1].excerpt == "LLM-picked tweet."


def test_merge_scraped_posts_dedupes_by_url():
    from models.card import WritingSample

    llm = [WritingSample(platform="x", excerpt="Same tweet via LLM.", url="https://x.com/a/status/1", posted_at="")]
    x_posts = [{"platform": "x", "excerpt": "Same tweet via LLM.", "url": "https://x.com/a/status/1", "posted_at": ""}]

    merged = cards_service.merge_scraped_posts(llm, x_posts, None)

    assert len(merged) == 1


def test_merge_scraped_posts_respects_cap():
    from models.card import WritingSample

    llm = [WritingSample(platform="x", excerpt=f"LLM {i}.", url=f"https://x.com/a/status/l{i}", posted_at="") for i in range(8)]
    x_posts = [{"platform": "x", "excerpt": f"Tweet {i}.", "url": f"https://x.com/a/status/{i}", "posted_at": ""} for i in range(8)]
    li_posts = [{"platform": "linkedin", "excerpt": f"LI {i}.", "url": f"https://ln/p/{i}", "posted_at": ""} for i in range(8)]

    merged = cards_service.merge_scraped_posts(llm, x_posts, li_posts, cap=10)

    assert len(merged) == 10
    platforms = [w.platform for w in merged]
    # Interleave favours a mix: 5 x + 5 linkedin fills the cap before LLM picks
    assert platforms.count("x") == 5
    assert platforms.count("linkedin") == 5