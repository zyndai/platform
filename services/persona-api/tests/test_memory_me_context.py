"""
Tests for the memory client's /me/context read path — client-side
relevance ranking, confidence filtering, and the k cap.

The persona JWT can't call the semantic /context/{user_id} endpoint
(memory layer rejects it with 403), so get_context reads /me/context and
ranks facts locally with _keyword_relevance.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from agent.memory_client import MemoryAssertion, _keyword_relevance, get_context


def test_keyword_relevance_scores_object_higher_than_statement():
    obj_match = MemoryAssertion(
        statement="You are working on BookCab", predicate="is_working_on",
        object="BookCab", object_type="project", confidence=0.6,
    )
    statement_only = MemoryAssertion(
        statement="You mentioned BookCab in passing", predicate="mentions",
        object="something-else", object_type="unknown", confidence=0.9,
    )
    assert _keyword_relevance("BookCab", obj_match) > _keyword_relevance("BookCab", statement_only)


def test_keyword_relevance_zero_for_no_overlap():
    a = MemoryAssertion(
        statement="You have expertise in Java", predicate="has_expertise_in",
        object="Java", object_type="skill", confidence=0.9,
    )
    assert _keyword_relevance("solidity smart contracts", a) == 0.0


def _fake_me_context_response(status: int, payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    return resp


def _fake_client(resp: MagicMock) -> MagicMock:
    """An async-context-manager stand-in for httpx.AsyncClient."""
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def _assertions():
    return [
        {"statement": "You are working on BookCab", "predicate": "is_working_on",
         "object": "BookCab", "object_type": "project", "confidence": 0.97},
        {"statement": "You are working on warden", "predicate": "is_working_on",
         "object": "warden", "object_type": "project", "confidence": 0.97},
        {"statement": "You have expertise in Java", "predicate": "has_expertise_in",
         "object": "Java", "object_type": "skill", "confidence": 0.97},
        {"statement": "You like coffee", "predicate": "is_interested_in",
         "object": "coffee", "object_type": "interest", "confidence": 0.4},
    ]


def test_get_context_uses_me_context_and_ranks_by_relevance():
    fake = _fake_client(_fake_me_context_response(
        200, {"assertions": _assertions(), "profile": None}
    ))

    async def run():
        with patch("agent.memory_client.is_enabled", return_value=True), \
             patch("agent.memory_client._make_jwt", return_value="jwt"), \
             patch("agent.memory_client._client", return_value=fake):
            return await get_context("u1", topic="BookCab projects", k=5, min_confidence=0.0)

    ctx = asyncio.run(run())
    assert ctx.error is None
    assert len(ctx.assertions) == 4
    # Topic matches rank above unrelated facts.
    assert ctx.assertions[0].object == "BookCab"
    assert ctx.assertions[1].object == "warden"


def test_get_context_filters_below_min_confidence_and_caps_at_k():
    fake = _fake_client(_fake_me_context_response(
        200, {"assertions": _assertions(), "profile": None}
    ))

    async def run():
        with patch("agent.memory_client.is_enabled", return_value=True), \
             patch("agent.memory_client._make_jwt", return_value="jwt"), \
             patch("agent.memory_client._client", return_value=fake):
            return await get_context("u1", topic="anything", k=2, min_confidence=0.9)

    ctx = asyncio.run(run())
    assert len(ctx.assertions) == 2
    assert all(a.confidence >= 0.9 for a in ctx.assertions)


def test_get_context_403_is_visible_not_silent():
    fake = _fake_client(_fake_me_context_response(403, {"detail": "no"}))

    async def run():
        with patch("agent.memory_client.is_enabled", return_value=True), \
             patch("agent.memory_client._make_jwt", return_value="jwt"), \
             patch("agent.memory_client._client", return_value=fake):
            return await get_context("u1", topic="anything")

    ctx = asyncio.run(run())
    assert ctx.error == "forbidden"
    assert ctx.assertions == []
