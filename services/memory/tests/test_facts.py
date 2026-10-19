"""Phase 2 — one fact per thing: write_fact precedence, canonical names, dismissal, approval."""
import itertools
import uuid

import pytest

from app.config import settings
from app.services import findability
from app.services.facts import dedupe_tech_fields, normalize, write_fact
from seed import make_user, seed_fact

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def families(monkeypatch):
    monkeypatch.setattr(settings, "feature_fact_families", True)


async def active(pg, uid, name=None):
    rows = await pg.fetch(
        """SELECT a.predicate, e.canonical_name AS name, e.entity_type, a.is_public, a.approved_at,
                  a.dismissed_at, a.source, a.version, a.confidence
             FROM assertions a JOIN entities e ON e.id = a.object_entity_id
            WHERE a.user_id = $1 AND a.valid_until IS NULL
            ORDER BY a.predicate""", uid)
    return [r for r in rows if name is None or r["name"].lower() == name.lower()]


async def archived(pg, uid):
    return await pg.fetch(
        """SELECT a.predicate, e.canonical_name AS name FROM assertions a
             JOIN entities e ON e.id = a.object_entity_id
            WHERE a.user_id = $1 AND a.valid_until IS NOT NULL""", uid)


async def put(pg, uid, predicate, name, etype="skill_technical", **kw):
    kw.setdefault("confidence", 0.9)
    kw.setdefault("source", "inferred")
    kw.setdefault("source_system", "claude")
    async with pg.acquire() as conn, conn.transaction():
        return await write_fact(conn, uid, predicate, name, entity_type=etype, **kw)


# ── normalization (pure) ───────────────────────────────────────────────────────────

def test_normalize_canonicalizes_tech_names_and_reclassifies_languages_and_frameworks():
    assert normalize("uses_tool", "js", "concept_topic") == ("has_skill", "JavaScript", "skill_technical")
    assert normalize("uses_tool", "React 18", "skill_domain") == ("has_skill", "React", "skill_technical")
    assert normalize("uses_tool", "docker", "skill_technical") == ("uses_tool", "Docker", "skill_technical")
    assert normalize("has_expertise_in", "machine learning", "skill_domain") == (
        "has_expertise_in", "machine learning", "skill_domain")


def test_normalize_leaves_projects_and_places_alone():
    assert normalize("is_building", "Next", "project_venture") == ("is_building", "Next", "project_venture")
    assert normalize("is_located_in", "  'SF'  ", "place_physical") == ("is_located_in", "SF", "place_physical")


# ── the plan's "done when": JavaScript three ways, any order ──────────────────────

@pytest.mark.parametrize("order", list(itertools.permutations(
    [("has_skill", "JavaScript"), ("uses_tool", "javascript"), ("has_skill", "JS")])))
async def test_javascript_as_language_tool_and_skill_is_one_fact_in_any_order(pg, order):
    uid = await make_user(pg)
    for predicate, name in order:
        await put(pg, uid, predicate, name)
    facts = await active(pg, uid)
    assert [(f["predicate"], f["name"]) for f in facts] == [("has_skill", "JavaScript")]
    assert await pg.fetchval("SELECT count(*) FROM entities WHERE user_id = $1", uid) == 1


async def test_the_surface_forms_are_kept_as_aliases(pg):
    uid = await make_user(pg)
    await put(pg, uid, "has_skill", "JavaScript")
    await put(pg, uid, "has_skill", "js")
    await put(pg, uid, "has_skill", "javascript")          # same name, other case: not an alias
    await put(pg, uid, "has_skill", "JS")                  # already recorded
    aliases = await pg.fetchval("SELECT aliases FROM entities WHERE user_id = $1", uid)
    assert aliases == ["js"]


# ── precedence matrix ─────────────────────────────────────────────────────────────

TECH = ["has_expertise_in", "has_skill", "uses_tool"]
RANK = {"has_expertise_in": 3, "has_skill": 2, "uses_tool": 1}


@pytest.mark.parametrize("first,second", [(a, b) for a in TECH for b in TECH if a != b])
async def test_tech_family_keeps_only_the_stronger_predicate_in_either_order(pg, first, second):
    uid = await make_user(pg)
    await put(pg, uid, first, "Docker")
    await put(pg, uid, second, "Docker")
    facts = await active(pg, uid)
    assert [f["predicate"] for f in facts] == [max((first, second), key=RANK.get)]


async def test_a_weaker_report_refreshes_the_stronger_fact_instead_of_adding_a_row(pg):
    uid = await make_user(pg)
    await put(pg, uid, "has_expertise_in", "Docker")
    before = (await active(pg, uid))[0]
    result = await put(pg, uid, "uses_tool", "Docker")
    after = (await active(pg, uid))[0]
    assert result.action == "bumped" and result.predicate == "has_expertise_in"
    assert after["version"] == before["version"] + 1 and len(await active(pg, uid)) == 1
    assert await archived(pg, uid) == []


async def test_a_stronger_report_archives_the_weaker_fact_without_deleting_it(pg):
    uid = await make_user(pg)
    await put(pg, uid, "uses_tool", "Docker")
    result = await put(pg, uid, "has_skill", "Docker")
    assert result.action == "inserted" and len(result.superseded) == 1
    assert [(r["predicate"], r["name"]) for r in await archived(pg, uid)] == [("uses_tool", "Docker")]
    reasons = await pg.fetch("SELECT change_reason FROM assertion_history WHERE assertion_id = $1", result.superseded[0])
    assert "superseded" in {r["change_reason"] for r in reasons}


WORK = ["is_building", "is_creating", "is_working_on", "intends_to"]
WORK_RANK = {"is_building": 4, "is_creating": 3, "is_working_on": 2, "intends_to": 1}


@pytest.mark.parametrize("first,second", [(a, b) for a in WORK for b in WORK if a != b])
async def test_work_family_keeps_only_the_stronger_predicate(pg, first, second):
    uid = await make_user(pg)
    await put(pg, uid, first, "Zynd", "project_venture")
    await put(pg, uid, second, "Zynd", "project_assignment")        # different entity type, same project
    facts = await active(pg, uid)
    assert [f["predicate"] for f in facts] == [max((first, second), key=WORK_RANK.get)]
    assert await pg.fetchval("SELECT count(*) FROM entities WHERE user_id = $1", uid) == 1


async def test_learning_a_technology_folds_into_the_tech_family_but_learning_a_field_does_not(pg):
    uid = await make_user(pg)
    await put(pg, uid, "has_skill", "Rust")
    await put(pg, uid, "is_learning", "Rust")
    assert [f["predicate"] for f in await active(pg, uid)] == ["has_skill"]

    uid2 = await make_user(pg)
    await put(pg, uid2, "has_expertise_in", "machine learning", "skill_domain")
    await put(pg, uid2, "is_learning", "machine learning", "skill_domain")
    assert sorted(f["predicate"] for f in await active(pg, uid2)) == ["has_expertise_in", "is_learning"]


async def test_learning_a_project_folds_into_the_work_family(pg):
    uid = await make_user(pg)
    await put(pg, uid, "is_building", "Zynd", "project_venture")
    await put(pg, uid, "is_learning", "Zynd", "project_venture")
    assert [f["predicate"] for f in await active(pg, uid)] == ["is_building"]


async def test_unrelated_things_are_not_merged(pg):
    uid = await make_user(pg)
    await put(pg, uid, "has_skill", "Python")
    await put(pg, uid, "has_skill", "Go")
    await put(pg, uid, "has_skill", "Taylor Swift")
    assert len(await active(pg, uid)) == 3


async def test_repeating_a_report_updates_one_row_with_bayesian_confidence(pg):
    uid = await make_user(pg)
    await put(pg, uid, "has_skill", "Rust", confidence=0.7)
    first = (await active(pg, uid))[0]
    await put(pg, uid, "has_skill", "Rust", confidence=0.7)
    second = (await active(pg, uid))[0]
    assert len(await active(pg, uid)) == 1
    assert second["version"] == 2 and second["confidence"] > first["confidence"]


# ── approved facts are never changed on their own ─────────────────────────────────

async def test_an_approved_weaker_fact_survives_a_stronger_report(pg):
    uid = await make_user(pg)
    await seed_fact(pg, uid, "has_skill", "Python", approved=True)
    result = await put(pg, uid, "has_expertise_in", "Python")
    facts = {f["predicate"]: f for f in await active(pg, uid)}
    assert set(facts) == {"has_skill", "has_expertise_in"}      # the card's fact is the owner's call
    assert facts["has_skill"]["approved_at"] is not None and result.superseded == []


async def test_a_weaker_report_never_unpublishes_an_approved_stronger_fact(pg):
    uid = await make_user(pg)
    await seed_fact(pg, uid, "has_expertise_in", "Python", approved=True)
    await put(pg, uid, "uses_tool", "Python", source="declared", source_system="cards_mcp", confidence=0.97)
    (fact,) = await active(pg, uid)
    assert fact["predicate"] == "has_expertise_in" and fact["is_public"] and fact["approved_at"]


async def test_re_reporting_an_approved_fact_keeps_it_public(pg):
    uid = await make_user(pg)
    await seed_fact(pg, uid, "has_skill", "Python", approved=True)
    await put(pg, uid, "has_skill", "Python", source="declared", source_system="cards_mcp", confidence=0.97)
    (fact,) = await active(pg, uid)
    assert fact["is_public"] and fact["approved_at"]


# ── dismissal blocks across the family ────────────────────────────────────────────

async def test_dismissed_fact_blocks_a_re_report_under_another_predicate(pg):
    uid = await make_user(pg)
    await seed_fact(pg, uid, "has_skill", "JavaScript", dismissed=True)
    ok = await findability.declare_for_review(pg, uid, "uses_tool", "javascript")
    assert ok is False
    assert [(f["predicate"]) for f in await active(pg, uid)] == ["has_skill"]


async def test_dismissal_carries_over_to_a_stronger_inferred_fact(pg):
    uid = await make_user(pg)
    await seed_fact(pg, uid, "uses_tool", "Docker", dismissed=True)
    await put(pg, uid, "has_expertise_in", "Docker")
    (fact,) = await active(pg, uid)
    assert fact["predicate"] == "has_expertise_in" and fact["dismissed_at"] is not None


async def test_an_explicit_declaration_clears_dismissal(pg):
    uid = await make_user(pg)
    await seed_fact(pg, uid, "has_expertise_in", "Python", dismissed=True)
    await findability.declare(pg, uid, "has_expertise_in", "Python")
    (fact,) = await active(pg, uid)
    assert fact["dismissed_at"] is None and fact["is_public"] and fact["approved_at"]


# ── entity resolution across types ────────────────────────────────────────────────

async def test_a_name_stored_under_another_entity_type_is_reused(pg):
    uid = await make_user(pg)
    await seed_fact(pg, uid, "has_skill", "JavaScript", "concept_topic")
    await put(pg, uid, "has_skill", "javascript", "skill_technical")
    assert await pg.fetchval("SELECT count(*) FROM entities WHERE user_id = $1", uid) == 1
    assert len(await active(pg, uid)) == 1


async def test_legacy_duplicates_converge_on_the_next_write(pg):
    uid = await make_user(pg)
    await seed_fact(pg, uid, "uses_tool", "JS")           # old data: alias spelling, own entity
    await seed_fact(pg, uid, "has_skill", "javascript")
    await put(pg, uid, "has_expertise_in", "JavaScript")
    assert [f["predicate"] for f in await active(pg, uid)] == ["has_expertise_in"]


# ── callers ───────────────────────────────────────────────────────────────────────

async def test_declare_for_review_collapses_languages_and_tools(pg):
    uid = await make_user(pg)
    for predicate, value in [("has_skill", "JavaScript"), ("uses_tool", "javascript"), ("has_skill", "JS")]:
        await findability.declare_for_review(pg, uid, predicate, value)
    facts = await active(pg, uid)
    assert [(f["predicate"], f["name"], f["is_public"]) for f in facts] == [("has_skill", "JavaScript", False)]


async def test_declare_publishes_and_declare_private_stays_private(pg):
    uid = await make_user(pg)
    await findability.declare(pg, uid, "uses_tool", "Figma")
    await findability.declare_private(pg, uid, "has_skill", "Rust")
    by_pred = {f["predicate"]: f for f in await active(pg, uid)}
    assert by_pred["uses_tool"]["is_public"] and by_pred["uses_tool"]["approved_at"]
    assert not by_pred["has_skill"]["is_public"] and by_pred["has_skill"]["source"] == "declared"


async def test_declare_reclassifies_a_language_declared_as_a_tool(pg):
    uid = await make_user(pg)
    await findability.declare(pg, uid, "uses_tool", "Python 3.12")
    (fact,) = await active(pg, uid)
    assert (fact["predicate"], fact["name"]) == ("has_skill", "Python")


async def test_new_inferred_facts_stay_private_by_default(pg):
    uid = await make_user(pg)
    await put(pg, uid, "has_skill", "Rust")
    (fact,) = await active(pg, uid)
    assert fact["is_public"] is False and fact["source"] == "inferred"


# ── cross-field dedupe for report_user_info ───────────────────────────────────────

def test_dedupe_tech_fields_saves_each_technology_once():
    assert dedupe_tech_fields(["JavaScript", "python 3.12"], ["React", "nextjs"],
                              ["js", "Rust", "docker"], ["Docker", "javascript", "react", "Figma"]) == (
        ["JavaScript", "Python"], ["React", "Next.js"], ["Rust", "Docker"], ["Figma"])


def test_dedupe_tech_fields_moves_languages_and_frameworks_out_of_tools():
    langs, fws, skills, tools = dedupe_tech_fields([], [], [], ["Python", "Docker", "FastAPI"])
    assert (langs, fws) == ([], []) and skills == ["Python", "FastAPI"] and tools == ["Docker"]
    assert dedupe_tech_fields(None, None, None, None) == ([], [], [], [])


# ── callers: worker filter and report_user_info ───────────────────────────────────

async def _chunk(pg, uid, text, source_system):
    return str(await pg.fetchval(
        """INSERT INTO trace_chunks (user_id, source_system, raw_text, content_hash)
           VALUES ($1, $2, $3, $4) RETURNING id""", uid, source_system, text, uuid.uuid4().hex))


async def test_sync_chunks_do_not_re_extract_what_the_sync_already_declared(pg):
    from app import worker
    uid = await make_user(pg)
    text = "I am working on Launch Pad. I am based in Pune."
    synced = await _chunk(pg, uid, text, "github")
    await worker.chunk_processor({}, synced)
    facts = {f["predicate"] for f in await active(pg, uid)}
    assert "is_working_on" not in facts            # the sync declared work directly
    assert "is_located_in" in facts                # everything else still comes through

    other = await make_user(pg)
    chat = await _chunk(pg, other, text, "claude")
    await worker.chunk_processor({}, chat)
    assert "is_working_on" in {f["predicate"] for f in await active(pg, other)}


async def test_report_user_info_saves_javascript_once_across_fields(pg, monkeypatch):
    import app.mcp_http as m
    uid = await make_user(pg)
    monkeypatch.setattr(m, "_pool", pg)
    monkeypatch.setattr(settings, "feature_s05_typed_capture", True)
    result = await m.report_user_info(languages=["JavaScript"], tools=["javascript", "Docker"],
                                      skills=["JS"], uid=uid)
    assert result["saved"] is True
    facts = {(f["predicate"], f["name"]) for f in await active(pg, uid)}
    assert facts == {("has_skill", "JavaScript"), ("uses_tool", "Docker")}
