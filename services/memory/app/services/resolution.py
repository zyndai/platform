"""v2 nightly resolution detector — emits the `is_resolved` system predicate.

A frustration is considered resolved when, over the last 90 days:
  1. its `is_frustrated_by` confidence dropped by > 0.25, AND
  2. a `has_expertise_in`/`has_skill` confidence rose by > 0.15, AND
  3. the two assertions' object embeddings are within cosine 0.80 (same domain).
This is never extracted or declared — only emitted here. Confidence 0.80, decays 6mo.
"""
import asyncpg

from app.taxonomy import decay_fn_for

DROP_THRESHOLD = 0.25
RISE_THRESHOLD = 0.15
DOMAIN_SIMILARITY = 0.80
RESOLVED_CONFIDENCE = 0.80

_PAIR_SQL = """
WITH frustrations AS (
  SELECT a.object_entity_id AS eid, e.embedding, a.confidence AS cur,
         (SELECT max(h.new_confidence) FROM assertion_history h
            WHERE h.assertion_id = a.id AND h.changed_at > now() - interval '90 days') AS peak
    FROM assertions a JOIN entities e ON e.id = a.object_entity_id
   WHERE a.user_id = $1 AND a.predicate = 'is_frustrated_by'
     AND a.valid_until IS NULL AND e.embedding IS NOT NULL
), expertise AS (
  SELECT e.embedding, a.confidence AS cur,
         (SELECT min(h.prev_confidence) FROM assertion_history h
            WHERE h.assertion_id = a.id AND h.changed_at > now() - interval '90 days') AS base
    FROM assertions a JOIN entities e ON e.id = a.object_entity_id
   WHERE a.user_id = $1 AND a.predicate IN ('has_expertise_in', 'has_skill')
     AND a.valid_until IS NULL AND e.embedding IS NOT NULL
)
SELECT DISTINCT f.eid
  FROM frustrations f, expertise x
 WHERE f.peak IS NOT NULL AND (f.peak - f.cur) > $2
   AND x.base IS NOT NULL AND (x.cur - x.base) > $3
   AND (1 - (f.embedding <=> x.embedding)) >= $4
"""


async def _emit(conn: asyncpg.Connection, user_id: str, eid: str) -> int:
    exists = await conn.fetchval(
        """SELECT 1 FROM assertions WHERE user_id = $1 AND predicate = 'is_resolved'
             AND object_entity_id = $2 AND valid_until IS NULL""",
        user_id, eid)
    if exists:
        return 0
    await conn.execute(
        """INSERT INTO assertions
             (user_id, predicate, object_entity_id, confidence, source_system, source, decay_fn)
           VALUES ($1, 'is_resolved', $2, $3, 'system', 'system', $4)""",
        user_id, eid, RESOLVED_CONFIDENCE, decay_fn_for("is_resolved"))
    return 1


async def run_resolution_detector(pool: asyncpg.Pool) -> dict:
    """Scan every user with active frustrations and emit is_resolved where warranted."""
    users = await pool.fetch(
        "SELECT DISTINCT user_id FROM assertions WHERE predicate = 'is_frustrated_by' AND valid_until IS NULL")
    emitted = 0
    for u in users:
        user_id = str(u["user_id"])
        eids = await pool.fetch(_PAIR_SQL, user_id, DROP_THRESHOLD, RISE_THRESHOLD, DOMAIN_SIMILARITY)
        async with pool.acquire() as conn:
            async with conn.transaction():
                for row in eids:
                    emitted += await _emit(conn, user_id, str(row["eid"]))
    return {"users_scanned": len(users), "resolutions_emitted": emitted}
