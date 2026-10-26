"""The score is relevance x fit x quality (services/search.py): each part is 0..1 and meeting a
requested constraint can only raise it (people search plan, Phase 1)."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from models.card import AgentProfileCard
from services import search as S


def _row(handle, *, headline="", location="", skills=(), summary="", claimed=True, similarity=None):
    card = AgentProfileCard(
        id=f"id-{handle}", status="published", handle=handle,
        identity={"name": handle.title(), "headline": headline, "location": location, "avatar_url": "", "links": {}},
        summary=summary, skills=[{"name": s} for s in skills],
    )
    row = {"card": card.model_dump(mode="json"), "handle": handle,
           "owner_email": "o@example.com" if claimed else ""}
    if similarity is not None:
        row["similarity"] = similarity
    return row


@pytest.fixture
def corpus(monkeypatch):
    rows: list[dict] = []
    sb = MagicMock()
    sb.rpc.side_effect = RuntimeError("no rpc")
    monkeypatch.setattr(S.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(S, "embed_text", lambda q: [1.0, 0.0])
    monkeypatch.setattr(S.cards_service, "list_published_rows", lambda **kw: rows)
    return rows


def scores(**kw):
    return {r["handle"]: r["match_score"] for r in S.search_agents(include_unclaimed=True, **kw)}


def test_every_part_of_the_score_is_between_zero_and_one():
    assert S.semantic_score(None) == S.semantic_score(0.0) == 0.0
    assert S.semantic_score(S.SEM_FLOOR + S.SEM_SPAN) == S.semantic_score(1.0) == 1.0
    assert 0 < S.semantic_score(0.4) < 1
    assert S.relevance_score(1, 1, 1, True, True) == 1.0
    assert S.relevance_score(0, 0, 0, False, False) == 1.0, "no query words: every card that passes the filters is equally relevant"
    assert 0.85 <= S.quality_score(False, 0) < S.quality_score(True, 1) <= 1.0


def test_meaning_alone_cannot_rescue_a_card_that_is_not_the_role(corpus):
    corpus += [_row("vc", headline="Seed investor", similarity=0.45),
               _row("pm", headline="Product manager", similarity=0.6)]
    got = scores(q="investor for my startup", role="investor", relax=True)
    assert got["vc"] > got.get("pm", 0)


def test_meeting_a_constraint_never_lowers_the_score(corpus):
    """The same card, one step closer to the request each time: role elsewhere -> in the headline,
    place absent -> same country -> the city; the score never drops."""
    steps = [
        ("Engineer who invests", "Paris"),
        ("Angel investor", "Paris"),
        ("Angel investor", "Gurgaon"),
        ("Angel investor", "Pune"),
    ]
    seen = []
    for headline, location in steps:
        corpus.clear()
        corpus.append(_row("c", headline=headline, location=location, summary="Angel investor backing AI", similarity=0.5))
        got = S.search_agents(q="angel investor in Pune", role="investor", location="Pune", relax=True, include_unclaimed=True)
        seen.append(got[0]["match_score"] if got else 0.0)
    assert seen == sorted(seen), seen


def test_a_stricter_pass_always_ranks_above_a_looser_one(corpus):
    corpus += [_row("near", headline="Angel investor", location="Paris", similarity=0.7),
               _row("exact", headline="Angel investor", location="Pune", similarity=0.5)]
    found = S.search_agents(q="angel investor", role="investor", location="Pune", relax=True, include_unclaimed=True, limit=5)
    assert [r["handle"] for r in found] == ["exact", "near"]
    assert "relaxed" not in found[0] and found[1]["relaxed"] == ["location"]


def test_a_missed_constraint_costs_a_fixed_share(corpus):
    corpus += [_row("here", headline="Investor", location="Pune", similarity=0.6),
               _row("there", headline="Investor", location="Paris", similarity=0.6)]
    got = scores(q="investor", role="investor", location="Pune", relax=True, limit=5)
    assert got["there"] == pytest.approx(got["here"] * S.FIT_LOCATION_MISSING, abs=0.01)


def test_a_claimed_owner_and_a_current_fact_raise_quality_a_little(corpus):
    corpus += [_row("claimed", headline="Investor", similarity=0.6), _row("scraped", headline="Investor", claimed=False, similarity=0.6)]
    got = scores(q="investor", role="investor")
    assert got["claimed"] > got["scraped"]
    assert got["scraped"] > 0.9 * got["claimed"]


def test_words_a_met_constraint_answers_count_as_found(corpus):
    """"investors in India" is answered by an investor in Gurgaon whose card never says India."""
    corpus.append(_row("gurgaon", headline="Seed investor", location="Gurgaon", similarity=0.5))
    assert scores(q="investors in India", role="investor", location="India")["gurgaon"] >= S.MIN_SCORE


def test_noise_below_the_floor_is_dropped_for_a_text_query(corpus):
    corpus.append(_row("noise", headline="Accountant", similarity=0.15))
    assert scores(q="rust compiler contributor") == {}
