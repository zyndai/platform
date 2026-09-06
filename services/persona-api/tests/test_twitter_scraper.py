"""
Tests for the Twitter scraper service (backend/services/twitter_scraper.py).

Covers the handle-required scrape contract, tweet selection (retweets and
other-authors' tweets dropped), LLM fact-JSON parsing, and sync_to_memory —
which declares curated interest facts (is_interested_in) into the memory
layer with source_system="twitter", deduped against the existing assertion
graph, ingesting an LLM-composed summary only when new facts were declared.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from agent.memory_client import MemoryAssertion
from services.twitter_scraper import (
    _parse_facts_json,
    _select_tweets,
    normalize_handle,
    scrape_user,
    sync_to_memory,
)


def _assertion(predicate: str, obj: str) -> MemoryAssertion:
    return MemoryAssertion(
        statement=f"You {predicate} {obj}",
        predicate=predicate,
        object=obj,
        object_type="unknown",
        confidence=0.9,
    )


def _tweets() -> list[dict]:
    return [
        {"text": "Ship tiny LLM evals daily", "isRetweet": False,
         "author": {"userName": "jane"}},
        {"text": "RT @someone else's take", "isRetweet": True,
         "author": {"userName": "jane"}},
        {"text": "someone else's tweet", "isRetweet": False,
         "author": {"userName": "other"}},
        {"text": "Thinking about local-first apps", "isRetweet": False,
         "author": {"userName": "jane"}},
    ]


# ── Handle normalization ─────────────────────────────────────────────


def test_normalize_handle_accepts_bare_handle():
    assert normalize_handle("jane") == "jane"
    assert normalize_handle("@jane") == "jane"


def test_normalize_handle_accepts_profile_urls():
    assert normalize_handle("https://x.com/jane") == "jane"
    assert normalize_handle("https://twitter.com/jane/") == "jane"
    assert normalize_handle("https://x.com/@jane?ref=1") == "jane"


def test_normalize_handle_rejects_garbage():
    assert normalize_handle("") is None
    assert normalize_handle("has space") is None
    assert normalize_handle("way too long a handle here") is None
    assert normalize_handle("not a url.com/jane") is None


# ── Tweet selection ──────────────────────────────────────────────────


def test_select_tweets_drops_retweets_and_other_authors():
    selected = _select_tweets(_tweets(), "jane")
    texts = [t["text"] for t in selected]
    assert "Ship tiny LLM evals daily" in texts
    assert "Thinking about local-first apps" in texts
    assert "RT @someone else's take" not in texts
    assert "someone else's tweet" not in texts


def test_select_tweets_falls_back_to_own_retweets_when_no_originals():
    items = [
        {"text": "RT only retweets", "isRetweet": True, "author": {"userName": "jane"}},
        {"text": "RT another retweet", "isRetweet": True, "author": {"userName": "jane"}},
        {"text": "someone else's tweet", "isRetweet": False, "author": {"userName": "other"}},
    ]
    selected = _select_tweets(items, "jane")
    assert len(selected) == 2
    assert all(t["text"].startswith("RT") for t in selected)


def test_select_tweets_falls_back_to_raw_items_without_author_info():
    items = [{"text": "no author field", "isRetweet": False}]
    selected = _select_tweets(items, "jane")
    assert len(selected) == 1


# ── LLM fact JSON parsing ────────────────────────────────────────────


def test_parse_facts_json_bare():
    assert _parse_facts_json('{"interests": ["AI agents", "Rust"]}') == ["AI agents", "Rust"]


def test_parse_facts_json_code_fenced():
    raw = '```json\n{"interests": ["AI agents"]}\n```'
    assert _parse_facts_json(raw) == ["AI agents"]


def test_parse_facts_json_strips_bullets_and_dedupes():
    assert _parse_facts_json('{"interests": ["- AI agents", "AI agents", ""]}') == ["AI agents"]


def test_parse_facts_json_junk_returns_empty():
    assert _parse_facts_json("not json at all") == []
    assert _parse_facts_json("") == []


# ── Scrape contract ──────────────────────────────────────────────────


def test_scrape_user_requires_handle():
    mocks = {}

    async def run():
        with patch("services.twitter_scraper.scrape_tweets", new_callable=AsyncMock) as mock_run:
            mocks["run_actor"] = mock_run
            return await scrape_user("u1", handle=None)

    result = asyncio.run(run())
    assert result == {"status": "skipped", "reason": "no_handle"}
    mocks["run_actor"].assert_not_called()


def test_scrape_actor_payload_uses_handle_and_caps_tweets():
    mocks = {}

    async def run():
        with patch("services.twitter_scraper._run_actor", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = []
            mocks["run_actor"] = mock_run
            from services.twitter_scraper import scrape_tweets
            await scrape_tweets("jane")

    asyncio.run(run())
    payload = mocks["run_actor"].call_args.args[0]
    assert payload["twitterHandles"] == ["jane"]
    assert payload["maxItems"] == 50
    assert payload["sort"] == "Latest"


# ── Memory sync ──────────────────────────────────────────────────────


def test_sync_to_memory_declares_only_new_facts_with_twitter_tag():
    existing = [_assertion("is_interested_in", "AI agents")]
    declared = []

    async def fake_declare(user_id, predicate, value, source_system="user_confirmed"):
        declared.append((predicate, value, source_system))
        return True

    async def run():
        with patch("agent.memory_client.list_assertions", new=AsyncMock(return_value=existing)), \
             patch("agent.memory_client.declare_fact", side_effect=fake_declare), \
             patch("agent.memory_client.ingest_turns", new=AsyncMock()), \
             patch("services.twitter_scraper._compose_summary", new=AsyncMock(return_value="x")):
            return await sync_to_memory("u1", "jane", ["AI agents", "Rust"])

    result = asyncio.run(run())
    assert result["facts_declared"] == 1
    assert declared == [("is_interested_in", "Rust", "twitter")]


def test_sync_to_memory_ingests_summary_with_twitter_source():
    mocks = {}

    async def run():
        with patch("agent.memory_client.list_assertions", new=AsyncMock(return_value=[])), \
             patch("agent.memory_client.declare_fact", new=AsyncMock(return_value=True)), \
             patch("agent.memory_client.ingest_turns", new=AsyncMock()) as ingest, \
             patch("services.twitter_scraper._compose_summary",
                   new=AsyncMock(return_value="I tweet about AI agents")):
            mocks["ingest"] = ingest
            return await sync_to_memory("u1", "jane", ["AI agents"])

    result = asyncio.run(run())
    assert result["facts_declared"] == 1
    ingest = mocks["ingest"]
    ingest.assert_called_once()
    kwargs = ingest.call_args.kwargs
    assert kwargs["source_system"] == "twitter"
    assert kwargs["turns"][0]["content"] == "I tweet about AI agents"


def test_sync_to_memory_noop_when_memory_disabled():
    mocks = {}

    async def run():
        with patch("agent.memory_client.is_enabled", return_value=False), \
             patch("agent.memory_client.list_assertions", new=AsyncMock()) as listed, \
             patch("agent.memory_client.declare_fact", new=AsyncMock()) as declare, \
             patch("agent.memory_client.ingest_turns", new=AsyncMock()) as ingest:
            mocks["listed"] = listed
            mocks["declare"] = declare
            mocks["ingest"] = ingest
            return await sync_to_memory("u1", "jane", ["AI agents"])

    result = asyncio.run(run())
    assert result["facts_declared"] == 0
    mocks["listed"].assert_not_called()
    mocks["declare"].assert_not_called()
    mocks["ingest"].assert_not_called()
