"""Clean up facts stored before the write path was unified (docs/plans/ZYND_MEMORY_QUALITY_PLAN.md, Phase 5).

`plan_user` works out what Phases 2-3 would have done to a user's existing active facts:

  - merge      duplicates of one thing (JS / javascript / JavaScript, uses_tool + has_skill) keep the
               strongest predicate; the others are archived
  - reclassify a language or framework stored as a tool becomes a skill
  - noise      markup / config "skills" (HTML, CSS, Shell, Dockerfile, ...) are archived

Nothing is ever deleted: archiving sets valid_until and writes an assertion_history row tagged with
the run id, so `undo` restores exactly the previous active set. A fact the owner approved onto
their card is never touched. `plan_user` is pure; `apply_plan` and `undo` run one transaction per user.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import asyncpg

from app.services.canonical import IGNORED_SKILL_LANGUAGES, canonical_name
from app.services.facts import _family_for, _key, normalize
from app.taxonomy import FAMILY_RANK, decay_fn_for

REASON_MERGE = "cleanup_merge"
REASON_NOISE = "cleanup_noise"
REASON_INSERT = "cleanup_insert"
REASON_UNDO = "cleanup_undo"


@dataclass(frozen=True)
class Fact:
    id: str
    predicate: str
    name: str
    entity_type: str
    entity_id: str
    confidence: float
    approved: bool


@dataclass
class Action:
    kind: str                    # archive | insert
    reason: str                  # cleanup_merge | cleanup_noise | cleanup_insert
    fact: Fact                   # the fact archived, or the fact the inserted one replaces
    detail: str
    new_predicate: str | None = None
    kept: str | None = None      # id of the fact that wins, for merges

    def as_dict(self) -> dict:
        return {
            "action": self.kind, "reason": self.reason, "assertion_id": self.fact.id,
            "predicate": self.fact.predicate, "object": self.fact.name, "detail": self.detail,
            **({"new_predicate": self.new_predicate} if self.new_predicate else {}),
            **({"kept": self.kept} if self.kept else {}),
        }


@dataclass
class Plan:
    user_id: str
    actions: list[Action] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for a in self.actions:
            key = "reclassify" if a.kind == "insert" else a.reason.removeprefix("cleanup_")
            out[key] = out.get(key, 0) + 1
        return out


def plan_user(user_id: str, facts: list[Fact]) -> Plan:
    plan = Plan(user_id)
    archived: set[str] = set()

    # 1. noise: markup / config languages stored as skills (never an approved one)
    for f in facts:
        if f.predicate in ("has_skill", "uses_tool") and f.name.strip().lower() in IGNORED_SKILL_LANGUAGES and not f.approved:
            plan.actions.append(Action("archive", REASON_NOISE, f, f"{f.name} is markup or config, not a skill"))
            archived.add(f.id)

    # 2. merge / reclassify what is left, one group per real-world thing
    groups: dict[tuple[str, str], list[tuple[Fact, str, str]]] = {}
    for f in facts:
        if f.id in archived:
            continue
        predicate, name, entity_type = normalize(f.predicate, f.name, f.entity_type)
        family = _family_for(predicate, name, entity_type)
        groups.setdefault((family or predicate, _key(predicate, name)), []).append((f, predicate, name))

    for members in groups.values():
        def strength(m):
            return (FAMILY_RANK.get(m[1], 0), m[0].approved, m[0].confidence)
        winner, w_pred, _ = max(members, key=strength)
        # An approved fact is the owner's call: kept as it is, whatever it duplicates.
        for f, pred, _name in members:
            if f.id == winner.id or f.approved:
                continue
            plan.actions.append(Action(
                "archive", REASON_MERGE, f,
                f"duplicate of {winner.predicate} {winner.name}" if f.predicate != winner.predicate or f.name != winner.name
                else "exact duplicate", kept=winner.id))
        # The winner itself may be stored under the wrong predicate (a language filed as a tool).
        if w_pred != winner.predicate and not winner.approved:
            plan.actions.append(Action(
                "archive", REASON_MERGE, winner, f"{winner.predicate} -> {w_pred}", new_predicate=w_pred))
            plan.actions.append(Action(
                "insert", REASON_INSERT, winner, f"{w_pred} replaces {winner.predicate}", new_predicate=w_pred))
    return plan


# ── database ──────────────────────────────────────────────────────────────────────

async def load_facts(conn: asyncpg.Connection, user_id: str) -> list[Fact]:
    rows = await conn.fetch(
        """SELECT a.id, a.predicate, a.confidence, a.approved_at, a.object_entity_id,
                  e.canonical_name, e.entity_type
             FROM assertions a JOIN entities e ON e.id = a.object_entity_id
            WHERE a.user_id = $1 AND a.valid_until IS NULL""", user_id)
    return [Fact(str(r["id"]), r["predicate"], r["canonical_name"], r["entity_type"], str(r["object_entity_id"]),
                 float(r["confidence"]), r["approved_at"] is not None) for r in rows]


async def user_ids(pool: asyncpg.Pool) -> list[str]:
    return [str(r["user_id"]) for r in await pool.fetch(
        "SELECT DISTINCT user_id FROM assertions WHERE valid_until IS NULL ORDER BY user_id")]


async def _log(conn, assertion_id: str, confidence: float, reason: str, run_id: str) -> None:
    await conn.execute(
        """INSERT INTO assertion_history (assertion_id, prev_confidence, new_confidence, change_reason)
           VALUES ($1, $2, $2, $3)""", assertion_id, confidence, f"{reason}:{run_id}")


async def _has_v2_columns(conn: asyncpg.Connection) -> bool:
    return bool(await conn.fetchval(
        """SELECT count(*) = 3 FROM information_schema.columns
            WHERE table_name = 'assertions' AND column_name IN ('last_seen_at', 'mention_count', 'base_confidence')"""))


async def apply_plan(pool: asyncpg.Pool, plan: Plan, run_id: str) -> dict:
    """Perform one user's plan in a single transaction. Returns what was done."""
    done = {"archived": 0, "inserted": 0}
    if not plan.actions:
        return done
    async with pool.acquire() as conn, conn.transaction():
        v2 = await _has_v2_columns(conn)
        for a in plan.actions:
            if a.kind == "archive":
                changed = await conn.fetchval(
                    "UPDATE assertions SET valid_until = now() WHERE id = $1 AND valid_until IS NULL RETURNING 1", a.fact.id)
                if changed:
                    await _log(conn, a.fact.id, a.fact.confidence, a.reason, run_id)
                    done["archived"] += 1
            else:
                extra_cols = ", base_confidence, last_seen_at, mention_count" if v2 else ""
                extra_vals = ", base_confidence, last_seen_at, mention_count" if v2 else ""
                new_id = await conn.fetchval(
                    f"""INSERT INTO assertions
                          (user_id, predicate, object_entity_id, confidence, source_system, source, trace_chunk_id,
                           decay_fn, observed_at, is_public, dismissed_at{extra_cols})
                        SELECT user_id, $2, object_entity_id, confidence, source_system, source, trace_chunk_id,
                               $3, observed_at, false, dismissed_at{extra_vals}
                          FROM assertions WHERE id = $1
                        RETURNING id""",
                    a.fact.id, a.new_predicate, decay_fn_for(a.new_predicate or ""))
                await _log(conn, str(new_id), a.fact.confidence, REASON_INSERT, run_id)
                done["inserted"] += 1
    return done


async def undo(pool: asyncpg.Pool, run_id: str) -> dict:
    """Reverse a run: un-archive what it archived, archive what it inserted. Per user, in one
    transaction. Idempotent."""
    rows = await pool.fetch(
        """SELECT h.assertion_id, a.user_id, split_part(h.change_reason, ':', 1) AS reason, a.confidence
             FROM assertion_history h JOIN assertions a ON a.id = h.assertion_id
            WHERE h.change_reason LIKE $1""", f"cleanup_%:{run_id}")
    by_user: dict[str, list] = {}
    for r in rows:
        by_user.setdefault(str(r["user_id"]), []).append(r)
    restored = removed = 0
    for items in by_user.values():
        async with pool.acquire() as conn, conn.transaction():
            for r in items:
                if r["reason"] in (REASON_MERGE, REASON_NOISE):
                    if await conn.fetchval("UPDATE assertions SET valid_until = NULL WHERE id = $1 AND valid_until IS NOT NULL RETURNING 1", r["assertion_id"]):
                        await _log(conn, str(r["assertion_id"]), float(r["confidence"]), REASON_UNDO, run_id)
                        restored += 1
                elif r["reason"] == REASON_INSERT:
                    if await conn.fetchval("UPDATE assertions SET valid_until = now() WHERE id = $1 AND valid_until IS NULL RETURNING 1", r["assertion_id"]):
                        await _log(conn, str(r["assertion_id"]), float(r["confidence"]), REASON_UNDO, run_id)
                        removed += 1
    return {"restored": restored, "removed": removed}


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]
