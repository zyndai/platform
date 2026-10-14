"""v2 Findability Card — the user-approved, public subset used for matching/discovery.

Private memory (all predicates, automatic) is never matched. Nothing becomes matchable
until the user approves it here, or declares it explicitly. The card is the consent layer.
"""
from __future__ import annotations

import asyncpg

from app.services.entities import resolve_entity
from app.services.matching import recompute_user_embeddings
from app.services.quality import (
    DEFAULT_DAILY_CAP,
    assess,
    dedupe_suggestion_rows,
    public_label_for,
    public_predicate_for,
)
from app.taxonomy import FINDABILITY_PREDICATES, PREDICATE_HALFLIFE_DAYS, decay_fn_for

# Declarable predicates -> the entity family a declared value resolves to.
DECLARE_ENTITY_TYPE: dict[str, str] = {
    "is_building": "project_venture",
    "is_working_on": "project_venture",
    "is_learning": "skill_domain",
    "has_expertise_in": "skill_domain",
    "uses_tool": "skill_technical",
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

# Private-memory declarable predicates -> entity family. Literal/enum predicates
# (has_age, is_seeking, open_to) are intentionally excluded — they need literal
# storage, not entity resolution.
PRIVATE_DECLARE_ENTITY_TYPE: dict[str, str] = {
    "is_building": "project_venture",
    "is_working_on": "project_venture",
    "is_creating": "artifact_creative",
    "wants_to_preserve": "concept_topic",
    "is_learning": "skill_domain",
    "has_expertise_in": "skill_domain",
    "has_skill": "skill_technical",
    "uses_tool": "skill_technical",
    "intends_to": "intent_project",
    "is_preparing_for": "intent_project",
    "fears": "concept_topic",
    "believes": "belief_opinion",
    "values": "belief_value",
    "recently_changed_stance_on": "belief_opinion",
    "has_aesthetic": "belief_opinion",
    "is_navigating": "concept_topic",
    "is_constrained_by": "concept_topic",
    "is_frustrated_by": "concept_topic",
    "has_been_wronged": "concept_topic",
    "is_transitioning": "concept_topic",
    "is_experiencing": "concept_topic",
    "is_processing": "concept_topic",
    "is_rediscovering": "concept_topic",
    "has_unsolved_problem": "concept_topic",
    "has_collaborator": "collaborator",
    "is_responsible_for": "project_assignment",
    "is_advocating_for": "concept_topic",
    "is_in_conflict_with": "adversary",
    "is_inspired_by": "influence",
    "is_located_in": "place_physical",
    "is_affiliated_with": "place_institutional",
    "has_language_context": "concept_topic",
    "is_motivated_by": "concept_topic",
}

PRIVATE_DECLARED_CONFIDENCE = 0.97
CARDS_MCP_SOURCE = "cards_mcp"

_FINDABILITY = list(FINDABILITY_PREDICATES)

_LOOKUP = """SELECT a.id FROM assertions a JOIN entities e ON e.id = a.object_entity_id
              WHERE a.user_id = $1 AND a.predicate = $2
                AND lower(e.canonical_name) = lower($3) AND a.valid_until IS NULL
              LIMIT 1"""


async def get_card(pool: asyncpg.Pool, user_id: str) -> list[dict]:
    """The user's public findability card — what others can match against."""
    rows = await pool.fetch(
        """SELECT a.predicate, e.canonical_name AS object, a.source, a.confidence,
                  a.approved_at, a.observed_at
             FROM assertions a JOIN entities e ON e.id = a.object_entity_id
            WHERE a.user_id = $1 AND a.valid_until IS NULL AND a.is_public = true
              AND a.predicate = ANY($2::text[])
            ORDER BY a.predicate""",
        user_id, _FINDABILITY,
    )
    card = []
    for r in rows:
        pred = r["predicate"]
        card.append({
            "predicate": pred,
            "object": r["object"],
            "source": r["source"],
            "confidence": round(float(r["confidence"]), 4),
            "approved_at": r["approved_at"].isoformat() if r["approved_at"] else None,
            "observed_at": r["observed_at"].isoformat() if r["observed_at"] else None,
            "half_life_days": PREDICATE_HALFLIFE_DAYS.get(pred),
        })
    return dedupe_suggestion_rows(card)


# Predicates coding agents commonly produce that should surface for review.
# Broader than FINDABILITY_PREDICATES — approve() maps these onto a public
# findability predicate before publishing.
_REVIEW_PREDICATES = list(FINDABILITY_PREDICATES | frozenset({
    "has_skill", "is_working_on", "is_creating", "intends_to",
    "is_responsible_for",
}))

# Map review predicates onto the public findability card vocabulary.
# (has_collaborator is intentionally omitted — open_to/is_seeking are enums.)
_APPROVE_AS: dict[str, str] = {
    "has_skill": "has_expertise_in",
    "is_creating": "is_building",
    "intends_to": "is_building",
    "is_responsible_for": "is_building",
}


def _enrich_suggestion(predicate: str, object_name: str, confidence: float) -> dict:
    quality = assess(object_name, intended_predicate=predicate)
    suggested = quality.suggested_predicate or predicate
    public_pred = public_predicate_for(suggested)
    return {
        "predicate": predicate,
        "object": quality.value or object_name,
        "confidence": round(float(confidence), 4),
        "group": quality.group,
        "suggested_predicate": suggested,
        "public_label": quality.public_label or public_label_for(public_pred, object_name),
    }


async def get_suggestions(pool: asyncpg.Pool, user_id: str) -> list[dict]:
    """Private facts awaiting review — inferred or cards_mcp typed declarations.

    Excludes permanently dismissed rows. Attaches triage group / Shows-as label.
    """
    rows = await pool.fetch(
        """SELECT a.predicate, e.canonical_name AS object, a.confidence
             FROM assertions a JOIN entities e ON e.id = a.object_entity_id
            WHERE a.user_id = $1 AND a.valid_until IS NULL AND a.is_public = false
              AND a.dismissed_at IS NULL
              AND a.predicate = ANY($2::text[])
              AND (
                    a.source <> 'declared'
                 OR (a.source = 'declared' AND a.source_system = $3)
              )
            ORDER BY a.confidence DESC""",
        user_id, _REVIEW_PREDICATES, CARDS_MCP_SOURCE,
    )
    enriched = [
        _enrich_suggestion(r["predicate"], r["object"], float(r["confidence"]))
        for r in rows
    ]
    # Prefer right > look > noise when collapsing duplicates.
    order = {"right": 0, "look": 1, "noise": 2}
    enriched.sort(key=lambda r: (order.get(r["group"], 9), -r["confidence"]))
    return dedupe_suggestion_rows(enriched)


async def approve(
    pool: asyncpg.Pool,
    user_id: str,
    predicate: str,
    object_name: str,
    *,
    as_predicate: str | None = None,
) -> dict | None:
    """Publish an inferred/typed fact onto the card.

    Findability predicates publish in place. Coding-agent predicates
    (has_skill, is_working_on, …) are promoted to their findability equivalent
    via declare() so they appear on the public card. Optional as_predicate
    overrides the default _APPROVE_AS remap.
    """
    object_name = (object_name or "").strip()
    if not object_name:
        return None

    if predicate in FINDABILITY_PREDICATES and not as_predicate:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(_LOOKUP, user_id, predicate, object_name)
            if row is None:
                return None
            await conn.execute(
                """UPDATE assertions SET is_public = true, approved_at = now(),
                      dismissed_at = NULL,
                      source = CASE WHEN source = 'inferred' THEN 'both' ELSE source END
                    WHERE id = $1""",
                row["id"],
            )
        await recompute_user_embeddings(pool, user_id)
        public_pred = predicate
        label = public_label_for(public_pred, object_name)
        return {
            "status": "approved",
            "predicate": public_pred,
            "value": object_name,
            "public_label": label,
        }

    public_pred = (as_predicate or "").strip() or _APPROVE_AS.get(predicate)
    if not public_pred or public_pred not in DECLARE_ENTITY_TYPE:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_LOOKUP, user_id, predicate, object_name)
        if row is None:
            return None
        # Soft-clear the private suggestion so it leaves the review queue.
        # Drop cards_mcp source_system so typed declarations are no longer
        # re-included by get_suggestions after publish.
        await conn.execute(
            """UPDATE assertions SET source = 'declared',
                  source_system = 'user_confirmed',
                  version = version + 1
                WHERE id = $1""",
            row["id"],
        )
    await declare(pool, user_id, public_pred, object_name)
    label = public_label_for(public_pred, object_name)
    return {
        "status": "approved",
        "predicate": public_pred,
        "value": object_name,
        "public_label": label,
    }


async def dismiss(pool: asyncpg.Pool, user_id: str, predicate: str, object_name: str) -> bool:
    """Permanently hide a private fact from the review inbox (keeps memory)."""
    object_name = (object_name or "").strip()
    if not object_name:
        return False
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_LOOKUP, user_id, predicate, object_name)
        if row is None:
            return False
        await conn.execute(
            """UPDATE assertions SET dismissed_at = COALESCE(dismissed_at, now()),
                  version = version + 1
                WHERE id = $1""",
            row["id"],
        )
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
                          dismissed_at = NULL,
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


async def declare_private(pool: asyncpg.Pool, user_id: str, predicate: str, value: str) -> None:
    """User explicitly adds a PRIVATE memory fact (never matched/public)."""
    if predicate not in PRIVATE_DECLARE_ENTITY_TYPE:
        raise ValueError(f"{predicate!r} is not declarable as private memory")
    value = (value or "").strip()
    if not value:
        raise ValueError("value is required")

    entity_type = PRIVATE_DECLARE_ENTITY_TYPE[predicate]
    async with pool.acquire() as conn:
        async with conn.transaction():
            entity_id = await resolve_entity(conn, user_id, value, entity_type)
            existing = await conn.fetchrow(
                """SELECT id FROM assertions WHERE user_id = $1 AND predicate = $2
                     AND object_entity_id = $3 AND valid_until IS NULL LIMIT 1""",
                user_id, predicate, entity_id)
            if existing:
                await conn.execute(
                    """UPDATE assertions SET source = 'declared',
                          confidence = $2, version = version + 1 WHERE id = $1""",
                    existing["id"], PRIVATE_DECLARED_CONFIDENCE)
            else:
                await conn.execute(
                    """INSERT INTO assertions
                         (user_id, predicate, object_entity_id, confidence, source_system,
                          source, is_public, decay_fn)
                       VALUES ($1, $2, $3, $4, 'user_confirmed', 'declared', false, $5)""",
                    user_id, predicate, entity_id, PRIVATE_DECLARED_CONFIDENCE,
                    decay_fn_for(predicate))
    # Private memory is not matched, so no recompute_user_embeddings is needed.


async def declare_for_review(
    pool: asyncpg.Pool,
    user_id: str,
    predicate: str,
    value: str,
    *,
    source_system: str = CARDS_MCP_SOURCE,
) -> bool:
    """Write a private typed MCP fact that appears in the review inbox.

    Uses source='declared' + source_system='cards_mcp' so get_suggestions can
    include these without pulling user_confirmed private memory.
    Returns False if the value was empty / predicate invalid.
    """
    if predicate not in PRIVATE_DECLARE_ENTITY_TYPE:
        return False
    value = (value or "").strip()
    if not value:
        return False
    entity_type = PRIVATE_DECLARE_ENTITY_TYPE[predicate]
    async with pool.acquire() as conn:
        async with conn.transaction():
            entity_id = await resolve_entity(conn, user_id, value, entity_type)
            existing = await conn.fetchrow(
                """SELECT id, dismissed_at FROM assertions
                    WHERE user_id = $1 AND predicate = $2
                      AND object_entity_id = $3 AND valid_until IS NULL LIMIT 1""",
                user_id, predicate, entity_id)
            if existing:
                # Re-report of a dismissed fact stays dismissed (teach the filter).
                if existing["dismissed_at"] is not None:
                    return False
                await conn.execute(
                    """UPDATE assertions SET source = 'declared', source_system = $2,
                          confidence = $3, version = version + 1,
                          is_public = false
                        WHERE id = $1""",
                    existing["id"], source_system, PRIVATE_DECLARED_CONFIDENCE)
            else:
                await conn.execute(
                    """INSERT INTO assertions
                         (user_id, predicate, object_entity_id, confidence, source_system,
                          source, is_public, decay_fn)
                       VALUES ($1, $2, $3, $4, $5, 'declared', false, $6)""",
                    user_id, predicate, entity_id, PRIVATE_DECLARED_CONFIDENCE,
                    source_system, decay_fn_for(predicate))
    return True


async def cards_mcp_writes_today(pool: asyncpg.Pool, user_id: str) -> int:
    """Count cards_mcp assertions touched today (for the soft daily cap)."""
    return int(await pool.fetchval(
        """SELECT COUNT(*) FROM assertions
            WHERE user_id = $1 AND source_system = $2
              AND extracted_at >= date_trunc('day', now() AT TIME ZONE 'utc')
              AND valid_until IS NULL""",
        user_id, CARDS_MCP_SOURCE,
    ) or 0)


async def under_daily_cap(
    pool: asyncpg.Pool, user_id: str, *, cap: int = DEFAULT_DAILY_CAP,
) -> bool:
    return await cards_mcp_writes_today(pool, user_id) < cap
