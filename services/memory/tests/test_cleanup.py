"""Phase 5 — cleanup of facts stored before the unified write path: dry run writes nothing,
apply then undo restores the exact previous active set, approved facts are never touched."""
import json
import pathlib
import subprocess
import sys

import pytest

from app.services import cleanup
from app.services.cleanup import Fact, apply_plan, load_facts, new_run_id, plan_user, undo
from seed import make_user, seed_fact


def fact(i, predicate, name, etype="skill_technical", conf=0.8, approved=False, entity=None):
    return Fact(f"id{i}", predicate, name, etype, entity or f"e{i}", conf, approved)


def kinds(plan):
    return sorted((a.kind, a.reason.removeprefix("cleanup_"), a.fact.id) for a in plan.actions)


# ── planning (pure) ──────────────────────────────────────────────────────────────

def test_spelling_duplicates_keep_the_strongest_predicate():
    plan = plan_user("u", [fact(1, "has_skill", "JS"), fact(2, "uses_tool", "javascript"),
                           fact(3, "has_expertise_in", "JavaScript", conf=0.7)])
    assert kinds(plan) == [("archive", "merge", "id1"), ("archive", "merge", "id2")]
    assert {a.kept for a in plan.actions} == {"id3"}


def test_a_language_filed_as_a_tool_is_reclassified_as_a_skill():
    plan = plan_user("u", [fact(1, "uses_tool", "Python 3.12")])
    assert kinds(plan) == [("archive", "merge", "id1"), ("insert", "insert", "id1")]
    assert plan.actions[1].new_predicate == "has_skill" and plan.counts == {"merge": 1, "reclassify": 1}


def test_a_product_stays_a_tool_and_unrelated_facts_are_left_alone():
    assert plan_user("u", [fact(1, "uses_tool", "Docker"), fact(2, "has_skill", "Rust"),
                           fact(3, "is_building", "Zynd", "project_venture")]).actions == []


def test_markup_languages_are_noise():
    plan = plan_user("u", [fact(1, "has_skill", "HTML"), fact(2, "has_skill", "css"), fact(3, "uses_tool", "Dockerfile"),
                           fact(4, "has_skill", "Python")])
    assert kinds(plan) == [("archive", "noise", "id1"), ("archive", "noise", "id2"), ("archive", "noise", "id3")]


def test_approved_facts_are_never_touched():
    plan = plan_user("u", [fact(1, "has_skill", "HTML", approved=True),                  # approved noise stays
                           fact(2, "has_skill", "Python", approved=True),                # approved weaker stays
                           fact(3, "has_expertise_in", "Python"),
                           fact(4, "uses_tool", "react", approved=True)])                # approved misfiled tool stays
    assert plan.actions == []


def test_learning_a_field_next_to_expertise_is_kept_but_learning_a_technology_is_merged():
    assert plan_user("u", [fact(1, "has_expertise_in", "machine learning", "skill_domain"),
                           fact(2, "is_learning", "machine learning", "skill_domain")]).actions == []
    plan = plan_user("u", [fact(1, "has_skill", "Rust"), fact(2, "is_learning", "Rust")])
    assert kinds(plan) == [("archive", "merge", "id2")]


def test_projects_merge_across_the_work_family():
    plan = plan_user("u", [fact(1, "is_building", "Zynd", "project_venture"), fact(2, "is_working_on", "zynd", "project_assignment")])
    assert kinds(plan) == [("archive", "merge", "id2")]


def test_the_plan_is_stable_when_nothing_is_left_to_do():
    assert plan_user("u", []).actions == []


# ── against Postgres ──────────────────────────────────────────────────────────────

async def active_ids(pg, uid):
    return {str(r["id"]) for r in await pg.fetch("SELECT id FROM assertions WHERE user_id = $1 AND valid_until IS NULL", uid)}


async def messy_user(pg):
    uid = await make_user(pg)
    await seed_fact(pg, uid, "uses_tool", "js", confidence=0.7)
    await seed_fact(pg, uid, "has_skill", "JavaScript", confidence=0.8)
    await seed_fact(pg, uid, "uses_tool", "Python 3.12", confidence=0.75)
    await seed_fact(pg, uid, "has_skill", "HTML", confidence=0.6)
    await seed_fact(pg, uid, "has_skill", "CSS", confidence=0.6, approved=True)
    await seed_fact(pg, uid, "uses_tool", "Docker", confidence=0.8)
    await seed_fact(pg, uid, "is_building", "Zynd", "project_venture", confidence=0.9)
    return uid


@pytest.mark.integration
async def test_a_dry_run_changes_nothing(pg):
    uid = await messy_user(pg)
    before = await active_ids(pg, uid)
    history = await pg.fetchval("SELECT count(*) FROM assertion_history")
    plan = plan_user(uid, await load_facts(pg, uid))
    assert plan.actions                                  # there is something to do...
    assert await active_ids(pg, uid) == before and await pg.fetchval("SELECT count(*) FROM assertion_history") == history


@pytest.mark.integration
async def test_apply_cleans_up_and_undo_restores_the_exact_previous_active_set(pg):
    uid = await messy_user(pg)
    before = await active_ids(pg, uid)
    run = new_run_id()

    done = await apply_plan(pg, plan_user(uid, await load_facts(pg, uid)), run)

    after = {(r["predicate"], r["canonical_name"]) for r in await pg.fetch(
        "SELECT a.predicate, e.canonical_name FROM assertions a JOIN entities e ON e.id = a.object_entity_id "
        "WHERE a.user_id = $1 AND a.valid_until IS NULL", uid)}
    assert after == {("has_skill", "JavaScript"), ("has_skill", "Python 3.12"), ("has_skill", "CSS"),
                     ("uses_tool", "Docker"), ("is_building", "Zynd")}       # CSS is approved: kept; HTML archived
    assert done == {"archived": 3, "inserted": 1}       # js, HTML, and the misfiled Python tool
    assert await pg.fetchval("SELECT count(*) FROM assertions WHERE user_id = $1", uid) == 8      # nothing deleted (7 seeded + 1 inserted)
    assert await pg.fetchval("SELECT count(*) FROM assertion_history WHERE change_reason LIKE $1", f"cleanup_%:{run}") == 4

    # the plan is now empty: running it again does nothing
    assert plan_user(uid, await load_facts(pg, uid)).actions == []

    result = await undo(pg, run)

    assert result == {"restored": 3, "removed": 1}
    assert await active_ids(pg, uid) == before
    assert await undo(pg, run) == {"restored": 0, "removed": 0}                            # idempotent


@pytest.mark.integration
async def test_apply_keeps_the_reclassified_fact_private_and_on_the_same_entity(pg):
    uid = await make_user(pg)
    old = await seed_fact(pg, uid, "uses_tool", "Python 3.12", confidence=0.75)
    await apply_plan(pg, plan_user(uid, await load_facts(pg, uid)), new_run_id())
    row = await pg.fetchrow(
        "SELECT predicate, is_public, confidence, object_entity_id, decay_fn FROM assertions WHERE user_id = $1 AND valid_until IS NULL", uid)
    old_entity = await pg.fetchval("SELECT object_entity_id FROM assertions WHERE id = $1", old)
    assert (row["predicate"], row["is_public"], row["confidence"]) == ("has_skill", False, 0.75)
    assert row["object_entity_id"] == old_entity and row["decay_fn"] == "exponential(halflife=730d)"


@pytest.mark.integration
async def test_users_are_independent_and_other_users_are_untouched(pg):
    a, b = await messy_user(pg), await make_user(pg)
    await seed_fact(pg, b, "has_skill", "Rust")
    before_b = await active_ids(pg, b)
    await apply_plan(pg, plan_user(a, await load_facts(pg, a)), new_run_id())
    assert await active_ids(pg, b) == before_b
    assert set(await cleanup.user_ids(pg)) == {a, b}


# ── the CLI ──────────────────────────────────────────────────────────────────────

ROOT = pathlib.Path(__file__).resolve().parents[1]


def run_cli(*args, db="zynd_test"):
    env = {"DATABASE_URL": f"postgresql://zynd:zynd@localhost:5433/{db}", "PATH": "/usr/bin:/bin", "MOCK_LLM": "true"}
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "dedupe_memory.py"), *args], capture_output=True,
                          text=True, cwd=ROOT, env=env, timeout=60)


@pytest.mark.integration
async def test_cli_dry_run_writes_a_report_and_no_changes(pg, tmp_path):
    uid = await messy_user(pg)
    before = await active_ids(pg, uid)
    report = tmp_path / "r.json"
    out = run_cli("--user", uid, "--report", str(report))
    assert out.returncode == 0, out.stderr
    data = json.loads(report.read_text())
    assert data["mode"] == "dry-run" and data["users"][0]["user_id"] == uid
    assert data["totals"]["merge"] >= 1 and "password" not in report.read_text()
    assert await active_ids(pg, uid) == before


@pytest.mark.integration
async def test_cli_refuses_to_apply_or_undo_without_naming_the_database(pg, tmp_path):
    uid = await messy_user(pg)
    before = await active_ids(pg, uid)
    for args in (["--apply"], ["--apply", "--confirm-database", "prod"], ["--undo", "abc123"]):
        out = run_cli("--user", uid, "--report", str(tmp_path / "r.json"), *args)
        assert out.returncode == 2 and "--confirm-database" in out.stdout
    assert await active_ids(pg, uid) == before
