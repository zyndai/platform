"""Integration tests for user-control endpoints: confirm, forget, matches."""
import pytest

from app.config import settings
from app.db import get_pool, to_pgvector

pytestmark = pytest.mark.integration
AUTH = {"Authorization": f"Bearer {settings.dev_bearer_token}"}


async def _dev_uid() -> str:
    return await get_pool().fetchval("SELECT id FROM users WHERE email = $1", settings.dev_user_email)


async def _seed(uid, predicate, name, etype, conf):
    from app.services.mock_llm import mock_embed
    pool = get_pool()
    eid = await pool.fetchval(
        "INSERT INTO entities (user_id,canonical_name,entity_type,embedding) VALUES ($1,$2,$3,$4::vector) RETURNING id",
        uid, name, etype, to_pgvector(mock_embed(name)))
    await pool.execute(
        "INSERT INTO assertions (user_id,predicate,object_entity_id,confidence,source_system,decay_fn) VALUES ($1,$2,$3,$4,'chatgpt','none')",
        uid, predicate, eid, conf)


async def test_confirm_boosts_to_max_and_marks_source(client):
    uid = await _dev_uid()
    await _seed(uid, "is_learning", "Rust", "skill_technical", 0.7)

    r = await client.post("/me/confirm", headers=AUTH, json={"predicate": "is_learning", "object": "Rust"})
    assert r.status_code == 200

    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT confidence, source_system FROM assertions WHERE user_id=$1 AND predicate='is_learning'", uid)
    assert round(float(row["confidence"]), 2) == 0.97
    assert row["source_system"] == "user_confirmed"
    assert await pool.fetchval(
        "SELECT count(*) FROM assertion_history WHERE change_reason='user_confirmed'") >= 1


async def test_forget_soft_deletes_keeps_audit(client):
    uid = await _dev_uid()
    await _seed(uid, "is_building", "thing X", "project_venture", 0.8)

    r = await client.post("/me/forget", headers=AUTH, json={"predicate": "is_building", "object": "thing X"})
    assert r.status_code == 200

    graph = await client.get("/me/graph", headers=AUTH)
    assert "thing X" not in {a["object"] for a in graph.json()}  # no longer active

    pool = get_pool()
    row = await pool.fetchrow("SELECT valid_until FROM assertions WHERE user_id=$1 AND predicate='is_building'", uid)
    assert row["valid_until"] is not None  # archived, not hard-deleted
    assert await pool.fetchval(
        "SELECT count(*) FROM assertion_history WHERE change_reason='user_deleted'") >= 1


async def test_confirm_unknown_fact_returns_404(client):
    r = await client.post("/me/confirm", headers=AUTH, json={"predicate": "is_learning", "object": "Nonexistent"})
    assert r.status_code == 404


async def test_my_matches_returns_list(client):
    uid = await _dev_uid()
    r = await client.get("/me/matches", headers=AUTH)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_my_matches_rejects_bad_cluster(client):
    r = await client.get("/me/matches?cluster_type=bogus", headers=AUTH)
    assert r.status_code == 400
