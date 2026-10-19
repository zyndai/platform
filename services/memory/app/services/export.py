"""M6 — portable export (JSON-LD) + topic-relevant context slicing (brief §11)."""
import hashlib
import hmac
import json
from datetime import datetime, timezone

import asyncpg

from app.config import settings
from app.db import to_pgvector
from app.services.canonical import dedupe_key, tech_kind
from app.services.embeddings import embed
from app.services.quality import visible_sql
from app.taxonomy import (
    CORE_LIMITS,
    CORE_PREDICATES,
    CORE_MAX_SHARE,
    DEFAULT_PREDICATE_WEIGHT,
    FAMILY_RANK,
    PREDICATE_HALFLIFE_DAYS,
    PREDICATE_WEIGHT,
    RELATED_MIN,
    STALE_AFTER_DAYS,
    TECH_NAME_PREDICATES,
    family_of,
    humanize,
)

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


async def _legacy_active_context(pool: asyncpg.Pool, user_id: str, k: int = 20) -> list[dict]:
    """Top-K active facts by confidence, no topic filter — answers 'what do you know
    about me?'. The topic-less counterpart of context_slice (used by MCP get_my_context
    when no topic is supplied)."""
    rows = await pool.fetch(
        f"""SELECT DISTINCT ON (a.predicate, e.canonical_name)
                  a.predicate, e.canonical_name AS object, e.entity_type AS object_type,
                  a.confidence, a.observed_at
             FROM assertions a
             LEFT JOIN entities e ON e.id = a.object_entity_id
            WHERE a.user_id = $1 AND a.valid_until IS NULL AND {visible_sql("a")}
            ORDER BY a.predicate, e.canonical_name, a.confidence DESC
            LIMIT $2""",
        user_id, k,
    )
    return [
        {
            "statement": humanize(r["predicate"], r["object"]),
            "predicate": r["predicate"],
            "object": r["object"],
            "object_type": r["object_type"],
            "confidence": round(float(r["confidence"]), 4),
            "observed_at": r["observed_at"].isoformat() if r["observed_at"] else None,
        }
        for r in rows
    ]


async def _legacy_context_slice(pool: asyncpg.Pool, user_id: str, topic: str, k: int = 20) -> list[dict]:
    """Top-K assertions most relevant to `topic` (brief §11.2).

    Embeds the topic, then orders the user's active assertions by how close their
    object entity is to it. This is the MCP context packet — relevant slice, not
    the whole graph.
    """
    topic_vector = to_pgvector(await embed(topic))
    rows = await pool.fetch(
        f"""SELECT DISTINCT ON (a.predicate, e.canonical_name)
                  a.predicate, e.canonical_name AS object, e.entity_type AS object_type,
                  a.confidence, a.observed_at,
                  1 - (e.embedding <=> $2::vector) AS relevance
             FROM assertions a
             JOIN entities e ON e.id = a.object_entity_id
            WHERE a.user_id = $1 AND a.valid_until IS NULL AND {visible_sql("a")}
              AND a.confidence > $3 AND e.embedding IS NOT NULL
            ORDER BY a.predicate, e.canonical_name, e.embedding <=> $2::vector
            LIMIT $4""",
        user_id, topic_vector, CONTEXT_CONFIDENCE_FLOOR, k,
    )
    return [
        {
            "statement": humanize(r["predicate"], r["object"]),
            "predicate": r["predicate"],
            "object": r["object"],
            "object_type": r["object_type"],
            "confidence": round(float(r["confidence"]), 4),
            "relevance": round(float(r["relevance"]), 4),
            "observed_at": r["observed_at"].isoformat() if r["observed_at"] else None,
        }
        for r in rows
    ]


# ── Ranked context (docs/plans/ZYND_MEMORY_QUALITY_PLAN.md, Phase 1) ──────────────────
#
# What the person is doing *now*, plus older facts only when they relate to the question.
# The legacy queries above ordered by predicate name before applying LIMIT, so "top K"
# was the first K facts alphabetically and the topic barely mattered.

STALE_FRESHNESS_FLOOR = 0.3   # an old fact that matches the topic is still worth showing
CANDIDATE_LIMIT = 400         # rows handed to the Python scorer per request


async def active_context(pool: asyncpg.Pool, user_id: str, k: int = 20) -> list[dict]:
    """What the person is up to now: core facts plus fresh ones, no topic."""
    if settings.feature_ranked_context:
        return await rank_context(pool, user_id, topic=None, k=k)
    return await _legacy_active_context(pool, user_id, k)


async def context_slice(pool: asyncpg.Pool, user_id: str, topic: str, k: int = 20) -> list[dict]:
    """Facts related to `topic`, including older ones that match."""
    if settings.feature_ranked_context:
        return await rank_context(pool, user_id, topic=topic, k=k)
    return await _legacy_context_slice(pool, user_id, topic, k)


def days_since(ts: datetime | None, now: datetime) -> float:
    if ts is None:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (now - ts).total_seconds() / 86400.0)


def freshness(predicate: str, days: float) -> float:
    """1.0 for a fact seen today, halving every half-life. 1.0 for no-decay predicates."""
    halflife = PREDICATE_HALFLIFE_DAYS.get(predicate)
    if halflife is None:
        return 1.0
    return 0.5 ** (days / halflife)


def is_stale(predicate: str, days: float) -> bool:
    limit = STALE_AFTER_DAYS.get(predicate)
    return limit is not None and days > limit


def _group_key(row: dict) -> tuple[str, str]:
    """Identity of "the same thing" across predicates: family + canonical name."""
    predicate = row["predicate"]
    name = (row.get("object") or "").strip()
    tech = predicate in TECH_NAME_PREDICATES
    family = family_of(
        predicate,
        is_tech=tech and tech_kind(name) is not None,
        is_project=(row.get("object_type") or "").startswith("project_"),
    )
    key = dedupe_key(name) if tech else name.lower()
    return (family or predicate, key)


def collapse_families(rows: list[dict]) -> list[dict]:
    """One row per real-world thing: the strongest predicate of its family, with the
    most recent sighting of any member (a weaker, fresher report keeps the stronger
    fact alive) and the best topic relevance."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault(_group_key(row), []).append(row)
    out: list[dict] = []
    for members in groups.values():
        best = max(members, key=lambda r: (FAMILY_RANK.get(r["predicate"], 0), r["confidence"]))
        merged = dict(best)
        seen = [m["seen_at"] for m in members if m.get("seen_at") is not None]
        merged["seen_at"] = max(seen) if seen else None
        rels = [m["relevance"] for m in members if m.get("relevance") is not None]
        merged["relevance"] = max(rels) if rels else None
        out.append(merged)
    return out


def _weight(predicate: str) -> float:
    return PREDICATE_WEIGHT.get(predicate, DEFAULT_PREDICATE_WEIGHT)


def _pick_core(ranked: list[dict], k: int) -> list[dict]:
    """Core facts (where they are, who for, what they build, what they're expert in),
    capped to a share of k so they never crowd out what's current."""
    cap = max(1, int(k * CORE_MAX_SHARE))
    picked: list[dict] = []
    for predicate, limit in CORE_LIMITS:
        picked.extend([r for r in ranked if r["predicate"] == predicate][:limit])
    picked.sort(key=lambda r: r["score"], reverse=True)
    return picked[:cap]


def rank_rows(rows: list[dict], *, topic: bool, k: int, now: datetime) -> list[dict]:
    """Score, dedupe and select candidate facts. Pure: the DB layer fetches `rows`.

    Each row needs predicate, object, object_type, confidence, observed_at, seen_at and,
    for topic ranking, relevance. Returns at most k facts with `section`, `stale` and
    `last_seen_at` added; existing keys are unchanged so old clients keep working.
    """
    facts = collapse_families(rows)
    scored: list[dict] = []
    for row in facts:
        days = days_since(row.get("seen_at"), now)
        row["stale"] = is_stale(row["predicate"], days)
        fresh = freshness(row["predicate"], days)
        if topic:
            relevance = row.get("relevance")
            if relevance is None or relevance < RELATED_MIN:
                continue
            row["score"] = (relevance ** 2) * row["confidence"] * max(fresh, STALE_FRESHNESS_FLOOR)
        else:
            if row["stale"]:
                continue
            row["score"] = row["confidence"] * fresh * _weight(row["predicate"])
        scored.append(row)
    scored.sort(key=lambda r: r["score"], reverse=True)

    if topic:
        selected = scored[:k]
        for row in selected:
            row["section"] = "related" if row["stale"] else (
                "core" if row["predicate"] in CORE_PREDICATES else "now")
    else:
        core = _pick_core(scored, k)
        core_ids = {id(r) for r in core}
        rest = [r for r in scored if id(r) not in core_ids][: max(0, k - len(core))]
        for row in core:
            row["section"] = "core"
        for row in rest:
            row["section"] = "now"
        selected = core + rest
    return [_shape(r, topic=topic) for r in selected]


def _shape(row: dict, *, topic: bool) -> dict:
    seen = row.get("seen_at")
    observed = row.get("observed_at")
    fact = {
        "statement": humanize(row["predicate"], row.get("object")),
        "predicate": row["predicate"],
        "object": row.get("object"),
        "object_type": row.get("object_type"),
        "confidence": round(float(row["confidence"]), 4),
        "observed_at": observed.isoformat() if observed else None,
        "last_seen_at": seen.isoformat() if seen else None,
        "section": row["section"],
        "stale": bool(row["stale"]),
    }
    if topic:
        fact["relevance"] = round(float(row["relevance"]), 4)
    return fact


async def rank_context(
    pool: asyncpg.Pool,
    user_id: str,
    *,
    topic: str | None,
    k: int = 20,
    now: datetime | None = None,
) -> list[dict]:
    """Ranked, de-duplicated, freshness-aware context.

    No topic: core facts plus the current ones, nothing stale.
    With a topic: facts whose object is related to it, older ones included and marked.
    """
    k = max(1, min(int(k), 50))
    now = now or datetime.now(timezone.utc)
    topic = (topic or "").strip()
    seen_expr = (
        "coalesce(a.last_seen_at, a.observed_at, a.extracted_at)"
        if settings.feature_freshness_v2
        else "coalesce(a.observed_at, a.extracted_at)"
    )
    conf_expr = "coalesce(a.base_confidence, a.confidence)" if settings.feature_freshness_v2 else "a.confidence"
    select = f"""SELECT a.predicate, coalesce(e.canonical_name, a.object_literal) AS object,
                        e.entity_type AS object_type, {conf_expr} AS confidence,
                        a.observed_at, {seen_expr} AS seen_at"""
    where = f"""FROM assertions a
                LEFT JOIN entities e ON e.id = a.object_entity_id
               WHERE a.user_id = $1 AND a.valid_until IS NULL AND a.dismissed_at IS NULL
                 AND {conf_expr} > $2 AND {visible_sql("a")}"""
    if topic:
        vector = to_pgvector(await embed(topic))
        records = await pool.fetch(
            f"""{select}, 1 - (e.embedding <=> $4::vector) AS relevance
                {where} AND e.embedding IS NOT NULL
                ORDER BY e.embedding <=> $4::vector
                LIMIT $3""",
            user_id, CONTEXT_CONFIDENCE_FLOOR, CANDIDATE_LIMIT, vector,
        )
    else:
        records = await pool.fetch(
            f"""{select}, NULL::float AS relevance
                {where}
                ORDER BY {conf_expr} DESC
                LIMIT $3""",
            user_id, CONTEXT_CONFIDENCE_FLOOR, CANDIDATE_LIMIT,
        )
    rows = [
        {
            "predicate": r["predicate"],
            "object": r["object"],
            "object_type": r["object_type"],
            "confidence": float(r["confidence"]),
            "observed_at": r["observed_at"],
            "seen_at": r["seen_at"],
            "relevance": float(r["relevance"]) if r["relevance"] is not None else None,
        }
        for r in records
    ]
    return rank_rows(rows, topic=bool(topic), k=k, now=now)
