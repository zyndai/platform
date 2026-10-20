"""The one place a fact is written: one fact per thing.

Extraction, typed MCP reports, declared facts and syncs used to each resolve an entity and
upsert an assertion their own way, so the same thing was stored again under another
predicate, another spelling or another entity type. Every write now goes through
`write_fact`, which

  1. canonicalizes the name ("js" -> "JavaScript", "Python 3.12" -> "Python"),
  2. reclassifies a language or framework sent as a *tool* into a skill (D2),
  3. resolves the entity across the types that name the same kind of thing,
  4. finds the existing facts about that thing in the same family (taxonomy.family_of),
  5. keeps the stronger predicate: a weaker report only refreshes the stronger fact, a
     stronger one archives the weaker (never deletes) -- except a fact the owner has
     approved onto their card, which is never changed on its own,
  6. records the evidence and a history row.

Behind `feature_fact_families`; with the flag off callers keep their legacy write paths.
Runs inside the caller's transaction.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import asyncpg

from app.config import settings
from app.services.assertions import bayesian_update, initial_visibility
from app.services.canonical import canonical_name, dedupe_key, tech_kind
from app.services.entities import resolve_entity
from app.services.quality import canonicalize
from app.taxonomy import (
    DEFAULT_SOURCE_RELIABILITY,
    FAMILY_RANK,
    SOURCE_RELIABILITY,
    TECH_NAME_PREDICATES,
    decay_fn_for,
    entity_type_group,
    family_of,
)

logger = logging.getLogger(__name__)

Action = Literal["inserted", "updated", "bumped", "blocked"]
Visibility = Literal["private", "public"]

TECH_ENTITY_TYPE = "skill_technical"
_WORK_PREDICATES = frozenset({"is_building", "is_creating", "is_working_on", "intends_to"})
_FAMILY_PREDICATES = {
    "tech": ("has_expertise_in", "has_skill", "uses_tool", "is_learning"),
    "work": ("is_building", "is_creating", "is_working_on", "intends_to", "is_learning"),
}
DECLARED_CONFIDENCE = 0.97


@dataclass
class WriteResult:
    action: Action
    assertion_id: str | None
    predicate: str                  # the predicate actually stored (after reclassification)
    name: str                       # the canonical name actually stored
    superseded: list[str] = field(default_factory=list)   # archived assertion ids

    @property
    def written(self) -> bool:
        return self.action != "blocked"


@dataclass
class _Member:
    id: str
    predicate: str
    confidence: float
    base_confidence: float
    is_public: bool
    approved_at: datetime | None
    dismissed_at: datetime | None
    version: int
    entity_id: str
    name: str
    entity_type: str

    @property
    def rank(self) -> int:
        return FAMILY_RANK.get(self.predicate, 0)


def normalize(predicate: str, name: str, entity_type: str) -> tuple[str, str, str]:
    """(predicate, name, entity_type) as it will be stored.

    Aliases and versions are only resolved for technology-flavoured predicates, so a project
    called "Next" is never rewritten to Next.js. A language or framework reported as a tool
    becomes a skill; a technology always gets the technical entity type.
    """
    if predicate in TECH_NAME_PREDICATES:
        name = canonical_name(name)
        kind = tech_kind(name)
        if kind is not None:
            if predicate == "uses_tool" and kind in ("language", "framework"):
                predicate = "has_skill"
            entity_type = TECH_ENTITY_TYPE
    else:
        name = canonicalize(name)
    return predicate, name, entity_type


def _family_for(predicate: str, name: str, entity_type: str) -> str | None:
    tech = predicate in TECH_NAME_PREDICATES and tech_kind(name) is not None
    return family_of(predicate, is_tech=tech, is_project=entity_type.startswith("project_"))


def _key(predicate: str, name: str) -> str:
    return dedupe_key(name) if predicate in TECH_NAME_PREDICATES else name.strip().lower()


async def _family_members(
    conn: asyncpg.Connection, user_id: str, predicate: str, name: str, entity_type: str,
    entity_id: str, family: str | None,
) -> list[_Member]:
    """Active facts about the same thing in the same family (any predicate, any entity type)."""
    predicates = _FAMILY_PREDICATES.get(family or "", (predicate,))
    base = "coalesce(a.base_confidence, a.confidence)" if settings.freshness_v2 else "a.confidence"
    rows = await conn.fetch(
        f"""SELECT a.id, a.predicate, a.confidence, {base} AS base_confidence, a.is_public,
                  a.approved_at, a.dismissed_at, a.version, a.object_entity_id,
                  e.canonical_name, e.entity_type
             FROM assertions a JOIN entities e ON e.id = a.object_entity_id
            WHERE a.user_id = $1 AND a.valid_until IS NULL AND a.predicate = ANY($2::text[])""",
        user_id, list(predicates),
    )
    wanted = _key(predicate, name)
    members: list[_Member] = []
    for r in rows:
        same_entity = str(r["object_entity_id"]) == entity_id
        if family is None:
            if not same_entity or r["predicate"] != predicate:
                continue
        else:
            if _family_for(r["predicate"], r["canonical_name"], r["entity_type"]) != family:
                continue
            if not same_entity and _key(r["predicate"], r["canonical_name"]) != wanted:
                continue
        members.append(_Member(
            id=str(r["id"]), predicate=r["predicate"], confidence=float(r["confidence"]),
            base_confidence=float(r["base_confidence"]), is_public=bool(r["is_public"]), approved_at=r["approved_at"], dismissed_at=r["dismissed_at"],
            version=r["version"], entity_id=str(r["object_entity_id"]),
            name=r["canonical_name"], entity_type=r["entity_type"],
        ))
    return members


async def _log(conn: asyncpg.Connection, assertion_id: str, prev: float | None, new: float, reason: str) -> None:
    await conn.execute(
        """INSERT INTO assertion_history (assertion_id, prev_confidence, new_confidence, change_reason)
           VALUES ($1, $2, $3, $4)""",
        assertion_id, prev, new, reason,
    )


async def _supersede(conn: asyncpg.Connection, members: list[_Member]) -> list[str]:
    """Archive weaker duplicates. Never an approved fact: what is public is the owner's call."""
    archived: list[str] = []
    for m in members:
        if m.approved_at is not None:
            continue
        await conn.execute("UPDATE assertions SET valid_until = now() WHERE id = $1", m.id)
        await _log(conn, m.id, m.confidence, m.confidence, "superseded")
        archived.append(m.id)
    return archived


async def write_fact(
    conn: asyncpg.Connection,
    user_id: str,
    predicate: str,
    name: str,
    *,
    entity_type: str,
    confidence: float,
    source: Literal["inferred", "declared"],
    source_system: str,
    trace_chunk_id: str | None = None,
    observed_at: datetime | None = None,
    visibility: Visibility | None = None,
    explicit: bool = False,
    block_if_dismissed: bool = False,
) -> WriteResult:
    """Write one fact, keeping a single fact per real-world thing. Caller owns the transaction.

    confidence is the strength of THIS evidence for inferred facts (Bayesian-combined with
    what is stored) and is ignored for declared ones (flat DECLARED_CONFIDENCE).
    visibility None = private, except new inferred facts follow `initial_visibility`.
    explicit marks an owner action (declare / editor): it upserts its own predicate and is
    never folded into a stronger sibling. block_if_dismissed turns a report of something the
    owner already dismissed (in any predicate of the family) into a no-op.
    """
    declared = source == "declared"
    surface = (name or "").strip()
    predicate, name, entity_type = normalize(predicate, name, entity_type)
    if not name:
        return WriteResult("blocked", None, predicate, "")
    family = _family_for(predicate, name, entity_type)
    work = family == "work" or predicate in _WORK_PREDICATES
    group = entity_type_group(entity_type, tech_name=predicate in TECH_NAME_PREDICATES, work=work)
    entity_id = await resolve_entity(conn, user_id, name, entity_type, type_group=group, surface_form=surface)

    members = await _family_members(conn, user_id, predicate, name, entity_type, entity_id, family)
    same = max((m for m in members if m.predicate == predicate), key=lambda m: m.confidence, default=None)
    stronger = [m for m in members if m.rank > FAMILY_RANK.get(predicate, 0) and m.predicate != predicate]
    weaker = [m for m in members if m.rank < FAMILY_RANK.get(predicate, 0) and m.predicate != predicate]
    family_dismissed = any(m.dismissed_at is not None for m in members)

    if block_if_dismissed and family_dismissed:
        return WriteResult("blocked", None, predicate, name)

    reliability = SOURCE_RELIABILITY.get(source_system, DEFAULT_SOURCE_RELIABILITY)
    evidence_at = observed_at

    # A weaker report of something already held more strongly only refreshes the stronger fact.
    if same is None and stronger and not explicit:
        top = max(stronger, key=lambda m: (m.rank, m.confidence))
        seen = ""
        if settings.freshness_v2:
            # The weaker report is evidence for the stronger fact: it was seen again, now.
            seen = """, last_seen_at = greatest(coalesce(last_seen_at, $2), $2),
                      mention_count = CASE WHEN $3::uuid IS NOT NULL AND $3::uuid IS DISTINCT FROM trace_chunk_id
                                           THEN mention_count + 1 ELSE mention_count END"""
        await conn.execute(
            f"""UPDATE assertions SET version = version + 1,
                      observed_at = greatest(coalesce(observed_at, $2), $2){seen}
                WHERE id = $1""",
            top.id, evidence_at or datetime.now(timezone.utc),
            *([trace_chunk_id] if settings.freshness_v2 else []),
        )
        await _log(conn, top.id, top.confidence, top.confidence, "new_evidence")
        return WriteResult("bumped", top.id, top.predicate, top.name)

    if same is not None:
        if declared:
            new_conf = DECLARED_CONFIDENCE
        else:
            # Evidence combines with the confidence the fact had before time decay, so a fact
            # that decayed while unseen is not penalized twice (Phase 4).
            new_conf = bayesian_update(same.base_confidence, confidence, reliability)
        public = visibility == "public"
        v2 = ""
        args = [same.id, new_conf, declared, source_system, trace_chunk_id, evidence_at, public, explicit and public]
        if settings.freshness_v2:
            v2 = """,
                      base_confidence = $2,
                      last_seen_at = greatest(coalesce(last_seen_at, coalesce($6, now())), coalesce($6, now())),
                      mention_count = CASE WHEN $5::uuid IS NOT NULL AND $5::uuid IS DISTINCT FROM trace_chunk_id
                                           THEN mention_count + 1 ELSE mention_count END"""
        await conn.execute(
            f"""UPDATE assertions
                  SET confidence = $2, version = version + 1,
                      source = CASE WHEN $3 THEN 'declared' ELSE source END,
                      source_system = CASE WHEN approved_at IS NOT NULL OR source IN ('declared', 'both')
                                           THEN source_system ELSE $4 END,
                      trace_chunk_id = coalesce($5, trace_chunk_id),
                      observed_at = coalesce($6, now()),
                      is_public = CASE WHEN $7 THEN true ELSE is_public END,
                      approved_at = CASE WHEN $7 THEN now() ELSE approved_at END,
                      dismissed_at = CASE WHEN $8 THEN NULL ELSE dismissed_at END{v2}
                WHERE id = $1""",
            *args,
        )
        await _log(conn, same.id, same.confidence, new_conf, "declared" if declared else "new_evidence")
        archived = await _supersede(conn, [m for m in weaker])
        return WriteResult("updated", same.id, predicate, name, archived)

    # Nothing about this thing yet, or this report is the strongest: insert and retire the weaker.
    new_conf = DECLARED_CONFIDENCE if declared else bayesian_update(0.0, confidence, reliability)
    if visibility is None:
        is_public = False if declared else initial_visibility(predicate)[0]
    else:
        is_public = visibility == "public"
    v2_cols, v2_vals = "", ""
    if settings.freshness_v2:
        v2_cols = ", base_confidence, last_seen_at, mention_count"
        v2_vals = ", $4, coalesce($9, now()), 1"
    row = await conn.fetchrow(
        f"""INSERT INTO assertions
             (user_id, predicate, object_entity_id, confidence, source_system, source,
              trace_chunk_id, decay_fn, observed_at, is_public, approved_at, dismissed_at{v2_cols})
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, coalesce($9, now()), $10,
                   CASE WHEN $10 THEN now() END,
                   CASE WHEN $11 THEN now() END{v2_vals})
           RETURNING id""",
        user_id, predicate, entity_id, new_conf, source_system, source, trace_chunk_id,
        decay_fn_for(predicate), evidence_at, is_public, family_dismissed and not explicit,
    )
    assertion_id = str(row["id"])
    await _log(conn, assertion_id, None, new_conf, "declared" if declared else "new_evidence")
    archived = await _supersede(conn, weaker)
    return WriteResult("inserted", assertion_id, predicate, name, archived)


def dedupe_tech_fields(
    languages: list[str] | None,
    frameworks: list[str] | None,
    skills: list[str] | None,
    tools: list[str] | None,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Collapse the typed MCP tech fields so each technology appears once (D2).

    JavaScript sent as a language, a tool and a skill used to be three facts. Values are
    canonicalized and de-duplicated across the four fields in priority order (languages,
    frameworks, skills, tools); a language or framework sent under `tools` is a skill.
    """
    seen: set[str] = set()
    out: dict[str, list[str]] = {"languages": [], "frameworks": [], "skills": [], "tools": []}
    for field, values in (("languages", languages), ("frameworks", frameworks),
                          ("skills", skills), ("tools", tools)):
        for raw in values or []:
            name = canonical_name(raw)
            if not name or dedupe_key(name) in seen:
                continue
            seen.add(dedupe_key(name))
            target = field
            if field == "tools" and tech_kind(name) in ("language", "framework"):
                target = "skills"
            out[target].append(name)
    return out["languages"], out["frameworks"], out["skills"], out["tools"]


MAX_TECH_VALUES = 5


def cap_tech_values(
    languages: list[str] | None, frameworks: list[str] | None,
    skills: list[str] | None, tools: list[str] | None, limit: int = MAX_TECH_VALUES,
) -> tuple[list[str], list[str], list[str], list[str], int]:
    """Keep at most `limit` technologies across the four typed fields, in priority order
    (languages, frameworks, skills, tools). Returns the trimmed lists and how many were dropped.

    One report that names ten technologies is an agent reading a repo's package.json, not a
    person saying what they use.
    """
    lists = [list(languages or []), list(frameworks or []), list(skills or []), list(tools or [])]
    total = sum(len(v) for v in lists)
    room = limit
    out: list[list[str]] = []
    for values in lists:
        out.append(values[:max(room, 0)])
        room -= len(out[-1])
    return out[0], out[1], out[2], out[3], max(total - limit, 0)
