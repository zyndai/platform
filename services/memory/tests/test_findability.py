"""Integration tests for the v2 findability card (consent layer over matching)."""
import pytest
import pytest_asyncio

from app.services.findability import declare, get_card, get_suggestions, approve, revoke

pytestmark = pytest.mark.integration

UID = "33330000-0000-0000-0000-000000000001"


@pytest_asyncio.fixture(autouse=True)
async def _user(client):
    from app.db import get_pool
    await get_pool().execute(
        "INSERT INTO users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
        UID, f"find-{UID}@test.local")


async def _seed_inferred(pool, uid, predicate, name, etype, is_public=False):
    from app.services.mock_llm import mock_embed
    from app.db import to_pgvector
    eid = await pool.fetchval(
        "INSERT INTO entities (user_id, canonical_name, entity_type, embedding) VALUES ($1,$2,$3,$4::vector) RETURNING id",
        uid, name, etype, to_pgvector(mock_embed(name)))
    await pool.execute(
        """INSERT INTO assertions (user_id, predicate, object_entity_id, confidence, source_system,
             source, decay_fn, is_public) VALUES ($1,$2,$3,0.8,'chatgpt','inferred','none',$4)""",
        uid, predicate, eid, is_public)


async def test_inferred_findability_facts_are_private_and_suggested(client):
    from app.db import get_pool
    pool = get_pool()
    await _seed_inferred(pool, UID, "is_building", "ai agent marketplace", "project_venture")
    await _seed_inferred(pool, UID, "believes", "privacy matters", "belief_opinion")  # not findability

    # #given an inferred findability fact #then it is NOT on the public card yet
    assert await get_card(pool, UID) == []
    # #then it shows up as a suggestion ("keep this?"); the belief never does
    sugg = await get_suggestions(pool, UID)
    assert [s["predicate"] for s in sugg] == ["is_building"]


async def test_approve_publishes_onto_card(client):
    from app.db import get_pool
    pool = get_pool()
    await _seed_inferred(pool, UID, "is_learning", "rust async", "skill_domain")

    ok = await approve(pool, UID, "is_learning", "Rust Async")  # case-insensitive
    assert ok is True
    card = await get_card(pool, UID)
    assert ("is_learning", "rust async") in [(c["predicate"], c["object"]) for c in card]
    assert card[0]["source"] == "both"  # inferred -> both after approval

    # #when revoked #then it leaves the card but stays in memory
    assert await revoke(pool, UID, "is_learning", "rust async") is True
    assert await get_card(pool, UID) == []


async def test_approve_rejects_non_findability_predicate(client):
    from app.db import get_pool
    pool = get_pool()
    await _seed_inferred(pool, UID, "believes", "speed over polish", "belief_opinion")
    assert await approve(pool, UID, "believes", "speed over polish") is False


async def test_declare_creates_public_fact(client):
    from app.db import get_pool
    pool = get_pool()
    await declare(pool, UID, "is_building", "developer tooling startup")
    card = await get_card(pool, UID)
    row = next(c for c in card if c["object"] == "developer tooling startup")
    assert row["source"] == "declared"


async def test_declare_validates_enum_values(client):
    from app.db import get_pool
    pool = get_pool()
    await declare(pool, UID, "is_seeking", "co_founder")          # valid
    with pytest.raises(ValueError):
        await declare(pool, UID, "is_seeking", "world domination")  # not in allowed set
    with pytest.raises(ValueError):
        await declare(pool, UID, "believes", "anything")            # not declarable
