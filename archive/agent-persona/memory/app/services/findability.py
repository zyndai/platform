"""v2 Findability Card — the user-approved, public subset used for matching/discovery.

Private memory (all predicates, automatic) is never matched. Nothing becomes matchable
until the user approves it here, or declares it explicitly. The card is the consent layer.
"""
import asyncpg

from app.services.entities import resolve_entity
from app.services.matching import recompute_user_embeddings
from app.taxonomy import FINDABILITY_PREDICATES, decay_fn_for

# Declarable predicates -> the entity family a declared value resolves to.
DECLARE_ENTITY_TYPE: dict[str, str] = {
    "is_building": "project_venture",
    "is_learning": "skill_domain",
    "has_expertise_in": "skill_domain",
    "is_seeking": "collaborator",
    "open_to": "collaborator",
    "is_affiliated_with": "place_institutional",
    "is_located_in": "place_physical",
}

# Multi-select predicates and their allowed values (v2 reference).
ENUM_VALUES: dict[str, frozenset[str]] = {
    "is_seeking": frozenset({"co_founder", "technical_feedback", "early_users", "mentoring",
                             "being_mentored", "peer_review", "collaboration", "investment", "community"}),
    "open_to": frozenset({"coffee_chat", "collaboration", "mentoring_others", "being_mentored",
                          "peer_review", "co_founder", "early_user_testing"}),
}

DECLARED_CONFIDENCE = 0.97  # user-declared facts carry the system's max confidence (doc cap)
_FINDABILITY = list(FINDABILITY_PREDICATES)

_LOOKUP = """SELECT a.id FROM assertions a JOIN entities e ON e.id = a.object_entity_id
              WHERE a.user_id = $1 AND a.predicate = $2
                AND lower(e.canonical_name) = lower($3) AND a.valid_until IS NULL
              LIMIT 1"""


async def get_card(pool: asyncpg.Pool, user_id: str) -> list[dict]:
    """The user's public findability card — what others can match against."""
    rows = await pool.fetch(
        """SELECT a.predicate, e.canonical_name AS object, a.source, a.confidence, a.approved_at
             FROM assertions a JOIN entities e ON e.id = a.object_entity_id
            WHERE a.user_id = $1 AND a.valid_until IS NULL AND a.is_public = true
              AND a.predicate = ANY($2::text[])
            ORDER BY a.predicate""",
        user_id, _FINDABILITY,
    )
    return [{"predicate": r["predicate"], "object": r["object"], "source": r["source"],
             "confidence": round(float(r["confidence"]), 4),
             "approved_at": r["approved_at"].isoformat() if r["approved_at"] else None}
            for r in rows]


async def get_suggestions(pool: asyncpg.Pool, user_id: str) -> list[dict]:
    """Inferred findability-eligible facts NOT yet public — "ZYND noticed this. Keep it?"."""
    rows = await pool.fetch(
        """SELECT a.predicate, e.canonical_name AS object, a.confidence
             FROM assertions a JOIN entities e ON e.id = a.object_entity_id
            WHERE a.user_id = $1 AND a.valid_until IS NULL AND a.is_public = false
              AND a.source <> 'declared' AND a.predicate = ANY($2::text[])
            ORDER BY a.confidence DESC""",
        user_id, _FINDABILITY,
    )
    return [{"predicate": r["predicate"], "object": r["object"],
             "confidence": round(float(r["confidence"]), 4)} for r in rows]


async def approve(pool: asyncpg.Pool, user_id: str, predicate: str, object_name: str) -> bool:
    """Publish an inferred fact onto the card. Only findability predicates are publishable."""
    if predicate not in FINDABILITY_PREDICATES:
        return False
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_LOOKUP, user_id, predicate, object_name)
        if row is None:
            return False
        await conn.execute(
            """UPDATE assertions SET is_public = true, approved_at = now(),
                  source = CASE WHEN source = 'inferred' THEN 'both' ELSE source END
                WHERE id = $1""",
            row["id"],
        )
    await recompute_user_embeddings(pool, user_id)  # rebuild the public match vector
    return True


async def revoke(pool: asyncpg.Pool, user_id: str, predicate: str, object_name: str) -> bool:
    """Take a fact off the card (back to private). The fact itself is kept in memory."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_LOOKUP, user_id, predicate, object_name)
        if row is None:
            return False
        await conn.execute(
            "UPDATE assertions SET is_public = false, approved_at = NULL WHERE id = $1", row["id"])
    await recompute_user_embeddings(pool, user_id)
    return True


async def declare(pool: asyncpg.Pool, user_id: str, predicate: str, value: str) -> None:
    """User explicitly adds a public findability fact. Raises ValueError on bad input."""
    if predicate not in DECLARE_ENTITY_TYPE:
        raise ValueError(f"{predicate!r} is not declarable")
    value = (value or "").strip()
    if not value:
        raise ValueError("value is required")
    allowed = ENUM_VALUES.get(predicate)
    if allowed is not None and value not in allowed:
        raise ValueError(f"{value!r} not allowed for {predicate}; choose one of {sorted(allowed)}")

    async with pool.acquire() as conn:
        async with conn.transaction():
            entity_id = await resolve_entity(conn, user_id, value, DECLARE_ENTITY_TYPE[predicate])
            existing = await conn.fetchrow(
                """SELECT id FROM assertions WHERE user_id = $1 AND predicate = $2
                     AND object_entity_id = $3 AND valid_until IS NULL LIMIT 1""",
                user_id, predicate, entity_id)
            if existing:  # already known privately -> just publish it as declared
                await conn.execute(
                    """UPDATE assertions SET is_public = true, approved_at = now(),
                          source = 'declared', confidence = $2 WHERE id = $1""",
                    existing["id"], DECLARED_CONFIDENCE)
            else:
                await conn.execute(
                    """INSERT INTO assertions
                         (user_id, predicate, object_entity_id, confidence, source_system,
                          source, is_public, approved_at, decay_fn)
                       VALUES ($1, $2, $3, $4, 'user_confirmed', 'declared', true, now(), $5)""",
                    user_id, predicate, entity_id, DECLARED_CONFIDENCE, decay_fn_for(predicate))
    await recompute_user_embeddings(pool, user_id)
