"""Concurrency + multi-user data-isolation tests for the ZYND MCP layer.

ZYND serves 1000+ simultaneous users over MCP. These tests verify three
properties under concurrency:

  1. Shared lazy-init state (the process-lifetime asyncpg/arq pools) is built
     exactly once even when many first requests race — no leaked pool.
  2. Every read/write is scoped to the caller's user_id — user A can never see,
     dedup against, or revoke user B's data.
  3. The module-level in-memory caches (threading.Lock guarded) don't corrupt
     under concurrent readers + writers.

Everything external (Postgres, Redis, Supabase) is mocked, so these run as unit
tests alongside the integration suite without touching a real database.

Run: .venv/bin/python -m pytest tests/test_concurrency_and_isolation.py -q
"""
import asyncio
import hashlib
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.mcp_http as m
from app.auth import issue_access_token
from app.models import Turn
from app.services.export import active_context
from app.services.ingest import ingest_turns
from app.services.matching import match_users
from app.services.sessions import tokens_revoked


# ── helpers ──────────────────────────────────────────────────────────────────


class _AcquireCtx:
    """Async-context-manager wrapper returning a fixed connection, so code using
    `async with pool.acquire() as conn:` works against a MagicMock pool."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


# ── Test group 1: pool lazy-init race condition ──────────────────────────────


async def test_concurrent_pool_init_creates_exactly_one_pool():
    # given — the process-lifetime pool is not yet initialized
    m._pool = None
    created_pools = []

    async def _fake_create_pool(*args, **kwargs):
        # simulate a slow connect so racing coroutines overlap inside the lock
        await asyncio.sleep(0.01)
        pool = MagicMock(name=f"pool-{len(created_pools)}")
        created_pools.append(pool)
        return pool

    # when — 10 coroutines all call _get_pool() simultaneously
    with patch("app.mcp_http.asyncpg.create_pool", side_effect=_fake_create_pool) as cp:
        results = await asyncio.gather(*[m._get_pool() for _ in range(10)])

    # then — create_pool ran exactly once and everyone got the SAME pool object
    assert cp.await_count == 1
    assert len(created_pools) == 1
    assert all(r is created_pools[0] for r in results)

    m._pool = None  # don't leak the mock into other tests


async def test_second_pool_call_reuses_cached_pool_without_locking():
    # given — a pool already initialized by a prior request
    m._pool = None
    sentinel = MagicMock(name="cached-pool")

    async def _fake_create_pool(*args, **kwargs):
        return sentinel

    with patch("app.mcp_http.asyncpg.create_pool", side_effect=_fake_create_pool) as cp:
        first = await m._get_pool()
        # when — many more callers arrive after init
        again = await asyncio.gather(*[m._get_pool() for _ in range(20)])

    # then — create_pool never runs a second time; the cached pool is returned
    assert cp.await_count == 1
    assert first is sentinel
    assert all(r is sentinel for r in again)

    m._pool = None


async def test_concurrent_arq_init_creates_exactly_one_pool():
    # given — the arq (Redis) pool is not yet initialized
    m._arq = None

    async def _fake_create(*args, **kwargs):
        await asyncio.sleep(0.01)
        return MagicMock(name="arq-pool")

    # when — 10 coroutines race to lazily create the arq pool
    with patch("app.mcp_http.create_pool", side_effect=_fake_create) as cp:
        results = await asyncio.gather(*[m._get_arq() for _ in range(10)])

    # then — exactly one arq pool exists and is shared by all callers
    assert cp.await_count == 1
    assert all(r is results[0] for r in results)

    m._arq = None


# ── Test group 2: user data isolation ────────────────────────────────────────


def _pool_returning_per_user(rows_by_user: dict[str, list[dict]]) -> AsyncMock:
    """A pool whose active_context query returns different rows keyed by the
    user_id bind param (the first positional arg to pool.fetch)."""
    pool = AsyncMock()

    async def _fetch(query, user_id, *rest):
        return rows_by_user.get(user_id, [])

    pool.fetch.side_effect = _fetch
    return pool


async def test_get_my_context_scoped_to_caller_user_id():
    # given — the pool returns different data for user_a vs user_b
    rows_by_user = {
        "user_a": [
            {"predicate": "is_building", "object": "a micro-SaaS", "object_type": "project",
             "confidence": 0.9, "observed_at": None},
        ],
        "user_b": [
            {"predicate": "lives_in", "object": "Berlin", "object_type": "place",
             "confidence": 0.8, "observed_at": None},
        ],
    }
    pool = _pool_returning_per_user(rows_by_user)

    # when — both users read their context concurrently
    ctx_a, ctx_b = await asyncio.gather(
        active_context(pool, "user_a", 20),
        active_context(pool, "user_b", 20),
    )

    # then — each caller sees ONLY their own facts, never the other's
    objs_a = {r["object"] for r in ctx_a}
    objs_b = {r["object"] for r in ctx_b}
    assert objs_a == {"a micro-SaaS"}
    assert objs_b == {"Berlin"}
    assert objs_a.isdisjoint(objs_b)


async def test_get_my_context_passes_caller_uid_as_sql_bind():
    # given — a pool that records the user_id bind param for every fetch
    seen_uids = []
    pool = AsyncMock()

    async def _fetch(query, user_id, *rest):
        seen_uids.append(user_id)
        return []

    pool.fetch.side_effect = _fetch

    # when — 50 distinct users query concurrently
    uids = [f"user-{i}" for i in range(50)]
    await asyncio.gather(*[active_context(pool, u, 10) for u in uids])

    # then — every query was scoped to its own caller's uid (no cross-talk)
    assert sorted(seen_uids) == sorted(uids)


# ── Test group 3: content-hash dedup is per-user (not global) ─────────────────


def _ingest_pool_capturing_hashes(existing_hashes: set[str]) -> tuple[AsyncMock, list[tuple[str, str]]]:
    """Pool that emulates the `ON CONFLICT (user_id, content_hash) DO NOTHING`
    INSERT: returns a row (id) only when (user_id, content_hash) is new.
    Records every (user_id, content_hash) it was asked to insert."""
    seen: list[tuple[str, str]] = []
    row_id = {"n": 0}
    pool = AsyncMock()

    async def _fetchrow(query, *args):
        # trace_chunks INSERT args: user_id, source, text, conv, turn, hash, ts
        user_id, content_hash = args[0], args[5]
        seen.append((user_id, content_hash))
        key = f"{user_id}:{content_hash}"
        if key in existing_hashes:
            return None  # ON CONFLICT DO NOTHING → no RETURNING row
        existing_hashes.add(key)
        row_id["n"] += 1
        return {"id": row_id["n"]}

    pool.fetchrow.side_effect = _fetchrow
    pool.execute.return_value = "OK"  # users upsert + last_active update
    return pool, seen


async def test_same_text_remembered_by_different_users_both_succeed():
    # given — two different users saving the IDENTICAL text
    text = "I am building a cross-AI memory layer for developers."
    turn = Turn(role="user", content=text, timestamp=datetime.now(timezone.utc))
    pool, seen = _ingest_pool_capturing_hashes(set())
    arq = AsyncMock()

    # when — both users ingest the same sentence concurrently
    (ins_a, _), (ins_b, _) = await asyncio.gather(
        ingest_turns(pool, arq, "user_a", "claude", [turn]),
        ingest_turns(pool, arq, "user_b", "claude", [turn]),
    )

    # then — BOTH inserts succeed: content_hash = sha256("user_id:text") is per-user
    assert ins_a == 1
    assert ins_b == 1

    hash_a = hashlib.sha256(f"user_a:{text}".encode()).hexdigest()
    hash_b = hashlib.sha256(f"user_b:{text}".encode()).hexdigest()
    assert hash_a != hash_b  # same text, different user → different hash
    assert ("user_a", hash_a) in seen
    assert ("user_b", hash_b) in seen


async def test_same_user_same_text_dedups_to_one_insert():
    # given — ONE user saving the same text twice
    text = "I am a senior staff engineer focused on distributed systems."
    turn = Turn(role="user", content=text, timestamp=datetime.now(timezone.utc))
    pool, _ = _ingest_pool_capturing_hashes(set())
    arq = AsyncMock()

    # when — the same user ingests the identical sentence twice
    (ins1, skip1), (ins2, skip2) = await asyncio.gather(
        ingest_turns(pool, arq, "user_a", "claude", [turn]),
        ingest_turns(pool, arq, "user_a", "claude", [turn]),
    )

    # then — exactly one insert survives across the two calls; the other dedups
    assert {ins1, ins2} == {0, 1}
    assert ins1 + ins2 == 1
    assert skip1 + skip2 == 1


# ── Test group 4: token revocation only affects the revoked user ──────────────


def _revocation_pool(revoked_at_by_user: dict[str, datetime | None]) -> AsyncMock:
    """Pool whose tokens_revoked_at lookup returns a per-user watermark."""
    pool = AsyncMock()

    async def _fetchval(query, user_id):
        return revoked_at_by_user.get(user_id)

    pool.fetchval.side_effect = _fetchval
    return pool


async def test_token_revocation_only_affects_one_user():
    # given — user_a signed out at now(); user_b never signed out
    now = datetime.now(timezone.utc)
    token_iat = _epoch(now) - 10  # both tokens were issued 10s ago
    pool = _revocation_pool({"user_a": now, "user_b": None})

    # when — check revocation for both users concurrently
    revoked_a, revoked_b = await asyncio.gather(
        tokens_revoked(pool, "user_a", token_iat),
        tokens_revoked(pool, "user_b", token_iat),
    )

    # then — only user_a's pre-signout token is dead; user_b's still valid
    assert revoked_a is True
    assert revoked_b is False


# ── Test group 5: match_users never returns the caller in results ─────────────


async def test_match_users_excludes_caller_from_results():
    # given — a pool where the SQL `ue.user_id <> $3` filter is honored: the
    #         caller's own row is excluded before rows come back
    caller = "caller-uid"
    pool = AsyncMock()

    async def _fetchval(query, *args):
        return "[0.1, 0.2, 0.3]"  # non-None self_vector so match proceeds

    async def _fetch(query, self_vec, cluster_type, excluded_uid, *rest):
        # emulate the DB applying `ue.user_id <> excluded_uid`
        candidate_rows = [
            {"user_id": caller, "display_name": "Me", "socials": None,
             "similarity": 0.99, "assertion_count": 10},
            {"user_id": "other-1", "display_name": "Alice", "socials": None,
             "similarity": 0.88, "assertion_count": 8},
        ]
        return [r for r in candidate_rows if str(r["user_id"]) != str(excluded_uid)]

    pool.fetchval.side_effect = _fetchval
    pool.fetch.side_effect = _fetch

    # when
    results = await match_users(pool, caller, "intent_cluster", 10)

    # then — the caller's own user_id is never surfaced as a match
    result_ids = {r["user_id"] for r in results}
    assert caller not in result_ids
    assert "other-1" in result_ids


async def test_match_users_returns_empty_when_no_self_vector():
    # given — the caller has no vector for that cluster yet
    pool = AsyncMock()
    pool.fetchval.return_value = None

    # when
    results = await match_users(pool, "new-user", "intent_cluster", 10)

    # then — empty results, and the DB is never scanned for candidates
    assert results == []
    pool.fetch.assert_not_called()


# ── Test group 6: cache thread-safety ────────────────────────────────────────


def test_discover_cache_thread_safety():
    # given — 50 threads hammering the discover cache concurrently
    from app.tools import zynd_network as zn

    with zn._DISCOVER_CACHE_LOCK:
        zn._DISCOVER_CACHE.clear()

    errors: list[Exception] = []
    barrier = threading.Barrier(50)

    def _worker(i: int):
        try:
            barrier.wait()  # maximize contention: everyone starts together
            for j in range(200):
                key = (f"q{i % 8}", (i + j) % 5)
                zn._discover_cache_put(key, {"status": "success", "worker": i, "j": j})
                got = zn._discover_cache_get(key)
                if got is not None:
                    # a cache hit must always be a well-formed dict
                    assert isinstance(got, dict)
                    assert got.get("status") == "success"
        except Exception as exc:  # capture, don't swallow — asserted below
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # then — no exceptions, cache stays bounded, every value is a valid dict
    assert not errors, f"cache corrupted under concurrency: {errors[:3]}"
    with zn._DISCOVER_CACHE_LOCK:
        assert len(zn._DISCOVER_CACHE) <= 64  # eviction keeps it bounded
        for _, (_expires, value) in zn._DISCOVER_CACHE.items():
            assert isinstance(value, dict)
            assert "status" in value
        zn._DISCOVER_CACHE.clear()


def test_search_cache_thread_safety():
    # given — 50 threads reading + writing the services search cache
    from app.tools import zynd_services as zs

    with zs._SEARCH_CACHE_LOCK:
        zs._SEARCH_CACHE.clear()

    errors: list[Exception] = []
    barrier = threading.Barrier(50)

    def _worker(i: int):
        try:
            barrier.wait()
            for j in range(200):
                key = (f"q{i % 8}", (i + j) % 5, "cat")
                zs._search_cache_put(key, {"status": "success", "count": j})
                got = zs._search_cache_get(key)
                if got is not None:
                    assert isinstance(got, dict)
                    assert got.get("status") == "success"
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # then — no corruption, bounded size, all values valid dicts
    assert not errors, f"search cache corrupted under concurrency: {errors[:3]}"
    with zs._SEARCH_CACHE_LOCK:
        assert len(zs._SEARCH_CACHE) <= 64
        for _, (_expires, value) in zs._SEARCH_CACHE.items():
            assert isinstance(value, dict)
            assert "status" in value
        zs._SEARCH_CACHE.clear()


# ── Test group 7: token issued AFTER revocation is valid ─────────────────────


async def test_new_token_after_revocation_is_valid():
    # given — user revoked at T; a NEW token is issued at T+1 (iat >= revoked_at)
    revoked_at = datetime.now(timezone.utc)
    new_token_iat = _epoch(revoked_at) + 1
    old_token_iat = _epoch(revoked_at) - 5
    pool = _revocation_pool({"user_a": revoked_at})

    # when — check both the pre-revocation and post-revocation token
    old_revoked, new_revoked = await asyncio.gather(
        tokens_revoked(pool, "user_a", old_token_iat),
        tokens_revoked(pool, "user_a", new_token_iat),
    )

    # then — the old token is dead, the freshly-minted one still works
    assert old_revoked is True
    assert new_revoked is False


async def test_same_second_token_is_revoked():
    # given — a token minted in the SAME second as the sign-out watermark.
    #         tokens_revoked now rejects any token issued at or before the
    #         revocation instant (<=), closing the same-second sign-out hole.
    revoked_at = datetime.now(timezone.utc)
    same_second_iat = int(revoked_at.timestamp())  # equal to the watermark
    pool = _revocation_pool({"user_a": revoked_at})

    # when
    revoked = await tokens_revoked(pool, "user_a", same_second_iat)

    # then — revoked (iat <= watermark)
    assert revoked is True


# ── Test group 8: 100 concurrent remember() calls from the same user ─────────


async def test_100_concurrent_remembers_same_user_dedup_to_one_insert():
    # given — the same user saving the same text 100 times at once
    text = "I am building ZYND, a cross-AI memory layer served over MCP."
    turn = Turn(role="user", content=text, timestamp=datetime.now(timezone.utc))
    existing: set[str] = set()
    lock = asyncio.Lock()
    inserts = {"n": 0}
    pool = AsyncMock()

    async def _fetchrow(query, *args):
        user_id, content_hash = args[0], args[5]
        key = f"{user_id}:{content_hash}"
        # single event loop → no true parallelism, but guard anyway to mirror the
        # DB's atomic ON CONFLICT semantics under interleaving
        async with lock:
            if key in existing:
                return None
            existing.add(key)
            inserts["n"] += 1
            return {"id": inserts["n"]}

    pool.fetchrow.side_effect = _fetchrow
    pool.execute.return_value = "OK"
    arq = AsyncMock()

    # when — 100 concurrent ingests of the identical single fact
    results = await asyncio.gather(
        *[ingest_turns(pool, arq, "user_a", "claude", [turn]) for _ in range(100)]
    )

    # then — exactly one insert wins; the other 99 are dedup skips
    total_inserted = sum(ins for ins, _ in results)
    total_skipped = sum(skip for _, skip in results)
    assert total_inserted == 1
    assert total_skipped == 99


# ── Test group 9: ZyndTokenVerifier concurrent token checks ──────────────────


async def test_verifier_concurrent_valid_jwts_all_resolve_correctly():
    # given — 100 distinct users each with a valid JWT
    user_ids = [f"00000000-0000-0000-0000-{i:012d}" for i in range(100)]
    tokens = {uid: issue_access_token(uid)[0] for uid in user_ids}
    verifier = m.ZyndTokenVerifier()

    mock_pool = AsyncMock()
    # patch the revocation check to a no-op so we exercise the JWT path only
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=mock_pool)):
        from app.services import sessions as sess_mod
        with patch.object(sess_mod, "tokens_revoked", AsyncMock(return_value=False)):
            # when — verify all 100 tokens simultaneously
            results = await asyncio.gather(
                *[verifier.verify_token(tokens[uid]) for uid in user_ids]
            )

    # then — no deadlock, and each token resolves to ITS OWN user_id (no mix-ups)
    resolved = {r.client_id for r in results}
    assert resolved == set(user_ids)
    for uid, result in zip(user_ids, results):
        assert result is not None
        assert result.client_id == uid
        assert "user" in result.scopes


async def test_verifier_concurrent_mixed_valid_and_garbage_tokens():
    # given — a mix of valid JWTs and garbage strings verified at once. Garbage
    #         falls to the opaque-token DB path; with the DB unreachable that
    #         path returns None (never raises).
    valid_ids = [f"00000000-0000-0000-0000-{i:012d}" for i in range(20)]
    valid_tokens = [issue_access_token(uid)[0] for uid in valid_ids]
    garbage = [f"not-a-jwt-{i}" for i in range(20)]
    verifier = m.ZyndTokenVerifier()

    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = None  # opaque-token lookup misses → None

    with patch("app.mcp_http._get_pool", AsyncMock(return_value=mock_pool)):
        from app.services import sessions as sess_mod
        with patch.object(sess_mod, "tokens_revoked", AsyncMock(return_value=False)):
            # when
            results = await asyncio.gather(
                *[verifier.verify_token(t) for t in valid_tokens + garbage]
            )

    # then — valid ones resolve, garbage ones are None; nothing crashes/deadlocks
    valid_results = results[:20]
    garbage_results = results[20:]
    assert {r.client_id for r in valid_results} == set(valid_ids)
    assert all(r is None for r in garbage_results)
