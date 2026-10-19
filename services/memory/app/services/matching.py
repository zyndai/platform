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
from app.services import card_directory
from app.services.embeddings import embed
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
                  AND a.is_public = true
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
    # Legacy/removed cluster names (e.g. belief_cluster) fall back to the full
    # findability card rather than erroring — matching is findability-only now.
    if cluster_type not in CLUSTER_PREDICATES:
        cluster_type = "full_context"
    # Clamp: a non-positive limit falls back to the default; cap to 50 so a caller
    # can't push a negative/huge value into SQL LIMIT (DB error) or scrape the graph.
    limit = limit if (limit and limit > 0) else settings.match_default_limit
    limit = min(limit, 50)

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
    results = await _shape_results(rows)
    return await _enrich_and_dedup(pool, results)


async def search_by_query(
    pool: asyncpg.Pool,
    caller_id: str,
    query_text: str,
    cluster_type: str = "full_context",
    limit: int | None = None,
) -> list[dict]:
    """Complementary search (powers find_people): top-N PUBLIC users whose
    `cluster_type` vector is nearest to the embedded `query_text` — a described
    TARGET profile, NOT the caller's own vector. The agent translates a need
    (founder→investor, SaaS→distribution) into the target description; this just
    retrieves. Same public-only pool, min-assertion gate, and shape as match_users."""
    query_text = (query_text or "").strip()
    if not query_text:
        return []  # empty/whitespace target → no results (and avoids embed()'s ValueError)
    if cluster_type not in CLUSTER_PREDICATES:
        cluster_type = "full_context"
    limit = limit if (limit and limit > 0) else settings.match_default_limit
    limit = min(limit, 50)

    query_vector = to_pgvector(await embed(query_text))
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
        query_vector, cluster_type, caller_id, settings.match_min_assertions, limit,
    )
    results = await _shape_results(rows)
    return await _enrich_and_dedup(pool, results)


def _match_label(display_name: str | None, user_id: str) -> str:
    """Human label shown for a matched user (human matching is the product, brief §6).
    SECURITY: legacy rows stored the raw email in display_name; strip to the local-part
    so the full address (a contact/spam vector) is never leaked. Real Google names pass
    through; unknown names fall back to an opaque handle."""
    if not display_name:
        return f"zynd-{user_id[:8]}"
    return display_name.split("@", 1)[0]


async def _shape_results(rows: list[asyncpg.Record]) -> list[dict]:
    """Shape match rows. Contact details (LinkedIn, Telegram, X, ...) are deliberately NOT
    part of a match: someone who is merely findable has not agreed to be contacted that way.
    They are shared with the other side of an accepted Cards connection (see
    cards-api services/network.py), never in search."""
    return [
        {
            "user_id": str(r["user_id"]),
            "display_name": _match_label(r["display_name"], str(r["user_id"])),
            "similarity": round(float(r["similarity"]), 4),
            "assertion_count": r["assertion_count"],
        }
        for r in rows
    ]


# ── name enrichment + identity dedup ─────────────────────────────────────────
#
# Pre-persona "ghost" rows: users created before the Supabase cutover carry
# users.id == the Supabase auth user id, with display_name/supabase_user_id NULL.
# They share an identity with a later persona-linked row (same Supabase user id),
# so a match can surface two rows for the same person — one named, one "zynd-<id>".
# Names come from the person's Card (the persona product is paused), and duplicate
# identities collapse onto one row.


def _is_fallback(name: str | None) -> bool:
    return bool(name) and name.startswith("zynd-")


async def _card_names(pool: asyncpg.Pool, ids: list[str]) -> dict[str, str]:
    """Shared Zynd user id -> the name on their Card, for those that have one."""
    cards = await card_directory.cards_for_canonical(ids)
    return {
        uid: str(card.get("name") or "").strip()
        for uid, card in (cards or {}).items()
        if str(card.get("name") or "").strip()
    }


async def _enrich_and_dedup(pool: asyncpg.Pool, results: list[dict]) -> list[dict]:
    """Fill in display_name for anonymous matches and drop duplicate identities.

    Returns only named, findable people: ghost rows are named from their Card (via
    users.supabase_user_id, or users.id for pre-persona ghost rows where the id IS the
    Supabase user id), collapsed onto their linked row, and any remaining unnamed rows (no
    Card anywhere) are dropped.
    """
    if not results:
        return results

    ids = [r["user_id"] for r in results]
    try:
        rows = await pool.fetch("SELECT id, supabase_user_id FROM users WHERE id = ANY($1::uuid[])", ids)
    except Exception:
        return results
    suid_by_id = {str(r["id"]): r["supabase_user_id"] for r in rows}

    # Canonical identity key: supabase_user_id when set, else the row's own id
    # (pre-persona ghost rows have users.id == the Supabase user id).
    keys = [suid_by_id.get(r["user_id"]) or r["user_id"] for r in results]
    names = await _card_names(pool, [str(k) for k in keys])

    for r, key in zip(results, keys):
        name = names.get(str(key))
        if name and _is_fallback(r.get("display_name")):
            r["display_name"] = name

    # Dedup by identity key, keeping the best row (real name > similarity).
    def _rank(r: dict) -> tuple:
        return (
            0 if _is_fallback(r.get("display_name")) else 1,
            r.get("similarity") or 0.0,
        )

    best: dict[str, dict] = {}
    for r, key in zip(results, keys):
        if key not in best or _rank(r) > _rank(best[key]):
            best[key] = r

    out: list[dict] = []
    seen: set[str] = set()
    for r, key in zip(results, keys):
        if key in seen:
            continue
        seen.add(key)
        picked = best[key]
        if _is_fallback(picked.get("display_name")):
            continue  # no name anywhere — not findable
        out.append(picked)
    return out
