"""Integration test for the is_resolved nightly detector."""
import pytest
import pytest_asyncio

from app.services.resolution import run_resolution_detector

pytestmark = pytest.mark.integration

UID = "44440000-0000-0000-0000-000000000001"


@pytest_asyncio.fixture(autouse=True)
async def _user(client):
    from app.db import get_pool
    await get_pool().execute(
        "INSERT INTO users (id, email) VALUES ($1,$2) ON CONFLICT (id) DO NOTHING",
        UID, f"res-{UID}@test.local")


async def _seed(pool, predicate, name, etype, confidence, history):
    from app.services.mock_llm import mock_embed
    from app.db import to_pgvector
    eid = await pool.fetchval(
        "INSERT INTO entities (user_id, canonical_name, entity_type, embedding) VALUES ($1,$2,$3,$4::vector) RETURNING id",
        UID, name, etype, to_pgvector(mock_embed(name)))
    aid = await pool.fetchval(
        """INSERT INTO assertions (user_id, predicate, object_entity_id, confidence, source_system, decay_fn)
           VALUES ($1,$2,$3,$4,'chatgpt','none') RETURNING id""",
        UID, predicate, eid, confidence)
    for prev, new in history:
        await pool.execute(
            """INSERT INTO assertion_history (assertion_id, prev_confidence, new_confidence, change_reason)
               VALUES ($1,$2,$3,'new_evidence')""", aid, prev, new)
    return eid


async def test_resolution_emitted_then_deduped(client):
    from app.db import get_pool
    pool = get_pool()
    # frustration dropped 0.9 -> 0.5 (drop 0.4 > 0.25); same-domain expertise rose 0.5 -> 0.9 (rise 0.4 > 0.15)
    await _seed(pool, "is_frustrated_by", "rust borrow checker", "concept_topic", 0.5, [(None, 0.9)])
    await _seed(pool, "has_expertise_in", "rust borrow checker", "skill_domain", 0.9, [(0.5, 0.9)])

    first = await run_resolution_detector(pool)
    assert first["resolutions_emitted"] == 1
    n = await pool.fetchval(
        "SELECT count(*) FROM assertions WHERE user_id=$1 AND predicate='is_resolved' AND valid_until IS NULL", UID)
    assert n == 1

    second = await run_resolution_detector(pool)   # idempotent
    assert second["resolutions_emitted"] == 0
