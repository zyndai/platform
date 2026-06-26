"""User-control over their own facts (brief §6): confirm and forget.

confirm → source=user_confirmed, confidence=0.97 (the doc's max).
forget  → soft-delete via valid_until (NEVER hard-delete — §14.1), logged.

Both re-derive the user's matching vectors afterward so /match stays consistent.
Facts are referenced by (predicate, object_name) — what the user/GPT actually
sees from getMyContext — matched case-insensitively, scoped to that user.
"""
import asyncpg

from app.services.matching import recompute_user_embeddings

_LOOKUP = """SELECT a.id, a.confidence
               FROM assertions a JOIN entities e ON e.id = a.object_entity_id
              WHERE a.user_id = $1 AND a.predicate = $2
                AND lower(e.canonical_name) = lower($3)
                AND a.valid_until IS NULL
              LIMIT 1"""


async def confirm_fact(pool: asyncpg.Pool, user_id: str, predicate: str, object_name: str) -> bool:
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(_LOOKUP, user_id, predicate, object_name)
            if row is None:
                return False
            await conn.execute(
                """UPDATE assertions
                      SET confidence = 0.97, source_system = 'user_confirmed', version = version + 1
                    WHERE id = $1""",
                row["id"],
            )
            await _log(conn, row["id"], float(row["confidence"]), 0.97, "user_confirmed")
    await recompute_user_embeddings(pool, user_id)
    return True


async def forget_fact(pool: asyncpg.Pool, user_id: str, predicate: str, object_name: str) -> bool:
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(_LOOKUP, user_id, predicate, object_name)
            if row is None:
                return False
            # Soft-delete: the row stays for audit; it just stops being active.
            await conn.execute("UPDATE assertions SET valid_until = now() WHERE id = $1", row["id"])
            await _log(conn, row["id"], float(row["confidence"]), float(row["confidence"]), "user_deleted")
    await recompute_user_embeddings(pool, user_id)
    return True


async def _log(conn, assertion_id, prev: float, new: float, reason: str) -> None:
    await conn.execute(
        """INSERT INTO assertion_history (assertion_id, prev_confidence, new_confidence, change_reason)
           VALUES ($1, $2, $3, $4)""",
        assertion_id, prev, new, reason,
    )
