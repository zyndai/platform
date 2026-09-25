"""
Tests for `agent.memory_client`'s confirm_fact/forget_fact matching logic.

The memory-layer API's /me/confirm and /me/forget need a {predicate, object}
FactRef body — assertions have no stable id, so there's nothing else to key
on. confirm_fact/forget_fact take a loose natural-language description (what
the LLM tools in mcp/tools/memory.py pass in) and must resolve it against
the user's current assertion graph before submitting a ref. These tests
verify that resolution logic without hitting the real network.
"""

from __future__ import annotations

import pytest

from agent import memory_client
from agent.memory_client import MemoryAssertion

FAKE_ASSERTIONS = [
    MemoryAssertion(
        statement="Works at Zynd AI as a founding engineer",
        predicate="works_at",
        object="Zynd AI",
        object_type="organization",
        confidence=0.8,
    ),
    MemoryAssertion(
        statement="Is allergic to peanuts",
        predicate="has_trait",
        object="peanuts",
        object_type="allergy",
        confidence=0.9,
    ),
]


async def _fake_list_assertions(user_id):
    return list(FAKE_ASSERTIONS)


@pytest.mark.asyncio
async def test_find_fact_ref_matches_on_full_statement(monkeypatch):
    monkeypatch.setattr(memory_client, "list_assertions", _fake_list_assertions)

    ref = await memory_client._find_fact_ref("user-1", "allergic to peanuts")
    assert ref == ("has_trait", "peanuts")


@pytest.mark.asyncio
async def test_find_fact_ref_matches_on_object_alone(monkeypatch):
    monkeypatch.setattr(memory_client, "list_assertions", _fake_list_assertions)

    ref = await memory_client._find_fact_ref("user-1", "peanuts")
    assert ref == ("has_trait", "peanuts")


@pytest.mark.asyncio
async def test_find_fact_ref_no_match_returns_none(monkeypatch):
    monkeypatch.setattr(memory_client, "list_assertions", _fake_list_assertions)

    ref = await memory_client._find_fact_ref("user-1", "loves hiking")
    assert ref is None


@pytest.mark.asyncio
async def test_find_fact_ref_empty_graph_returns_none(monkeypatch):
    async def empty(_user_id):
        return []

    monkeypatch.setattr(memory_client, "list_assertions", empty)

    ref = await memory_client._find_fact_ref("user-1", "peanuts")
    assert ref is None


@pytest.mark.asyncio
async def test_forget_fact_submits_resolved_ref(monkeypatch):
    monkeypatch.setattr(memory_client, "list_assertions", _fake_list_assertions)

    calls = []

    async def fake_forget_by_ref(user_id, predicate, obj):
        calls.append((user_id, predicate, obj))
        return True

    monkeypatch.setattr(memory_client, "forget_by_ref", fake_forget_by_ref)

    ok = await memory_client.forget_fact("user-1", "peanuts allergy")
    assert ok is True
    assert calls == [("user-1", "has_trait", "peanuts")]


@pytest.mark.asyncio
async def test_forget_fact_no_match_does_not_call_api(monkeypatch):
    monkeypatch.setattr(memory_client, "list_assertions", _fake_list_assertions)

    calls = []

    async def fake_forget_by_ref(user_id, predicate, obj):
        calls.append((user_id, predicate, obj))
        return True

    monkeypatch.setattr(memory_client, "forget_by_ref", fake_forget_by_ref)

    ok = await memory_client.forget_fact("user-1", "loves skiing")
    assert ok is False
    assert calls == []


@pytest.mark.asyncio
async def test_confirm_fact_submits_resolved_ref(monkeypatch):
    monkeypatch.setattr(memory_client, "list_assertions", _fake_list_assertions)

    calls = []

    async def fake_confirm_by_ref(user_id, predicate, obj):
        calls.append((user_id, predicate, obj))
        return True

    monkeypatch.setattr(memory_client, "confirm_by_ref", fake_confirm_by_ref)

    ok = await memory_client.confirm_fact("user-1", "Works at Zynd AI")
    assert ok is True
    assert calls == [("user-1", "works_at", "Zynd AI")]


def test_make_jwt_has_required_claims():
    """Regression test: the memory-layer validates `iss` and `typ` claims —
    a prior version used a `type` key (never checked) and no `iss` at all,
    which made every request 401 with 'invalid bearer token' regardless of
    whether the shared secret was correct."""
    import jwt as pyjwt

    token = memory_client._make_jwt("user-1")
    claims = pyjwt.decode(token, options={"verify_signature": False})
    assert claims["iss"] == "zynd"
    assert claims["typ"] == "access"
    assert claims["sub"] == "user-1"
