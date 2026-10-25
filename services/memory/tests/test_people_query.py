"""Parsing "seed-stage investor who backs AI dev tools in India" into search filters."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import people_query as pq
from app.services.people_discovery import company_phrases, quickenrich_body
from app.services.people_query import parse_target, parse_target_heuristic


def test_the_plans_example_query_keeps_ai_and_india():
    q = parse_target_heuristic("seed-stage investor who backs AI dev tools in India")
    assert q.role == "investor"
    assert q.stage == "seed"
    assert q.topics == ("AI dev tools",)
    assert (q.location, q.country_code, q.locality) == ("India", "IN", "")


@pytest.mark.parametrize("text,role,topics,location,code,locality", [
    ("find me a rust engineer in Berlin", "engineer", ("rust",), "Berlin", "DE", "Berlin"),
    ("founders building climate tech in San Francisco", "founder", ("climate tech",),
     "San Francisco", "US", "San Francisco"),
    ("ML engineer from Bangalore working on computer vision", "ml", ("computer vision",),
     "Bengaluru", "IN", "Bengaluru"),
    ("angel investors in the US who like developer tools", "investor", ("developer tools",),
     "US", "US", ""),
    ("product manager at a fintech", "pm", ("fintech",), "", "", ""),
    ("CTO based in Lagos", "cto", (), "Lagos", "NG", "Lagos"),
])
def test_roles_topics_and_places(text, role, topics, location, code, locality):
    q = parse_target_heuristic(text)
    assert (q.role, q.topics, q.location, q.country_code, q.locality) == (role, topics, location, code, locality)


def test_unknown_place_is_kept_as_free_text():
    q = parse_target_heuristic("designer based in Kigali")
    assert q.location == "Kigali" and q.country_code == ""


def test_no_role_still_yields_topics():
    q = parse_target_heuristic("someone who knows kubernetes")
    assert q.role == "" and q.topics == ("kubernetes",) and q.titles == ()


def test_empty_and_whitespace_targets_are_empty():
    assert parse_target_heuristic("").raw == ""
    assert parse_target_heuristic("   ").topics == ()


def test_topics_are_capped_and_stage_is_not_a_topic():
    q = parse_target_heuristic("series a investors who like robotics, climate, fintech, biotech and gaming")
    assert q.stage == "series a" and "series" not in " ".join(q.topics).lower()
    assert len(q.topics) <= pq.MAX_TOPICS


def test_search_text_is_compact_and_readable():
    q = parse_target_heuristic("ML engineer from Bangalore working on computer vision")
    assert q.search_text() == "machine learning engineer computer vision Bengaluru"
    assert parse_target_heuristic("???").search_text() == "???"


# ── QuickEnrich filters (F1) ───────────────────────────────────────────────────────

def test_quickenrich_body_uses_title_country_and_company_keywords():
    q = parse_target_heuristic("seed-stage investor who backs AI dev tools in India")
    body = quickenrich_body(q, 10)
    assert body["title"]["include"][:3] == ["Investor", "Angel Investor", "Venture Partner"]
    assert "Grievance" in body["title"]["exclude"]
    assert body["country_code"] == {"include": ["IN"], "exclude": []}
    # the stage and the whole topic phrase, "AI" included (the old 3-letter rule dropped it)
    assert body["bio_li"]["include"] == ["seed", "AI dev tools"]
    assert "locality" not in body and body["per_page"] == 10


def test_quickenrich_body_adds_locality_for_a_city():
    body = quickenrich_body(parse_target_heuristic("founders building climate tech in San Francisco"), 5)
    assert body["locality"] == {"include": ["San Francisco"], "exclude": []}
    assert body["country_code"]["include"] == ["US"]


def test_bio_li_is_for_company_keywords_only_never_for_a_persons_skills():
    body = quickenrich_body(parse_target_heuristic("rust engineer in Berlin"), 5)
    assert "bio_li" not in body            # an engineer's skills are not their company's About text
    assert body["title"]["include"] == ["Software Engineer", "Developer", "Engineer"]
    assert body["country_code"]["include"] == ["DE"]


def test_a_location_alone_is_too_vague_to_search():
    assert quickenrich_body(parse_target_heuristic("people in India"), 5) is None
    assert quickenrich_body(parse_target_heuristic(""), 5) is None


def test_company_phrases_keep_topics_whole_and_drop_generic_ones():
    q = parse_target_heuristic("investor who backs developer tools and AI tools")
    assert company_phrases(q) == ["developer tools", "AI tools"]


# ── LLM refinement ──────────────────────────────────────────────────────────────

def _llm(content: str):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    return client


@pytest.fixture
def llm_on(monkeypatch):
    monkeypatch.setattr(pq.settings, "deepseek_api_key", "k")
    monkeypatch.setattr(pq.settings, "mock_llm", False)
    pq._cache.clear()


@pytest.mark.asyncio
async def test_parse_target_uses_the_llm_and_validates_its_output(llm_on, monkeypatch):
    client = _llm(json.dumps({"role": "venture capitalist", "stage": "Seed",
                              "topics": ["AI developer tools", "", 5], "location": "Bangalore"}))
    monkeypatch.setattr(pq, "_get_client", lambda: client)
    q = await parse_target("someone who funds early AI tooling around Bangalore")
    assert q.role == "investor" and q.stage == "seed"
    assert q.topics == ("AI developer tools",)
    assert (q.locality, q.country_code) == ("Bengaluru", "IN")


@pytest.mark.asyncio
async def test_parse_target_falls_back_to_the_heuristic_when_the_llm_fails(llm_on, monkeypatch):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("timeout"))
    monkeypatch.setattr(pq, "_get_client", lambda: client)
    q = await parse_target("investor in India")
    assert q.role == "investor" and q.country_code == "IN"


@pytest.mark.asyncio
async def test_parse_target_ignores_garbage_llm_output(llm_on, monkeypatch):
    monkeypatch.setattr(pq, "_get_client", lambda: _llm("[1, 2, 3]"))
    q = await parse_target("designer in Pune")
    assert q.role == "designer" and q.locality == "Pune"


@pytest.mark.asyncio
async def test_parse_target_caches_llm_results(llm_on, monkeypatch):
    client = _llm(json.dumps({"role": "founder", "topics": ["climate"]}))
    monkeypatch.setattr(pq, "_get_client", lambda: client)
    await parse_target("Climate founders")
    await parse_target("climate founders")
    assert client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_parse_target_never_calls_the_llm_in_mock_mode(monkeypatch):
    monkeypatch.setattr(pq.settings, "mock_llm", True)
    monkeypatch.setattr(pq, "_get_client", lambda: pytest.fail("should not be called"))
    assert (await parse_target("investor in India")).role == "investor"


def test_places_written_with_commas_are_still_found():
    # "City, Country" is how locations are written everywhere (Cards, LinkedIn, profiles).
    q = parse_target_heuristic("designer in Pune, India")
    assert (q.location, q.country_code, q.locality) == ("Pune", "IN", "Pune")
    q = parse_target_heuristic("founder, San Francisco, CA")
    assert (q.country_code, q.locality) == ("US", "San Francisco")
