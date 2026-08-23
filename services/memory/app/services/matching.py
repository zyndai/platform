"""M5 matching: build per-cluster user vectors, then find nearest users.

Recompute (brief §10.2): for each cluster_type, take the user's active
assertion -> entity embeddings (confidence > 0.3, top 50 by confidence) and
average them weighted by confidence. Store one vector per (user, cluster).

Match (brief §6.1): cosine ANN over user_embeddings — the HNSW index makes this
a single vector scan. Decayed/archived assertions are excluded upstream, so a
match reflects what each user is about *now*.
"""
import json

import asyncpg

from app.config import settings
from app.db import from_pgvector, to_pgvector
from app.services.embeddings import embed
from app.taxonomy import CLUSTER_PREDICATES

# Social links surfaced with a match (from the person's persona profile) so the caller
# can reach out. Non-URL/empty values are dropped.
_SOCIAL_KEYS = ("linkedin", "twitter", "github", "website", "instagram", "telegram")
_SOCIAL_LABELS = {
    "linkedin": "LinkedIn", "twitter": "Twitter/X", "github": "GitHub",
    "website": "Website", "instagram": "Instagram", "telegram": "Telegram",
}

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
        """SELECT ue.user_id, u.display_name, u.socials,
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
    results = await _results_with_socials(rows)
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
        """SELECT ue.user_id, u.display_name, u.socials,
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
    results = await _results_with_socials(rows)
    return await _enrich_and_dedup(pool, results)


def _match_label(display_name: str | None, user_id: str) -> str:
    """Human label shown for a matched user (human matching is the product, brief §6).
    SECURITY: legacy rows stored the raw email in display_name; strip to the local-part
    so the full address (a contact/spam vector) is never leaked. Real Google names pass
    through; unknown names fall back to an opaque handle."""
    if not display_name:
        return f"zynd-{user_id[:8]}"
    return display_name.split("@", 1)[0]


def _parse_socials(raw) -> dict:
    """Clean the stored users.socials jsonb (str or dict) to known non-empty links."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    if not isinstance(raw, dict):
        return {}
    return {k: str(raw[k]).strip() for k in _SOCIAL_KEYS if raw.get(k) and str(raw[k]).strip()}


async def _results_with_socials(rows: list[asyncpg.Record]) -> list[dict]:
    """Shape match rows + attach each person's stored social links (users.socials, kept
    in sync from the persona profile). Adds an optional `socials` object and a ready-to-
    print `contact` line so the agent can show LinkedIn / Telegram / etc. verbatim."""
    out: list[dict] = []
    for r in rows:
        item = {
            "user_id": str(r["user_id"]),
            "display_name": _match_label(r["display_name"], str(r["user_id"])),
            "similarity": round(float(r["similarity"]), 4),
            "assertion_count": r["assertion_count"],
        }
        links = _parse_socials(r["socials"])
        if links:
            item["socials"] = links
            item["contact"] = " · ".join(f"{_SOCIAL_LABELS[k]}: {v}" for k, v in links.items())
        out.append(item)
    return out


# ── name enrichment + identity dedup ─────────────────────────────────────────
#
# Pre-persona "ghost" rows: users created before the Supabase cutover carry
# users.id == the Supabase auth user id, with display_name/supabase_user_id NULL.
# They share an identity with a later persona-linked row (same Supabase user id),
# so a match can surface two rows for the same person — one named, one "zynd-<id>".
# Resolve names from persona_agents (Supabase) and collapse duplicate identities.

_supabase_client = None


def _supabase():
    """Lazy Supabase client (service key), or None when unavailable. Never raises."""
    global _supabase_client
    if _supabase_client is None:
        try:
            from supabase import create_client
            _supabase_client = create_client(settings.supabase_url, settings.supabase_service_key)
        except Exception:
            _supabase_client = False
    return _supabase_client if _supabase_client is not False else None


def _persona_names(user_ids: list[str]) -> dict[str, str]:
    """Map Supabase user_id -> persona display name (agent_handle preferred)."""
    user_ids = [u for u in dict.fromkeys(user_ids) if u]
    if not user_ids:
        return {}
    sb = _supabase()
    if sb is None:
        return {}
    out: dict[str, str] = {}
    for i in range(0, len(user_ids), 20):
        chunk = user_ids[i:i + 20]
        try:
            rows = sb.table("persona_agents").select("user_id,name,agent_handle").eq("active", True).in_("user_id", chunk).execute()
        except Exception:
            continue
        for r in (rows.data or []):
            uid = r.get("user_id")
            name = (r.get("agent_handle") or r.get("name") or "").strip()
            if uid and name:
                out[uid] = name
    return out


def _is_fallback(name: str | None) -> bool:
    return bool(name) and name.startswith("zynd-")


async def _enrich_and_dedup(pool: asyncpg.Pool, results: list[dict]) -> list[dict]:
    """Fill in display_name for anonymous matches and drop duplicate identities.

    Returns only named, findable people: ghost rows are enriched from persona_agents
    (via users.supabase_user_id, or users.id for pre-persona ghost rows where the id
    IS the Supabase user id), collapsed onto their persona-linked row, and any
    remaining unnamed rows (no persona anywhere) are dropped.
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
    names = _persona_names(keys)

    for r, key in zip(results, keys):
        name = names.get(key)
        if name and _is_fallback(r.get("display_name")):
            r["display_name"] = name

    # Dedup by identity key, keeping the richest row (socials > real name > similarity).
    def _rank(r: dict) -> tuple:
        return (
            1 if r.get("socials") else 0,
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
