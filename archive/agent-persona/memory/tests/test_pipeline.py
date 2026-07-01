"""Integration tests — ingest endpoint + worker pipeline against zynd_test.

Marked `integration`; auto-skips (via the _test_db fixture) if Postgres is down.
Runs with MOCK_LLM so no API keys / spend are needed.
"""
import pytest

from app.config import settings
from app.db import get_pool

pytestmark = pytest.mark.integration

AUTH = {"Authorization": f"Bearer {settings.dev_bearer_token}"}

_CONVO = {
    "conversation_id": "conv_test",
    "source_system": "chatgpt",
    "turns": [
        {"role": "user", "content": "I am learning Rust async runtimes and building an ML engineer marketplace for India."},
        {"role": "assistant", "content": "Here are some tokio tips for you."},
        {"role": "user", "content": "ok"},
    ],
}


async def _dev_user_id() -> str:
    return await get_pool().fetchval("SELECT id FROM users WHERE email = $1", settings.dev_user_email)


async def test_ingest_inserts_user_turn_and_strips_rest(client):
    r = await client.post("/ingest", json=_CONVO, headers=AUTH)
    assert r.status_code == 200
    # one long user turn inserted; "ok" (<40 chars) skipped; assistant stripped (not counted).
    assert r.json() == {"status": "ok", "chunks_inserted": 1, "chunks_skipped": 1}

    pool = get_pool()
    assert await pool.fetchval("SELECT count(*) FROM trace_chunks") == 1
    # Assistant content must never be stored (brief §14.6).
    assert await pool.fetchval("SELECT count(*) FROM trace_chunks WHERE raw_text ILIKE '%tokio%'") == 0


async def test_ingest_dedup_skips_seen_chunks(client):
    await client.post("/ingest", json=_CONVO, headers=AUTH)
    r2 = await client.post("/ingest", json=_CONVO, headers=AUTH)
    assert r2.json() == {"status": "ok", "chunks_inserted": 0, "chunks_skipped": 2}
    assert await get_pool().fetchval("SELECT count(*) FROM trace_chunks") == 1


async def test_ingest_rejects_bad_token(client):
    r = await client.post("/ingest", json=_CONVO, headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


async def test_worker_produces_assertions(client):
    from app.worker import chunk_processor

    await client.post("/ingest", json=_CONVO, headers=AUTH)
    pool = get_pool()
    chunk_id = await pool.fetchval("SELECT id FROM trace_chunks LIMIT 1")

    result = await chunk_processor({}, str(chunk_id))
    assert result["status"] == "ok"
    assert result["assertions"] == 2  # is_learning + is_building

    # Chunk got embedded; entities + assertions + history written.
    assert await pool.fetchval("SELECT embedding IS NOT NULL FROM trace_chunks WHERE id = $1", chunk_id)
    assert await pool.fetchval("SELECT count(*) FROM entities") == 2
    assert await pool.fetchval("SELECT count(*) FROM assertions") == 2
    assert await pool.fetchval("SELECT count(*) FROM assertion_history") == 2

    learning = await pool.fetchval(
        "SELECT confidence FROM assertions WHERE predicate = 'is_learning'")
    assert learning == pytest.approx(0.72, abs=1e-4)  # 0.9 * 0.8


async def test_worker_restatement_is_bayesian_update_not_duplicate(client):
    from app.worker import chunk_processor

    async def ingest_and_process(text: str):
        await client.post("/ingest", json={"source_system": "chatgpt",
                                           "turns": [{"role": "user", "content": text}]}, headers=AUTH)
        pool = get_pool()
        cid = await pool.fetchval(
            "SELECT id FROM trace_chunks WHERE embedding IS NULL ORDER BY ingested_at DESC LIMIT 1")
        await chunk_processor({}, str(cid))

    # Both sentences are >=40 chars and capture the identical object name
    # "Rust async runtimes" (comma ends the capture), so the entity merges.
    await ingest_and_process("I am currently learning Rust async runtimes, it is genuinely fun.")
    await ingest_and_process("Honestly I keep learning Rust async runtimes, every single day.")

    pool = get_pool()
    # Same entity reused, single assertion, confidence climbed, version bumped.
    assert await pool.fetchval("SELECT count(*) FROM entities WHERE entity_type = 'skill_technical'") == 1
    row = await pool.fetchrow("SELECT confidence, version FROM assertions WHERE predicate = 'is_learning'")
    assert row["version"] == 2
    assert row["confidence"] == pytest.approx(0.9216, abs=1e-4)
    assert await pool.fetchval("SELECT count(*) FROM assertion_history WHERE change_reason = 'new_evidence'") == 2


async def test_graph_endpoint_returns_active_assertions(client):
    from app.worker import chunk_processor

    await client.post("/ingest", json=_CONVO, headers=AUTH)
    chunk_id = await get_pool().fetchval("SELECT id FROM trace_chunks LIMIT 1")
    await chunk_processor({}, str(chunk_id))

    uid = await _dev_user_id()
    r = await client.get(f"/users/{uid}/graph", headers=AUTH)
    assert r.status_code == 200
    predicates = {a["predicate"] for a in r.json()}
    assert predicates == {"is_learning", "is_building"}

    # Cannot read another user's graph.
    other = await client.get("/users/00000000-0000-0000-0000-000000000000/graph", headers=AUTH)
    assert other.status_code == 403
