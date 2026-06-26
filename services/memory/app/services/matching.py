"""M5 matching: build per-cluster user vectors, then find nearest users.

Recompute (brief §10.2): for each cluster_type, take the user's active
assertion -> entity embeddings (confidence > 0.3, top 50 by confidence) and
average them weighted by confidence. Store one vector per (user, cluster).

Match (brief §6.1): cosine ANN over user_embeddings — the HNSW index makes this
a single vector scan. Decayed/archived assertions are excluded upstream, so a
match reflects what each user is about *now*.
"""
import asyncpg

from app.config import settings
from app.db import from_pgvector, to_pgvector
from app.taxonomy import CLUSTER_PREDICATES

CONFIDENCE_FLOOR = 0.3   # brief §10.2
MAX_ASSERTIONS_PER_CLUSTER = 50


def _weighted_average(rows: list[asyncpg.Record]) -> list[float]:
    """Confidence-weighted average of the embeddings in `rows`. Not normalized —
    pgvector's cosine distance normalizes internally at query time."""
    total_weight = sum(float(r["confidence"]) for r in rows)
    dim = len(from_pgvector(rows[0]["embedding"]))
    accumulator = [0.0] * dim
    for row in rows:
        embedding = from_pgvector(row["embedding"])
        weight = float(row["confidence"])
        for i in range(dim):
            accumulator[i] += embedding[i] * weight
    return [value / total_weight for value in accumulator]


async def recompute_user_embeddings(pool: asyncpg.Pool, user_id: str) -> dict:
    """Rebuild every cluster vector for one user. Returns {cluster_type: count}."""
    built: dict[str, int] = {}
    for cluster_type, predicates in CLUSTER_PREDICATES.items():
        rows = await pool.fetch(
            """SELECT e.embedding, a.confidence
                 FROM assertions a
                 JOIN entities e ON e.id = a.object_entity_id
                WHERE a.user_id = $1
                  AND a.predicate = ANY($2::text[])
                  AND a.confidence > $3
                  AND a.valid_until IS NULL
                  AND e.embedding IS NOT NULL
                ORDER BY a.confidence DESC
                LIMIT $4""",
            user_id, list(predicates), CONFIDENCE_FLOOR, MAX_ASSERTIONS_PER_CLUSTER,
        )
        if not rows:
            continue
        vector = to_pgvector(_weighted_average(rows))
        await pool.execute(
            """INSERT INTO user_embeddings (user_id, cluster_type, embedding, assertion_count, computed_at)
               VALUES ($1, $2, $3::vector, $4, now())
               ON CONFLICT (user_id, cluster_type)
               DO UPDATE SET embedding = EXCLUDED.embedding,
                             assertion_count = EXCLUDED.assertion_count,
                             computed_at = now()""",
            user_id, cluster_type, vector, len(rows),
        )
        built[cluster_type] = len(rows)
    return built


async def run_recompute_all(pool: asyncpg.Pool) -> dict:
    """Nightly: recompute embeddings for every user."""
    user_ids = [r["id"] for r in await pool.fetch("SELECT id FROM users")]
    for user_id in user_ids:
        await recompute_user_embeddings(pool, str(user_id))
    return {"users_recomputed": len(user_ids)}


async def match_users(
    pool: asyncpg.Pool,
    user_id: str,
    cluster_type: str,
    limit: int | None = None,
) -> list[dict]:
    """Top-N users most similar to `user_id` within `cluster_type` (brief §6.1)."""
    if cluster_type not in CLUSTER_PREDICATES:
        raise ValueError(f"unknown cluster_type: {cluster_type}")
    limit = limit or settings.match_default_limit

    self_vector = await pool.fetchval(
        "SELECT embedding FROM user_embeddings WHERE user_id = $1 AND cluster_type = $2",
        user_id, cluster_type,
    )
    if self_vector is None:
        return []  # this user has no vector for that cluster yet

    rows = await pool.fetch(
        """SELECT ue.user_id, u.display_name,
                  1 - (ue.embedding <=> $1::vector) AS similarity,
                  ue.assertion_count
             FROM user_embeddings ue
             JOIN users u ON u.id = ue.user_id
            WHERE ue.cluster_type = $2
              AND ue.user_id <> $3
              AND ue.assertion_count >= $4
            ORDER BY ue.embedding <=> $1::vector
            LIMIT $5""",
        self_vector, cluster_type, user_id, settings.match_min_assertions, limit,
    )
    return [
        {
            "user_id": str(r["user_id"]),
            "display_name": r["display_name"],
            "similarity": round(float(r["similarity"]), 4),
            "assertion_count": r["assertion_count"],
        }
        for r in rows
    ]
