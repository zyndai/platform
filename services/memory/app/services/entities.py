from collections.abc import Sequence

import asyncpg

from app.db import to_pgvector
from app.services.embeddings import embed

# Brief §5.3 entity-resolution thresholds (cosine similarity).
MERGE_THRESHOLD = 0.92       # >= this -> same entity, merge + record alias
AMBIGUOUS_THRESHOLD = 0.75   # 0.75-0.92 -> ambiguous; create new, flag for review (future)


async def resolve_entity(
    conn: asyncpg.Connection,
    user_id: str,
    canonical_name: str,
    entity_type: str,
    *,
    type_group: Sequence[str] | None = None,
    surface_form: str | None = None,
) -> str:
    """Return the entity id for a name, merging onto an existing node when the
    name is semantically the same thing (brief §5.3, milestone M3).

    1. Exact canonical_name match -> reuse (cheap, skips an embedding call on
       identical restatements).
    2. Else embed the name and find the nearest existing entity of the same type:
         - cosine similarity >= 0.92 -> merge; record the new surface form as an alias.
         - similarity in [0.75, 0.92) -> ambiguous; create new (review tooling is future).
         - similarity < 0.75         -> clearly new; create new.

    Entities are always user-scoped — no global entity table (§14.5). Resolution
    is scoped to the same entity_type so a skill "Rust" never merges with a
    concept "Rust".

    `type_group` widens that scope to types that name the same kind of thing
    (taxonomy.ENTITY_TYPE_GROUPS: skill_technical / skill_domain / concept_topic for a
    technology). Inside a group the exact match is case-insensitive and also checks recorded
    aliases, so "javascript" finds the "JavaScript" entity whatever type it was stored under.
    `surface_form` is the name as the caller wrote it; when it differs it is kept as an alias.
    """
    types = list(type_group) if type_group else [entity_type]
    if type_group:
        exact = await conn.fetchrow(
            """SELECT id, canonical_name, aliases FROM entities
                WHERE user_id = $1 AND entity_type = ANY($2::text[])
                  AND (lower(canonical_name) = lower($3)
                       OR EXISTS (SELECT 1 FROM unnest(aliases) a WHERE lower(a) = lower($3)))
                ORDER BY (entity_type = $4) DESC, (lower(canonical_name) = lower($3)) DESC, created_at
                LIMIT 1""",
            user_id, types, canonical_name, entity_type,
        )
    else:
        exact = await conn.fetchrow(
            "SELECT id, canonical_name, aliases FROM entities WHERE user_id = $1 AND entity_type = $2 AND canonical_name = $3",
            user_id, entity_type, canonical_name,
        )
    if exact is not None:
        await _remember_surface(conn, exact, surface_form)
        return str(exact["id"])

    vector = to_pgvector(await embed(canonical_name))
    nearest = await conn.fetchrow(
        """SELECT id, canonical_name, aliases,
                  1 - (embedding <=> $1::vector) AS similarity
             FROM entities
            WHERE user_id = $2 AND entity_type = ANY($3::text[]) AND embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT 1""",
        vector, user_id, types,
    )

    if nearest is not None and nearest["similarity"] >= MERGE_THRESHOLD:
        entity_id = str(nearest["id"])
        existing_aliases = nearest["aliases"] or []
        if canonical_name not in existing_aliases:
            await conn.execute(
                "UPDATE entities SET aliases = array_append(aliases, $1), updated_at = now() WHERE id = $2",
                canonical_name, entity_id,
            )
        return entity_id

    created = await conn.fetchrow(
        """INSERT INTO entities (user_id, canonical_name, entity_type, embedding)
           VALUES ($1, $2, $3, $4::vector)
           RETURNING id""",
        user_id, canonical_name, entity_type, vector,
    )
    return str(created["id"])


async def _remember_surface(conn: asyncpg.Connection, entity, surface_form: str | None) -> None:
    """Record how the caller spelled a name that resolved to an existing entity."""
    surface = (surface_form or "").strip()
    if not surface or surface.lower() == entity["canonical_name"].lower():
        return
    if surface.lower() in {a.lower() for a in (entity["aliases"] or [])}:
        return
    await conn.execute(
        "UPDATE entities SET aliases = array_append(aliases, $1), updated_at = now() WHERE id = $2",
        surface, entity["id"],
    )
