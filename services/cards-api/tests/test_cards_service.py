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


def test_update_card_refuses_legacy_unowned_claim_by_default(mock_sb, monkeypatch):
    monkeypatch.setattr(cards_service.config, "LEGACY_UNOWNED_CLAIM", False)

    ok, h = cards_service.update_card("alice", _card(), "mallory@example.com")

    assert ok is False
    assert mock_sb.payload is None


def test_update_card_claims_legacy_unowned_card_when_enabled(mock_sb, monkeypatch):
    monkeypatch.setattr(cards_service.config, "LEGACY_UNOWNED_CLAIM", True)

    ok, h = cards_service.update_card("alice", _card(), "alice@example.com")

    assert ok is True
    assert h == "alice"
    assert mock_sb.payload["owner_email"] == "alice@example.com"


def test_update_card_claims_with_matching_claim_token(mock_sb):
    token, token_hash = cards_service.new_claim_token()
    mock_sb._rows = [{"owner_email": None, "claim_token_hash": token_hash}]

    ok, _ = cards_service.update_card("alice", _card(), "alice@example.com", claim_token=token)

    assert ok is True
    assert mock_sb.payload["owner_email"] == "alice@example.com"
    assert mock_sb.payload["claim_token_hash"] is None  # single use


def test_update_card_rejects_wrong_or_missing_claim_token(mock_sb):
    _, token_hash = cards_service.new_claim_token()
    mock_sb._rows = [{"owner_email": None, "claim_token_hash": token_hash}]

    assert cards_service.update_card("alice", _card(), "m@example.com", claim_token="guess")[0] is False
    assert cards_service.update_card("alice", _card(), "m@example.com")[0] is False
    assert mock_sb.payload is None


def test_owner_edits_do_not_need_a_claim_token(mock_sb):
    mock_sb._rows = [{"owner_email": "alice@example.com", "claim_token_hash": None}]

    ok, _ = cards_service.update_card("alice", _card(), "alice@example.com")

    assert ok is True
    assert "claim_token_hash" not in mock_sb.payload


def test_update_card_allows_existing_owner(mock_sb):
    mock_sb._rows = [{"owner_email": "alice@example.com"}]

    ok, h = cards_service.update_card("alice", _card(), "alice@example.com")

    assert ok is True
    assert h == "alice"
    assert mock_sb.payload["owner_email"] == "alice@example.com"


def test_update_card_rejects_different_owner(mock_sb):
    mock_sb._rows = [{"owner_email": "someone-else@example.com"}]

    ok, h = cards_service.update_card("alice", _card(), "alice@example.com")

    assert ok is False
    assert mock_sb.payload is None


def test_update_card_returns_false_when_handle_missing(mock_sb):
    mock_sb._rows = []

    ok, h = cards_service.update_card("ghost", _card(), "alice@example.com")

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


def test_refresh_avatar_updates_identity_avatar_url():
    card = {"identity": {"name": "Alice", "avatar_url": "https://old.example/a.jpg", "links": {}}}

    assert cards_service.refresh_avatar(card, "https://media.licdn.com/new.jpg", None) is True
    assert card["identity"]["avatar_url"] == "https://media.licdn.com/new.jpg"


def test_refresh_avatar_keeps_existing_when_nothing_new():
    card = {"identity": {"name": "Alice", "avatar_url": "https://avatars.githubusercontent.com/c", "links": {}}}

    assert cards_service.refresh_avatar(card, None, None) is False
    assert card["identity"]["avatar_url"] == "https://avatars.githubusercontent.com/c"


def test_refresh_avatar_unchanged_is_noop():
    card = {"identity": {"name": "Alice", "avatar_url": "https://media.licdn.com/a.jpg", "links": {}}}

    assert cards_service.refresh_avatar(card, "https://media.licdn.com/a.jpg", None) is False


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
    x_posts = [{"platform": "x", "excerpt": f"Shipped tweet number {i} today.", "url": f"https://x.com/a/status/{i}", "posted_at": ""} for i in range(8)]
    li_posts = [{"platform": "linkedin", "excerpt": f"LinkedIn post number {i} about the launch.", "url": f"https://ln/p/{i}", "posted_at": ""} for i in range(8)]

    merged = cards_service.merge_scraped_posts(llm, x_posts, li_posts, cap=10)

    assert len(merged) == 10
    platforms = [w.platform for w in merged]
    # Interleave favours a mix: 5 x + 5 linkedin fills the cap before LLM picks
    assert platforms.count("x") == 5
    assert platforms.count("linkedin") == 5


def test_clean_excerpt_unescapes_and_strips_tags():
    assert cards_service.clean_excerpt("agent &amp; LLM friendly.<br>Next") == "agent & LLM friendly. Next"
    assert cards_service.clean_excerpt("  hello   \n\n\n  world  ") == "hello \n\n world"


def test_is_thin_excerpt_drops_url_only_posts():
    assert cards_service.is_thin_excerpt("full post here: https://t.co/fNxJMRhPUe") is True
    assert cards_service.is_thin_excerpt("Manifesting: I can just travel the world") is False


def test_merge_scraped_posts_skips_thin_and_html():
    from models.card import WritingSample

    llm: list[WritingSample] = []
    x_posts = [
        {"excerpt": "full post here: https://t.co/fNxJMRhPUe", "url": "https://x.com/a/status/1"},
        {"excerpt": "Cookie got a facelift. Its agent &amp; LLM friendly.", "url": "https://x.com/a/status/2"},
    ]
    merged = cards_service.merge_scraped_posts(llm, x_posts, None)
    assert len(merged) == 1
    assert merged[0].excerpt == "Cookie got a facelift. Its agent & LLM friendly."

# ── owner_user_id only where the column exists (aafo's cards schema) ─────────

@pytest.mark.parametrize("writes, expected", [(False, None), (True, "sub-aafo")])
def test_insert_card_sends_owner_user_id_only_on_cards_schema(monkeypatch, writes, expected):
    """xmfj's agent_profile_cards has no owner_user_id column; sending it there
    makes PostgREST reject the whole publish."""
    sb = MagicMock()
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(cards_service.config, "WRITES_OWNER_USER_ID", writes)
    monkeypatch.setattr(cards_service, "_assign_handle", lambda *a: "alice")
    monkeypatch.setattr(cards_service.embed, "card_search_text", lambda card: "t")
    monkeypatch.setattr(cards_service.embed, "embed_text", lambda text: [0.1])

    cards_service.insert_card(_card(), None, None, owner_email="a@x.io", owner_user_id="sub-aafo")

    row = sb.table.return_value.upsert.call_args.args[0]
    assert row.get("owner_user_id") == expected
    assert ("owner_user_id" in row) is writes


@pytest.mark.parametrize("writes", [False, True])
def test_update_card_sends_owner_user_id_only_on_cards_schema(mock_sb, monkeypatch, writes):
    mock_sb._rows = [{"owner_email": "alice@example.com"}]
    monkeypatch.setattr(cards_service.config, "WRITES_OWNER_USER_ID", writes)

    ok, _ = cards_service.update_card("alice", _card(), "Alice@Example.com", owner_user_id="sub-aafo")

    assert ok  # owner match is case-insensitive
    assert ("owner_user_id" in mock_sb.payload) is writes


def test_like_literal_and_postgrest_quote_escape_special_characters():
    assert cards_service._like_literal("a_b%c@x.io") == "a\\_b\\%c@x.io"
    assert cards_service._postgrest_quote('evil,handle.eq.x"') == '"evil,handle.eq.x\\""'


# ── rename keeps old handles resolving (stale-link prevention) ────────────────

class _RenameQuery:
    """Owner checks succeed, handle-conflict checks come back empty."""

    def __init__(self):
        self.payload = None
        self._conflict = False

    def select(self, *_a):
        return self

    def eq(self, col, val):
        if col == "handle" and val == "alice-new":
            self._conflict = True
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def execute(self):
        if self._conflict:
            return MagicMock(data=[])
        return MagicMock(data=[{"owner_email": "alice@example.com", "claim_token_hash": None}])


def test_update_card_rename_records_previous_handle(monkeypatch):
    q = _RenameQuery()
    sb = MagicMock()
    sb.table.return_value = q
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(cards_service.embed, "card_search_text", lambda card: "t")
    monkeypatch.setattr(cards_service.embed, "embed_text", lambda text: [0.1])

    card = _card()
    ok, h = cards_service.update_card("alice", card, "alice@example.com", new_handle="alice-new")

    assert ok is True
    assert h == "alice-new"
    assert card.previous_handles == ["alice"]
    assert q.payload["handle"] == "alice-new"


def test_update_card_rename_appends_to_existing_history(monkeypatch):
    q = _RenameQuery()
    sb = MagicMock()
    sb.table.return_value = q
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(cards_service.embed, "card_search_text", lambda card: "t")
    monkeypatch.setattr(cards_service.embed, "embed_text", lambda text: [0.1])

    card = _card()
    card.previous_handles = ["first-slug"]
    ok, h = cards_service.update_card("alice", card, "alice@example.com", new_handle="alice-new")

    assert ok is True
    assert card.previous_handles == ["alice", "first-slug"]


def test_update_card_rename_does_not_duplicate_history(monkeypatch):
    q = _RenameQuery()
    sb = MagicMock()
    sb.table.return_value = q
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(cards_service.embed, "card_search_text", lambda card: "t")
    monkeypatch.setattr(cards_service.embed, "embed_text", lambda text: [0.1])

    card = _card()
    card.previous_handles = ["alice"]
    ok, _ = cards_service.update_card("alice", card, "alice@example.com", new_handle="alice-new")

    assert ok is True
    assert card.previous_handles == ["alice"]


class _HandleLookupQuery:
    """by-handle miss on the first pass, hit on the previous-handles fallback."""

    def __init__(self, fallback_rows=None):
        self.contains_call = None
        self.fallback_rows = fallback_rows

    def select(self, *_a):
        return self

    def eq(self, *_a, **_k):
        return self

    def contains(self, col, val):
        self.contains_call = (col, val)
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        if self.contains_call:
            return MagicMock(data=self.fallback_rows or [])
        return MagicMock(data=[])


def test_get_card_by_handle_falls_back_to_previous_handles(monkeypatch):
    q = _HandleLookupQuery(
        fallback_rows=[{"card": _card().model_dump(mode="json"), "handle": "alice-new"}]
    )
    sb = MagicMock()
    sb.table.return_value = q
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)

    card = cards_service.get_card_by_handle("alice")

    assert card is not None
    assert card.handle == "alice-new"
    assert q.contains_call == ("card", {"previous_handles": ["alice"]})


def test_get_card_by_handle_returns_none_when_neither_matches(monkeypatch):
    q = _HandleLookupQuery(fallback_rows=[])
    sb = MagicMock()
    sb.table.return_value = q
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)

    assert cards_service.get_card_by_handle("ghost") is None


# ── owners never look card-less ───────────────────────────────────────────────

class _OwnerLookupQuery:
    """First (published-filtered) pass misses; second (any-status) pass hits."""

    def __init__(self, fallback_rows):
        self.fallback_rows = fallback_rows
        self.status_filters = []
        self.executes = 0

    def select(self, *_a):
        return self

    def ilike(self, *_a, **_k):
        return self

    def eq(self, col, val):
        if col == "status":
            self.status_filters.append(val)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        self.executes += 1
        if self.executes == 1:
            return MagicMock(data=[])
        return MagicMock(data=self.fallback_rows)


def test_get_card_by_owner_falls_back_to_unpublished_owned_card(monkeypatch):
    pending = _card()
    pending.status = "pending_review"
    q = _OwnerLookupQuery([{"card": pending.model_dump(mode="json"), "handle": "chandan-kumar-c5r4"}])
    sb = MagicMock()
    sb.table.return_value = q
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)

    card, handle = cards_service.get_card_by_owner("vivekans2016@gmail.com")

    assert handle == "chandan-kumar-c5r4"
    assert card.status == "pending_review"
    assert q.status_filters == ["published"]  # published pass ran first
