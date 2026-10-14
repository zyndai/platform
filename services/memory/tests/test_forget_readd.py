"""A fact the user forgot must be re-addable; duplicates must still be skipped.

ingest dedupes on sha256(user_id:text) in trace_chunks. Forgetting soft-deletes the
assertion but leaves the chunk, so re-reporting the identical sentence used to come back
as "nothing new" forever. trace_chunks is append-only, so the fix re-processes the
existing chunk instead of deleting or editing it.
"""
import pytest

from app.config import settings
from app.db import get_pool, to_pgvector
from app.models import Turn
from app.services.control import forget_fact
from app.services.ingest import ingest_turns
from app.services.mock_llm import mock_embed

pytestmark = pytest.mark.integration

SENTENCE = "The user has a tool: Codex"


class FakeArq:
    def __init__(self):
        self.jobs: list[tuple[str, str]] = []

    async def enqueue_job(self, name, *args):
        self.jobs.append((name, args[0]))


def _turns(text=SENTENCE):
    return [Turn(role="user", content=text, timestamp=None)]


async def _dev_uid() -> str:
    return await get_pool().fetchval("SELECT id FROM users WHERE email = $1", settings.dev_user_email)


async def _ingest(uid, arq):
    return await ingest_turns(get_pool(), arq, str(uid), "cards_mcp", _turns(), min_chars=8)


async def _assertion_from_chunk(uid, chunk_id, predicate="uses_tool", name="Codex"):
    pool = get_pool()
    eid = await pool.fetchval(
        "INSERT INTO entities (user_id,canonical_name,entity_type,embedding) "
        "VALUES ($1,$2,'skill_technical',$3::vector) RETURNING id",
        uid, name, to_pgvector(mock_embed(name)))
    return await pool.fetchval(
        "INSERT INTO assertions (user_id,predicate,object_entity_id,confidence,source_system,"
        "trace_chunk_id,decay_fn) VALUES ($1,$2,$3,0.8,'cards_mcp',$4,'none') RETURNING id",
        uid, predicate, eid, chunk_id)


async def _chunk_id(uid):
    return await get_pool().fetchval("SELECT id FROM trace_chunks WHERE user_id=$1", uid)


async def test_forgotten_fact_can_be_reported_again(client):
    uid, arq = await _dev_uid(), FakeArq()
    assert await _ingest(uid, arq) == (1, 0)
    chunk_id = await _chunk_id(uid)
    await _assertion_from_chunk(uid, chunk_id)

    assert await forget_fact(get_pool(), str(uid), "uses_tool", "Codex") is True

    # Same sentence again: used to be (0, 1) forever.
    assert await _ingest(uid, arq) == (1, 0)
    # The existing chunk is re-processed; nothing is added to or edited in trace_chunks.
    assert arq.jobs == [("chunk_processor", str(chunk_id)), ("chunk_processor", str(chunk_id))]
    assert await get_pool().fetchval("SELECT count(*) FROM trace_chunks WHERE user_id=$1", uid) == 1


async def test_failed_enqueue_never_deletes_an_existing_chunk(client):
    class DownArq:
        async def enqueue_job(self, *_a):
            raise ConnectionError("redis down")

    uid = await _dev_uid()
    await _ingest(uid, FakeArq())
    chunk_id = await _chunk_id(uid)
    await _assertion_from_chunk(uid, chunk_id)
    await forget_fact(get_pool(), str(uid), "uses_tool", "Codex")

    with pytest.raises(ConnectionError):
        await _ingest(uid, DownArq())
    # A re-processed chunk carries audit history and must survive; it can be retried.
    assert await _chunk_id(uid) == chunk_id
    assert await _ingest(uid, FakeArq()) == (1, 0)


async def test_failed_enqueue_still_rolls_back_a_new_chunk(client):
    class DownArq:
        async def enqueue_job(self, *_a):
            raise ConnectionError("redis down")

    uid = await _dev_uid()
    with pytest.raises(ConnectionError):
        await _ingest(uid, DownArq())
    assert await _chunk_id(uid) is None  # unchanged behavior: no orphan hash blocking retry


async def test_active_fact_is_still_deduped(client):
    uid, arq = await _dev_uid(), FakeArq()
    await _ingest(uid, arq)
    await _assertion_from_chunk(uid, await _chunk_id(uid))

    assert await _ingest(uid, arq) == (0, 1)
    assert len(arq.jobs) == 1


async def test_unprocessed_duplicate_is_still_deduped(client):
    uid, arq = await _dev_uid(), FakeArq()
    assert await _ingest(uid, arq) == (1, 0)
    assert await _ingest(uid, arq) == (0, 1)


async def test_decayed_fact_is_not_treated_as_forgotten(client):
    # valid_until is also set by the decay job. Only an explicit user forget re-opens ingest.
    uid, arq = await _dev_uid(), FakeArq()
    await _ingest(uid, arq)
    aid = await _assertion_from_chunk(uid, await _chunk_id(uid))
    await get_pool().execute("UPDATE assertions SET valid_until = now() WHERE id = $1", aid)

    assert await _ingest(uid, arq) == (0, 1)


async def test_other_users_forget_does_not_reopen(client):
    uid, arq = await _dev_uid(), FakeArq()
    pool = get_pool()
    # users survive the per-test truncate, so make the email unique per run
    other = await pool.fetchval(
        "INSERT INTO users (id, email) VALUES (gen_random_uuid(), "
        "'other-' || gen_random_uuid()::text || '@zynd.test') RETURNING id")
    await ingest_turns(pool, arq, str(other), "cards_mcp", _turns(), min_chars=8)
    await _assertion_from_chunk(other, await _chunk_id(other))
    await forget_fact(pool, str(other), "uses_tool", "Codex")

    # The dev user never reported it, so their first report is a normal insert.
    assert await _ingest(uid, arq) == (1, 0)
