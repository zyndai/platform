"""Card search matches whole words and ignores stopwords (Part B, F2)."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from models.card import AgentProfileCard
from services import search as search_service
from services.search_text import contains_all, query_terms, token_set


def _card(handle, *, headline="", location="", skills=(), industries=(), summary="", memory=()):
    return {
        "card": AgentProfileCard(
            id=f"id-{handle}", status="published", handle=handle,
            identity={"name": handle.title(), "headline": headline, "location": location,
                      "avatar_url": "", "links": {}},
            summary=summary, skills=[{"name": s} for s in skills], industries=list(industries),
            zynd_memory=[{"predicate": "is_building", "object": o, "source": "declared",
                          "approved_at": datetime.now(timezone.utc).isoformat(), "confidence": 0.9}
                         for o in memory],
        ).model_dump(mode="json"),
        "handle": handle,
        "owner_email": "owner@example.com",
    }


@pytest.fixture
def cards(monkeypatch):
    rows: list[dict] = []
    sb = MagicMock()
    sb.rpc.side_effect = RuntimeError("no rpc")
    monkeypatch.setattr(search_service.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(search_service, "embed_text", lambda q: [])
    monkeypatch.setattr(search_service.cards_service, "list_published_rows", lambda **kw: rows)
    return rows


def handles(**kw):
    return [r["handle"] for r in search_service.search_agents(include_unclaimed=True, **kw)]


# ── helpers ────────────────────────────────────────────────────────────────────

def test_query_terms_drop_stopwords_but_keep_ai():
    assert query_terms("seed-stage investor who backs AI dev tools in India") == [
        "seed", "stage", "investor", "back", "ai", "dev", "tool", "india"]
    assert query_terms("who in the") == []


def test_plurals_and_punctuation_fold_together():
    assert contains_all(token_set("Angel Investors"), "investor")
    assert contains_all(token_set("builds Next.js apps"), "nextjs")
    assert contains_all(token_set("builds nextjs apps"), "Next.js")
    assert not contains_all(token_set("I maintain systems"), "ai")


# ── search ────────────────────────────────────────────────────────────────────

def test_ai_does_not_match_inside_other_words(cards):
    cards += [
        _card("plumber", headline="I maintain the plumbing", summary="Certain repairs, again and again"),
        _card("aidev", headline="AI engineer"),
    ]
    assert handles(q="ai") == ["aidev"]


def test_stopwords_alone_match_nothing(cards):
    cards += [_card("a", headline="Someone who works in a field"), _card("b", headline="Founder")]
    assert handles(q="who in the") == []


def test_stopwords_no_longer_inflate_a_match(cards):
    cards += [
        _card("noise", headline="People who live in the city"),       # only stopword overlap
        _card("real", headline="Investor", location="India", summary="Backs AI developer tools in India"),
    ]
    assert handles(q="investor who backs AI tools in India") == ["real"]


def test_nextjs_and_next_js_are_the_same_word(cards):
    cards += [_card("web", headline="Frontend", summary="I ship Next.js apps")]
    assert handles(q="nextjs") == ["web"]


def test_memory_fact_bonus_uses_whole_words(cards):
    cards += [
        _card("maintainer", headline="Engineer", memory=["Maintaining a legacy billing system"]),
        _card("ai", headline="Engineer", memory=["AI evaluation harness"]),
    ]
    result = search_service.search_agents(q="ai", include_unclaimed=True)
    assert [r["handle"] for r in result] == ["ai"]
    assert any(isinstance(r, dict) or r == "Approved fact" for r in result[0]["match_reasons"])


def test_skill_filter_is_whole_word_go_is_not_django(cards):
    cards += [_card("py", headline="Backend", skills=["Django"]), _card("gopher", headline="Backend", skills=["Go"])]
    ranked = search_service.search_agents(q="backend", skills="go", include_unclaimed=True)
    scores = {r["handle"]: r["match_score"] for r in ranked}
    assert "gopher" in scores and "py" not in scores


def test_role_filter_matches_plural_headlines(cards):
    cards += [_card("vc", headline="Angel investors collective"), _card("eng", headline="Engineer")]
    ranked = search_service.search_agents(q="seed", role="investor", include_unclaimed=True)
    assert ranked[0]["handle"] == "vc"


def test_location_filter_knows_bengaluru_is_bangalore(cards):
    cards += [_card("blr", headline="Founder", location="Bengaluru, India"),
              _card("nyc", headline="Founder", location="New York")]
    ranked = {r["handle"]: r["match_score"] for r in
              search_service.search_agents(q="founder", location="Bangalore", include_unclaimed=True)}
    assert "blr" in ranked and "nyc" not in ranked


def test_location_filter_does_not_match_substrings(cards):
    cards += [_card("a", headline="Founder", location="Indiana, USA"),
              _card("b", headline="Founder", location="Pune, India")]
    ranked = {r["handle"]: r["match_score"] for r in
              search_service.search_agents(q="founder", location="India", include_unclaimed=True)}
    assert "b" in ranked and "a" not in ranked


def test_developer_tools_is_not_a_developer():
    """People search Phase 2: "Seed investor backing AI developer tools" is no engineer, in search
    or in two-way matching; "Developer tooling engineer" still is."""
    from models.card import AgentProfileCard
    from services.search_text import role_matches, role_tokens
    from services.two_way import kinds_of

    assert not role_matches(role_tokens("Seed investor backing AI developer tools"), "engineer")
    assert not role_matches(role_tokens("Founder of a dev-tools company"), "developer")
    assert role_matches(role_tokens("Developer tooling engineer"), "engineer")
    assert role_matches(role_tokens("Backend developer"), "engineer")
    investor = AgentProfileCard(id="x", identity={"name": "X", "headline": "Seed investor backing AI developer tools"})
    assert kinds_of(investor) == {"Investors"}
