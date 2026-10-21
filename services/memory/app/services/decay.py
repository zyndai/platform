"""Confidence decay + archival (brief §5.4, §9). The "evolving" half of ZYND.

Run nightly. For every active, decaying assertion, recompute confidence from its
age and half-life. Drop below 0.1 -> archive via valid_until (never DELETE).
Every change is logged to assertion_history with reason 'decay'.

Two modes. The legacy job multiplies the *already decayed* confidence by the decay factor of
the *total* age every night, so night n has applied roughly 0.5^(n(n+1)/2h): an is_working_on
(14-day half-life) at 0.9 was archived after ~9 days instead of ~44. With freshness v2 the
confidence is recomputed from the evidence each time:

    confidence = base_confidence x 0.5 ^ (days since last_seen_at / half-life)

which is idempotent (running twice changes nothing) and cannot over-decay. Facts that can go
stale (taxonomy.STALE_AFTER_DAYS) are never archived by age: staleness is a read-time state, so
they stay searchable by topic. Only facts that are not time-bound (beliefs, feelings, ...) are
archived below ARCHIVE_THRESHOLD.
"""
import re

import asyncpg

from app.config import settings
from app.taxonomy import STALE_AFTER_DAYS

ARCHIVE_THRESHOLD = 0.1  # brief §5.4 — archive when confidence drops below this

_HALFLIFE_RE = re.compile(r"exponential\(halflife=(\d+)d\)")


def parse_halflife_days(decay_fn: str) -> int | None:
    """Pull the half-life out of a decay_fn string. None for "none"/unparseable."""
    match = _HALFLIFE_RE.fullmatch(decay_fn)
    return int(match.group(1)) if match else None


def apply_decay(confidence: float, halflife_days: int, days_elapsed: float) -> float:
    decay_factor = 0.5 ** (days_elapsed / halflife_days)
    return round(confidence * decay_factor, 4)


MIN_CHANGE = 0.0001   # v2 skips writes smaller than this, so a second run in the same minute is a no-op


async def run_decay_job(pool: asyncpg.Pool) -> dict:
    """Decay all active assertions. Returns counts for observability."""
    if settings.freshness_v2:
        return await _run_decay_v2(pool)
    rows = await pool.fetch(
        """SELECT id, confidence, decay_fn,
                  EXTRACT(EPOCH FROM (now() - COALESCE(observed_at, extracted_at))) / 86400.0
                    AS days_elapsed
             FROM assertions
            WHERE valid_until IS NULL AND confidence > $1 AND decay_fn <> 'none'""",
        ARCHIVE_THRESHOLD,
    )

    decayed = 0
    archived = 0
    for row in rows:
        halflife = parse_halflife_days(row["decay_fn"])
        if halflife is None:
            continue
        old = round(float(row["confidence"]), 4)
        new = apply_decay(old, halflife, float(row["days_elapsed"]))

        if new < ARCHIVE_THRESHOLD:
            await _archive(pool, row["id"], old, new)
            archived += 1
        elif new < old:  # decay only ever decreases; skip no-op writes
            await _decay(pool, row["id"], old, new)
            decayed += 1

    return {"scanned": len(rows), "decayed": decayed, "archived": archived}


async def _run_decay_v2(pool: asyncpg.Pool) -> dict:
    """Recompute confidence from base_confidence and last_seen_at; idempotent."""
    rows = await pool.fetch(
        """SELECT id, predicate, confidence, decay_fn,
                  coalesce(base_confidence, confidence) AS base,
                  EXTRACT(EPOCH FROM (now() - coalesce(last_seen_at, observed_at, extracted_at))) / 86400.0
                    AS days_elapsed
             FROM assertions
            WHERE valid_until IS NULL AND decay_fn <> 'none'""",
    )
    decayed: list[tuple[float, object]] = []
    archived: list[tuple[float, object]] = []
    history: list[tuple[object, float, float]] = []
    for row in rows:
        halflife = parse_halflife_days(row["decay_fn"])
        if halflife is None:
            continue
        old = round(float(row["confidence"]), 4)
        new = apply_decay(float(row["base"]), halflife, max(float(row["days_elapsed"]), 0.0))
        if new < ARCHIVE_THRESHOLD and row["predicate"] not in STALE_AFTER_DAYS:
            archived.append((new, row["id"]))
            history.append((row["id"], old, new))
        elif abs(new - old) >= MIN_CHANGE:
            decayed.append((new, row["id"]))
            history.append((row["id"], old, new))

    if decayed or archived:
        async with pool.acquire() as conn, conn.transaction():
            await conn.executemany("UPDATE assertions SET confidence = $1 WHERE id = $2", decayed)
            await conn.executemany(
                "UPDATE assertions SET confidence = $1, valid_until = now() WHERE id = $2", archived)
            await conn.executemany(
                """INSERT INTO assertion_history (assertion_id, prev_confidence, new_confidence, change_reason)
                   VALUES ($1, $2, $3, 'decay')""",
                history,
            )
    return {"scanned": len(rows), "decayed": len(decayed), "archived": len(archived), "mode": "v2"}


async def _decay(pool: asyncpg.Pool, assertion_id, old: float, new: float) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE assertions SET confidence = $1 WHERE id = $2", new, assertion_id)
        await _log(conn, assertion_id, old, new)


async def _archive(pool: asyncpg.Pool, assertion_id, old: float, new: float) -> None:
    async with pool.acquire() as conn, conn.transaction():
        # Keep the decayed confidence AND mark it inactive — the row is never deleted.
        await conn.execute(
            "UPDATE assertions SET confidence = $1, valid_until = now() WHERE id = $2",
            new, assertion_id,
        )
        await _log(conn, assertion_id, old, new)


async def _log(conn: asyncpg.Connection, assertion_id, old: float, new: float) -> None:
    await conn.execute(
        """INSERT INTO assertion_history (assertion_id, prev_confidence, new_confidence, change_reason)
           VALUES ($1, $2, $3, 'decay')""",
        assertion_id, old, new,
    )


async def run_orphan_cleanup(pool: asyncpg.Pool) -> dict:
    """Delete entities that no assertion references at all (brief §9, weekly).

    Note: scoped to entities with ZERO references (active OR archived) — an
    archived assertion still FK-references its entity, so we cannot drop an
    entity while any history of it remains. trace_chunks retention is deliberately
    NOT implemented here: the trace layer is sacred (§14.2).
    """
    deleted = await pool.fetchval(
        """WITH gone AS (
             DELETE FROM entities e
              WHERE NOT EXISTS (
                SELECT 1 FROM assertions a
                 WHERE a.object_entity_id = e.id OR a.subject_entity_id = e.id)
             RETURNING 1)
           SELECT count(*) FROM gone""",
    )
    return {"entities_deleted": int(deleted)}
