"""Integration tests for the shared ingest service + topic-less recall (the MCP
`remember` / `get_my_context` paths)."""
from datetime import datetime, timezone

import pytest

from app.models import Turn
from app.services.export import active_context
from app.services.ingest import ingest_turns

pytestmark = pytest.mark.integration

UID = "11111111-1111-1111-1111-111111111111"
EMPTY_UID = "22222222-2222-2222-2222-222222222222"


class FakeArq:
    """Records enqueued jobs so ingest_turns can be tested without a live worker."""
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, fn, *args):
        self.jobs.append((fn, args))


async def test_ingest_turns_inserts_and_dedups(client):
    from app.db import get_pool
    pool = get_pool()
    arq = FakeArq()
    turns = [Turn(role="user", content="I am building an AI agent marketplace in Rust",
                  timestamp=datetime.now(timezone.utc))]

    inserted, skipped = await ingest_turns(pool, arq, UID, "claude", turns, min_chars=8)
    assert (inserted, skipped) == (1, 0)
    assert len(arq.jobs) == 1 and arq.jobs[0][0] == "chunk_processor"

    # Same text again -> deduped by content hash, no new enqueue.
    inserted2, skipped2 = await ingest_turns(pool, arq, UID, "claude", turns, min_chars=8)
    assert (inserted2, skipped2) == (0, 1)
    assert len(arq.jobs) == 1


async def test_ingest_turns_skips_assistant_and_short(client):
    from app.db import get_pool
    arq = FakeArq()
    turns = [
        Turn(role="assistant", content="A long assistant reply that must be ignored entirely."),
        Turn(role="user", content="short"),
        Turn(role="user", content="I am learning Rust and systems programming this year"),
    ]
    inserted, skipped = await ingest_turns(get_pool(), arq, UID, "claude", turns, min_chars=8)
    # assistant turn is dropped silently; only the short user turn counts as skipped.
    assert inserted == 1
    assert skipped == 1


async def test_active_context_empty_profile_returns_empty_list(client):
    from app.db import get_pool
    assert await active_context(get_pool(), EMPTY_UID, 10) == []


async def test_ingest_strips_nul_bytes_no_crash(client):
    from app.db import get_pool
    pool = get_pool()
    arq = FakeArq()
    turns = [Turn(role="user", content="I use Rust\x00 for systems work and async tokio runtimes",
                  timestamp=datetime.now(timezone.utc))]
    inserted, _ = await ingest_turns(pool, arq, UID, "claude", turns, min_chars=8)
    assert inserted == 1
    raw = await pool.fetchval("SELECT raw_text FROM trace_chunks WHERE user_id=$1 LIMIT 1", UID)
    assert "\x00" not in raw
