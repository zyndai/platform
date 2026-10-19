"""Seed helpers for service-level integration tests (use with the `pg` fixture)."""
import uuid

from app.db import to_pgvector
from app.services.embeddings import embed
from app.taxonomy import decay_fn_for


async def make_user(pool, email: str | None = None) -> str:
    email = email or f"u-{uuid.uuid4().hex[:10]}@test.local"
    return str(await pool.fetchval(
        "INSERT INTO users (email, display_name) VALUES ($1, $2) RETURNING id", email, email.split("@")[0]))


async def seed_fact(
    pool,
    user_id: str,
    predicate: str,
    name: str,
    etype: str = "skill_technical",
    *,
    confidence: float = 0.9,
    days_ago: float = 0,
    source: str = "inferred",
    source_system: str = "claude",
    is_public: bool = False,
    approved: bool = False,
    dismissed: bool = False,
    archived: bool = False,
    version: int = 1,
) -> str:
    """Insert one entity + one active assertion `days_ago` days old. Returns the assertion id."""
    entity_id = await pool.fetchval(
        """INSERT INTO entities (user_id, canonical_name, entity_type, embedding)
           VALUES ($1, $2, $3, $4::vector) RETURNING id""",
        user_id, name, etype, to_pgvector(await embed(name)))
    return str(await pool.fetchval(
        """INSERT INTO assertions
             (user_id, predicate, object_entity_id, confidence, source_system, source,
              decay_fn, observed_at, is_public, approved_at, dismissed_at, valid_until, version)
           VALUES ($1,$2,$3,$4,$5,$6,$7, now() - ($8 * interval '1 day'), $9,
                   CASE WHEN $10 THEN now() END,
                   CASE WHEN $11 THEN now() END,
                   CASE WHEN $12 THEN now() END, $13)
           RETURNING id""",
        user_id, predicate, entity_id, confidence, source_system, source,
        decay_fn_for(predicate), days_ago, is_public or approved, approved, dismissed, archived,
        version))
