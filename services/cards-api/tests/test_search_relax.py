"""Soft topics, filter relaxation, country matching and name lookup (people search plan, Phase 0)."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import agents as agents_api
from models.card import AgentProfileCard
from services import geo, lookup as lookup_service
from services import search as search_service


def _card(handle, *, name="", headline="", location="", skills=(), summary="", memory=()):
    return {
        "card": AgentProfileCard(
            id=f"id-{handle}", status="published", handle=handle,
            identity={"name": name or handle.title(), "headline": headline, "location": location,
                      "avatar_url": "", "links": {}},
            summary=summary, skills=[{"name": s} for s in skills],
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


def run(**kw):
    return search_service.search_agents(include_unclaimed=True, **kw)


def handles(**kw):
    return [r["handle"] for r in run(**kw)]


# ── geo ──────────────────────────────────────────────────────────────────────────

def test_a_country_contains_its_cities():
    assert geo.same_country("India", "Gurgaon")
    assert geo.same_country("India", "Bengaluru, Karnataka")
    assert not geo.same_country("India", "London, UK")
    assert not geo.same_country("Pune", "Mumbai"), "a city is not widened implicitly"
    assert geo.country_code("Pune, India") == "IN"
    assert geo.widen("Pune") == "India" and geo.widen("India") == "" and geo.widen("Atlantis") == ""
    assert geo.widen("New York") == "United States"


# ── topics never filter ──────────────────────────────────────────────────────────

def test_topics_score_but_never_remove_a_card(cards):
    cards += [_card("rustacean", headline="Rust engineer", summary="Systems programming"),
              _card("webdev", headline="Web engineer", summary="Frontend")]
    assert set(handles(q="engineer")) == {"rustacean", "webdev"}
    with_topics = handles(q="engineer", topics="rust,quantum basket weaving")
    assert set(with_topics) == {"rustacean", "webdev"}, "an unmatched topic must not drop anyone"
    assert with_topics[0] == "rustacean", "a matching topic ranks higher"


def test_skills_still_filter(cards):
    cards += [_card("rustacean", headline="Rust engineer", skills=["Rust"]), _card("webdev", headline="Web engineer")]
    assert handles(q="engineer", skills="rust") == ["rustacean"]


# ── relax ────────────────────────────────────────────────────────────────────────

def test_without_relax_filters_are_strict(cards):
    cards.append(_card("pune_angel", headline="Angel investor", location="Pune, India"))
    assert handles(q="lawyer", role="lawyer", location="Pune") == []


def test_relax_returns_strict_matches_first_then_looser_ones_marked(cards):
    cards += [
        _card("mum_investor", headline="Seed investor", location="Mumbai, India"),
        _card("pune_investor", headline="Angel investor", location="Pune, India"),
        _card("london_investor", headline="Seed investor", location="London, UK"),
    ]
    found = run(q="investor in Pune", role="investor", location="Pune", relax=True)
    assert [r["handle"] for r in found][0] == "pune_investor"
    assert "relaxed" not in found[0]
    by = {r["handle"]: r for r in found}
    assert by["mum_investor"]["relaxed"] == ["location"]
    assert any("Pune" in reason and "closest match: India" in reason for reason in by["mum_investor"]["match_reasons"])
    # London is not in India: only the pass that drops the location finds it, so it ranks last
    assert [r["handle"] for r in found][-1] == "london_investor"
    assert by["london_investor"]["relaxed"] == ["location"]


def test_relax_stops_as_soon_as_there_are_enough(cards):
    cards += [_card(f"inv{i}", headline="Investor", location="Pune") for i in range(3)]
    cards.append(_card("elsewhere", headline="Investor", location="Paris"))
    assert handles(q="investor", role="investor", location="Pune", limit=3, relax=True) == ["inv0", "inv1", "inv2"]


def test_relax_drops_skills_first(cards):
    cards += [_card("backend", headline="Backend engineer", location="Pune", summary="Writes rust on weekends")]
    found = run(q="rust", role="engineer", location="Pune", skills="rust", relax=True)
    assert [r["handle"] for r in found] == ["backend"]
    assert found[0]["relaxed"] == ["skills"]
    assert any("Skill filter relaxed" in r for r in found[0]["match_reasons"])


def test_a_card_that_is_not_the_role_needs_real_evidence_to_survive_the_last_relaxation(cards):
    """Dropping the role is the loosest step: a designer who only shares the city and one word is
    not a result (the score floor counts the missing role), unlike a near-miss on place or skills."""
    cards += [_card("designer", headline="Product designer and rust fan", location="Pune")]
    assert run(q="rust", role="engineer", location="Pune", skills="rust", relax=True) == []


def test_a_country_filter_matches_a_city_only_card(cards):
    cards.append(_card("gurgaon_vc", headline="Seed investor", location="Gurgaon"))
    found = run(q="investors in India", role="investor", location="India")
    assert [r["handle"] for r in found] == ["gurgaon_vc"] and "relaxed" not in found[0]


# ── endpoint ─────────────────────────────────────────────────────────────────────

def _client(monkeypatch, seen):
    monkeypatch.setattr(agents_api.search_service, "search_agents", lambda *a, **kw: seen.update(args=a, kw=kw) or [])
    monkeypatch.setattr(agents_api.cards_service, "claimed_by_handles", lambda handles: {})
    app = FastAPI()
    app.include_router(agents_api.router, prefix="/v1/agents")
    return TestClient(app)


def test_search_endpoint_passes_topics_and_relax_only_when_given(monkeypatch):
    seen = {}
    client = _client(monkeypatch, seen)
    client.get("/v1/agents/search", params={"q": "x"})
    assert seen["kw"] == {}
    body = client.get("/v1/agents/search", params={"q": "x", "topics": "AI,dev tools", "relax": "true"}).json()
    assert seen["kw"] == {"topics": "AI,dev tools", "relax": True}
    assert body["query"]["topics"] == "AI,dev tools" and body["query"]["relax"] is True


# ── lookup ───────────────────────────────────────────────────────────────────────

class _Query:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def __getattr__(self, name):
        def call(*a, **kw):
            self.calls.append((name, a))
            return self
        return call

    @property
    def not_(self):
        return self

    def execute(self):
        return MagicMock(data=self.rows)


def _row(handle, name, headline=""):
    return {"id": f"id-{handle}", "handle": handle, "owner_email": "x@y.z",
            "card": {"identity": {"name": name, "headline": headline, "location": "Gurgaon",
                                  "links": {"linkedin": "https://linkedin.com/in/c"}}, "skills": [{"name": "Python"}]}}


def test_lookup_ranks_exact_then_prefix_then_contains(monkeypatch):
    rows = [_row("ex-chandan-lee", "Ex Chandani"), _row("chandan-kumar-2en8", "Chandan Kumar"), _row("chandan", "Chandan"),
            _row("someone-else", "Michandana")]
    q = _Query(rows)
    monkeypatch.setattr(lookup_service.network, "_sb", lambda: MagicMock(table=lambda name: q))
    found = lookup_service.lookup_by_name("chandan")
    assert [r["handle"] for r in found] == ["chandan", "chandan-kumar-2en8", "ex-chandan-lee", "someone-else"]
    assert found[0]["match_reasons"] == ["Name match"] and found[0]["match_score"] > found[1]["match_score"]
    assert found[1]["linkedin_url"] == "https://linkedin.com/in/c" and found[1]["skills"] == ["Python"]
    assert any(name == "not_" or name == "is_" for name, _ in q.calls), "unclaimed cards are excluded by default"
    assert "email" not in " ".join(found[0])


def test_lookup_ignores_filter_syntax_and_short_input(monkeypatch):
    q = _Query([])
    monkeypatch.setattr(lookup_service.network, "_sb", lambda: MagicMock(table=lambda name: q))
    assert lookup_service.lookup_by_name("a") == []
    lookup_service.lookup_by_name('chandan"),handle.eq.x(')
    pattern = next(args[0] for name, args in q.calls if name == "or_")
    # the typed quote, comma and parentheses are gone, so the text cannot close its own quotes
    assert pattern == ('handle.ilike."*chandan handle.eq.x*",card->identity->>name.ilike."*chandan handle.eq.x*"')


def test_lookup_endpoint_returns_claimed_people_and_is_rate_limited(monkeypatch):
    monkeypatch.setattr(agents_api.lookup_service, "lookup_by_name",
                        lambda name, limit, unclaimed: [{"handle": "chandan-kumar-2en8", "agent_id": "a1", "name": name}])
    monkeypatch.setattr(agents_api.cards_service, "claimed_by_handles", lambda handles: {"chandan-kumar-2en8": True})
    lookup_service._hits.clear()
    app = FastAPI()
    app.include_router(agents_api.router, prefix="/v1/agents")
    client = TestClient(app)
    body = client.get("/v1/agents/lookup", params={"name": "@Chandan"}).json()
    assert body["results"][0]["claimed"] is True and body["results"][0]["name"] == "Chandan"
    assert client.get("/v1/agents/lookup", params={"name": "x"}).status_code == 422
    for _ in range(lookup_service.RATE_LIMIT):
        last = client.get("/v1/agents/lookup", params={"name": "chandan"})
    assert last.status_code == 429
    lookup_service._hits.clear()
