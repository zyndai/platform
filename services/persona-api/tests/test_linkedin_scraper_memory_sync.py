"""
Tests for the LinkedIn scraper service (backend/services/linkedin_scraper.py).

Covers the URL-required scrape contract (name guessing removed), the
latest-5-posts cap, and sync_profile_to_memory — which declares curated
facts (works_at / lives_in / has_skill) into the memory layer with
dedup against the existing assertion graph, ingesting an LLM-composed
summary only when new facts were declared.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from agent.memory_client import MemoryAssertion
from services.linkedin_scraper import scrape_recent_posts, scrape_user, sync_profile_to_memory


def _profile() -> dict:
    return {
        "headline": "CTO & co-founder",
        "location": "San Francisco, California",
        "experience": [
            {"title": "CTO", "companyName": "Lattice Labs"},
            {"title": "Software Engineer", "companyName": "Old Corp"},
        ],
        "skills": ["AI", "Python", "Rust", "Go", "TypeScript", "Java", "C", "Ruby", "C#", "Elixir"],
    }


def _assertion(predicate: str, obj: str) -> MemoryAssertion:
    return MemoryAssertion(
        statement=f"You {predicate} {obj}",
        predicate=predicate,
        object=obj,
        object_type="unknown",
        confidence=0.9,
    )


# ── Scrape contract ──────────────────────────────────────────────────


def test_scrape_user_requires_profile_url():
    mocks = {}

    async def run():
        with patch("services.linkedin_scraper._run_actor", new_callable=AsyncMock) as mock_run:
            mocks["run_actor"] = mock_run
            return await scrape_user("u1", profile_url=None)

    result = asyncio.run(run())
    assert result == {"status": "skipped", "reason": "no_profile_url"}
    mocks["run_actor"].assert_not_called()


def test_posts_actor_capped_at_five_latest():
    mocks = {}

    async def run():
        with patch("services.linkedin_scraper._run_actor", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = []
            mocks["run_actor"] = mock_run
            await scrape_recent_posts("https://www.linkedin.com/in/jane")

    asyncio.run(run())
    _, payload = mocks["run_actor"].call_args.args
    assert payload["maxPosts"] == 5


# ── Memory sync ──────────────────────────────────────────────────────


def test_sync_profile_to_memory_declares_only_new_facts():
    profile = _profile()
    existing = [_assertion("works_at", "CTO at Lattice Labs")]
    declared = []

    async def fake_declare(user_id, predicate, value):
        declared.append((predicate, value))
        return True

    async def run():
        with patch("agent.memory_client.list_assertions", new=AsyncMock(return_value=existing)), \
             patch("agent.memory_client.declare_fact", side_effect=fake_declare), \
             patch("agent.memory_client.ingest_turns", new=AsyncMock()), \
             patch("services.linkedin_scraper._compose_profile_summary", new=AsyncMock(return_value="x")):
            return await sync_profile_to_memory("u1", profile)

    result = asyncio.run(run())
    assert result["facts_declared"] == 9  # lives_in + 8 skills
    assert ("works_at", "CTO at Lattice Labs") not in declared
    assert ("lives_in", "San Francisco, California") in declared
    skill_values = [v for p, v in declared if p == "has_skill"]
    assert len(skill_values) == 8
    assert skill_values == ["AI", "Python", "Rust", "Go", "TypeScript", "Java", "C", "Ruby"]
    # 9th and 10th skills are beyond the cap.
    assert "C#" not in skill_values and "Elixir" not in skill_values


def test_sync_profile_to_memory_skips_summary_when_nothing_new():
    profile = _profile()
    existing = [
        _assertion("works_at", "CTO at Lattice Labs"),
        _assertion("lives_in", "San Francisco, California"),
    ] + [
        _assertion("has_skill", s)
        for s in ["AI", "Python", "Rust", "Go", "TypeScript", "Java", "C", "Ruby"]
    ]
    mocks = {}

    async def run():
        with patch("agent.memory_client.list_assertions", new=AsyncMock(return_value=existing)), \
             patch("agent.memory_client.declare_fact", new=AsyncMock()) as declare, \
             patch("agent.memory_client.ingest_turns", new=AsyncMock()) as ingest, \
             patch("services.linkedin_scraper._compose_profile_summary", new=AsyncMock(return_value="x")):
            mocks["declare"] = declare
            mocks["ingest"] = ingest
            return await sync_profile_to_memory("u1", profile)

    result = asyncio.run(run())
    assert result["facts_declared"] == 0
    mocks["declare"].assert_not_called()
    mocks["ingest"].assert_not_called()


def test_sync_profile_to_memory_ingests_summary_when_new_facts():
    profile = _profile()
    mocks = {}

    async def run():
        with patch("agent.memory_client.list_assertions", new=AsyncMock(return_value=[])), \
             patch("agent.memory_client.declare_fact", new=AsyncMock(return_value=True)), \
             patch("agent.memory_client.ingest_turns", new=AsyncMock()) as ingest, \
             patch("services.linkedin_scraper._compose_profile_summary",
                   new=AsyncMock(return_value="I am CTO at Lattice Labs")):
            mocks["ingest"] = ingest
            return await sync_profile_to_memory("u1", profile)

    result = asyncio.run(run())
    assert result["facts_declared"] == 10  # works_at + lives_in + 8 skills
    ingest = mocks["ingest"]
    ingest.assert_called_once()
    kwargs = ingest.call_args.kwargs
    assert kwargs["source_system"] == "linkedin"
    assert kwargs["turns"][0]["content"] == "I am CTO at Lattice Labs"


def test_sync_profile_to_memory_noop_when_memory_disabled():
    mocks = {}

    async def run():
        with patch("agent.memory_client.is_enabled", return_value=False), \
             patch("agent.memory_client.list_assertions", new=AsyncMock()) as listed, \
             patch("agent.memory_client.declare_fact", new=AsyncMock()) as declare, \
             patch("agent.memory_client.ingest_turns", new=AsyncMock()) as ingest:
            mocks["listed"] = listed
            mocks["declare"] = declare
            mocks["ingest"] = ingest
            return await sync_profile_to_memory("u1", _profile())

    result = asyncio.run(run())
    assert result["facts_declared"] == 0
    mocks["listed"].assert_not_called()
    mocks["declare"].assert_not_called()
    mocks["ingest"].assert_not_called()
