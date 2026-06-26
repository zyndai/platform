"""M6 — portable export (JSON-LD) + topic-relevant context slicing (brief §11)."""
import hashlib
import hmac
import json
from datetime import datetime, timezone

import asyncpg

from app.config import settings
from app.db import to_pgvector
from app.services.embeddings import embed

EXPORT_CONFIDENCE_FLOOR = 0.0   # full active graph in the portable export
CONTEXT_CONFIDENCE_FLOOR = 0.4  # brief §11.2 — only reasonably-held beliefs in a slice


async def build_jsonld_export(pool: asyncpg.Pool, user_id: str) -> dict:
    """The user's full active context as a JSON-LD packet (brief §11.1).

    Portable: any MCP-compatible system can read it via the @context vocabulary.
    """
    rows = await pool.fetch(
        """SELECT a.predicate, e.canonical_name AS object, e.entity_type AS object_type,
                  a.confidence, a.observed_at
             FROM assertions a
             JOIN entities e ON e.id = a.object_entity_id
            WHERE a.user_id = $1 AND a.valid_until IS NULL AND a.confidence > $2
            ORDER BY a.confidence DESC""",
        user_id, EXPORT_CONFIDENCE_FLOOR,
    )
    assertions = [
        {
            "predicate": r["predicate"],
            "object": r["object"],
            "object_type": r["object_type"],
            "confidence": round(float(r["confidence"]), 4),
            "observed_at": r["observed_at"].isoformat() if r["observed_at"] else None,
        }
        for r in rows
    ]
    return {
        "@context": "https://zynd.io/schema/v1",
        "@type": "UserContext",
        "user_id": str(user_id),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "signature": _sign(assertions),
        "assertions": assertions,
    }


def _sign(assertions: list[dict]) -> str:
    """Tamper-evidence over the payload. NOTE: server-side HMAC integrity, NOT the
    user-private-key signature the brief envisions (§11.1) — swap when users hold keys."""
    payload = json.dumps(assertions, sort_keys=True, separators=(",", ":"))
    return hmac.new(settings.jwt_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


async def active_context(pool: asyncpg.Pool, user_id: str, k: int = 20) -> list[dict]:
    """Top-K active facts by confidence, no topic filter — answers 'what do you know
    about me?'. The topic-less counterpart of context_slice (used by MCP get_my_context
    when no topic is supplied)."""
    rows = await pool.fetch(
        """SELECT a.predicate, e.canonical_name AS object, e.entity_type AS object_type,
                  a.confidence, a.observed_at
             FROM assertions a
             LEFT JOIN entities e ON e.id = a.object_entity_id
            WHERE a.user_id = $1 AND a.valid_until IS NULL
            ORDER BY a.confidence DESC
            LIMIT $2""",
        user_id, k,
    )
    return [
        {
            "predicate": r["predicate"],
            "object": r["object"],
            "object_type": r["object_type"],
            "confidence": round(float(r["confidence"]), 4),
            "observed_at": r["observed_at"].isoformat() if r["observed_at"] else None,
        }
        for r in rows
    ]


async def context_slice(pool: asyncpg.Pool, user_id: str, topic: str, k: int = 20) -> list[dict]:
    """Top-K assertions most relevant to `topic` (brief §11.2).

    Embeds the topic, then orders the user's active assertions by how close their
    object entity is to it. This is the MCP context packet — relevant slice, not
    the whole graph.
    """
    topic_vector = to_pgvector(await embed(topic))
    rows = await pool.fetch(
        """SELECT a.predicate, e.canonical_name AS object, e.entity_type AS object_type,
                  a.confidence, a.observed_at,
                  1 - (e.embedding <=> $2::vector) AS relevance
             FROM assertions a
             JOIN entities e ON e.id = a.object_entity_id
            WHERE a.user_id = $1 AND a.valid_until IS NULL
              AND a.confidence > $3 AND e.embedding IS NOT NULL
            ORDER BY e.embedding <=> $2::vector
            LIMIT $4""",
        user_id, topic_vector, CONTEXT_CONFIDENCE_FLOOR, k,
    )
    return [
        {
            "predicate": r["predicate"],
            "object": r["object"],
            "object_type": r["object_type"],
            "confidence": round(float(r["confidence"]), 4),
            "relevance": round(float(r["relevance"]), 4),
            "observed_at": r["observed_at"].isoformat() if r["observed_at"] else None,
        }
        for r in rows
    ]
