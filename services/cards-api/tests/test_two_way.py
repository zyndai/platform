"""A1 — two-way match: rank higher when the person found also wants to meet someone like the searcher."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from models.card import AgentProfileCard
from services import search as search_service
from services import two_way


def card(handle, headline="", **fields):
    seeking = fields.pop("seeking", [])
    return AgentProfileCard(
        id=handle, status="published", handle=handle,
        identity={"name": handle.title(), "headline": headline, "avatar_url": "", "links": {}},
        zynd_memory=[{"predicate": "is_seeking", "object": s, "source": "declared", "confidence": 0.9,
                      "approved_at": datetime.now(timezone.utc).isoformat()} for s in seeking],
        **fields,
    )


# ── what kind of person is this? ──────────────────────────────────────────────────

@pytest.mark.parametrize("headline,working_on,expected", [
    ("Founder building AI agents", [], {"Founders", "Potential co-founders"}),
    ("Seed investor in fintech", [], {"Investors"}),
    ("Product Manager at Acme", [], {"Product Managers", "Potential co-founders"}),
    ("Backend developer", [], {"Engineers", "Potential co-founders"}),
    ("Quietly doing things", ["Building a startup"], {"Founders", "Potential co-founders"}),
    ("Angel who mentors founders", [], {"Investors", "Mentors", "Founders", "Potential co-founders"}),
    ("", [], set()),
])
def test_kinds_come_from_the_headline_and_what_they_work_on(headline, working_on, expected):
    assert two_way.kinds_of(card("x", headline, working_on=working_on)) == expected


def test_a_substring_is_not_a_kind():
    assert two_way.kinds_of(card("x", "Vice president of venturesome plans")) == set()


# ── what do they want to meet? ────────────────────────────────────────────────────

def test_wanted_kinds_combine_connect_with_and_approved_seeking_facts():
    c = card("inv", "Investor", connect_with=["founders", "Engineers"], seeking=["mentoring", "co_founder"])
    assert two_way.wanted_kinds(c) >= {"Founders", "Engineers", "Mentors", "Potential co-founders"}
    assert two_way.wanted_kinds(card("quiet")) == set()
    assert two_way.wanted_kinds(card("x", connect_with=["unknown thing"])) == set()


def test_seeking_investment_means_wanting_investors():
    founder = card("f", "Founder", seeking=["investment"])
    assert two_way.two_way_match({"Investors"}, founder) == ["Investors"]
    assert two_way.two_way_match({"Designers"}, founder) == []
    assert two_way.two_way_match(set(), founder) == []


# ── in the ranking ────────────────────────────────────────────────────────────────

@pytest.fixture
def corpus(monkeypatch):
    rows = []
    sb = MagicMock()
    sb.rpc.side_effect = RuntimeError("no rpc")
    monkeypatch.setattr(search_service.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(search_service, "embed_text", lambda q: [])
    monkeypatch.setattr(search_service.cards_service, "list_published_rows", lambda **kw: rows)
    return rows


def put(rows, c):
    rows.append({"card": c.model_dump(mode="json"), "handle": c.handle, "owner_email": "o@example.com"})


def order(**kw):
    return [r["handle"] for r in search_service.search_agents(q="AI investor", role="investor", include_unclaimed=True, **kw)]


def test_the_investor_who_wants_founders_ranks_first_for_a_founder(corpus):
    put(corpus, card("wants-founders", "AI investor", connect_with=["Founders"]))
    put(corpus, card("wants-engineers", "AI investor", connect_with=["Engineers"]))
    put(corpus, card("silent", "AI investor"))
    founder = card("me", "Founder building AI agents")
    assert order(searcher=founder)[0] == "wants-founders"
    assert order(searcher=card("eng", "ML engineer"))[0] == "wants-engineers"


def test_the_boost_is_explained_and_only_applies_with_a_searcher(corpus):
    put(corpus, card("a", "AI investor", connect_with=["Founders"]))
    put(corpus, card("b", "AI investor"))
    plain = {r["handle"]: r for r in search_service.search_agents(q="AI investor", include_unclaimed=True)}
    assert plain["a"]["match_score"] == plain["b"]["match_score"]
    boosted = {r["handle"]: r for r in search_service.search_agents(
        q="AI investor", include_unclaimed=True, searcher=card("me", "Founder"))}
    assert boosted["a"]["match_score"] == pytest.approx(plain["a"]["match_score"] + two_way.TWO_WAY_BOOST, abs=0.001)
    assert any("Wants to meet people like you: Founders" in r for r in boosted["a"]["match_reasons"])
    assert boosted["b"]["match_score"] == plain["b"]["match_score"]


def test_you_never_get_a_boost_for_yourself(corpus):
    me = card("me", "Founder", connect_with=["Founders"])
    put(corpus, me)
    (result,) = search_service.search_agents(q="Founder", include_unclaimed=True, searcher=me)
    assert not any("Wants to meet" in str(r) for r in result["match_reasons"])


def test_the_search_endpoint_resolves_as_handle_to_a_card(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import agents as agents_api

    seen = {}
    me = card("me", "Founder")
    monkeypatch.setattr(agents_api.cards_service, "get_card_by_handle", lambda h: seen.setdefault("h", h) and me)
    monkeypatch.setattr(agents_api.search_service, "search_agents", lambda *a: seen.update(searcher=a[-2]) or [])
    app = FastAPI()
    app.include_router(agents_api.router, prefix="/v1/agents")
    client = TestClient(app)

    client.get("/v1/agents/search", params={"q": "investor", "as_handle": "@me"})
    assert seen["h"] == "me" and seen["searcher"] is me

    seen.clear()
    client.get("/v1/agents/search", params={"q": "investor"})
    assert seen["searcher"] is None


def test_suggested_people_mark_and_lead_with_two_way_matches(monkeypatch):
    from services import suggested_people

    def build(handle, headline, **extra):
        c = card(handle, headline)
        for k, v in extra.items():
            setattr(c, k, v)
        return c

    me = build("me", "Founder", working_on=["Building a startup", "Building with AI"])
    plain = build("aaa-plain", "Designer", working_on=["Building with AI"])
    wants_me = build("zzz-wants-me", "Investor", working_on=["Building with AI"], connect_with=["Founders"])
    rows = [{"handle": c.handle, "card": c.model_dump(mode="json")} for c in (plain, wants_me)]
    monkeypatch.setattr(suggested_people.cards_service, "get_card_by_handle", lambda h: me)
    monkeypatch.setattr(suggested_people.cards_service, "list_published_rows", lambda **kw: rows)
    monkeypatch.setattr(suggested_people, "outside_search_enabled", lambda: False)

    people = suggested_people.get_suggested_people("me")["people"]
    assert [p["handle"] for p in people] == ["zzz-wants-me", "aaa-plain"]
    assert [p["two_way"] for p in people] == [True, False]
