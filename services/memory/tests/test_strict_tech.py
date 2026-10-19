"""Phase 3 — keep dependency noise out: strict extraction, second sighting, per-call cap."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import settings
from app.models import ExtractedAssertion
from app.services import extraction, findability
from app.services.export import rank_context
from app.services.facts import cap_tech_values
from app.services.quality import visible_sql
from seed import make_user, seed_fact


def item(predicate, name, etype="skill_technical", conf=0.8):
    return ExtractedAssertion(predicate=predicate, object_name=name, object_type=etype, confidence=conf)


@pytest.fixture
def strict(monkeypatch):
    monkeypatch.setattr(settings, "feature_strict_tech", True)


# ── prompt ────────────────────────────────────────────────────────────────────────

def test_the_strict_block_is_only_in_the_prompt_when_the_flag_is_on(monkeypatch):
    monkeypatch.setattr(settings, "feature_strict_tech", False)
    assert extraction.system_prompt() == extraction.SYSTEM_PROMPT
    monkeypatch.setattr(settings, "feature_strict_tech", True)
    prompt = extraction.system_prompt()
    assert prompt.startswith(extraction.SYSTEM_PROMPT)
    flat = " ".join(prompt.split())
    for phrase in ("stack trace", "lockfile", "one-off task", "webpack config", "No module named"):
        assert phrase in flat


async def test_the_strict_prompt_is_what_the_model_is_sent(strict, monkeypatch):
    create = AsyncMock(return_value=MagicMock(choices=[MagicMock(message=MagicMock(content='{"assertions": []}'))]))
    client = MagicMock()
    client.chat.completions.create = create
    monkeypatch.setattr(extraction, "_get_client", lambda: client)
    monkeypatch.setattr(settings, "mock_llm", False)
    await extraction.extract_assertions("I run all my services on Kubernetes")
    system = create.await_args.kwargs["messages"][0]["content"]
    assert "NOT about the person" in system


# ── deterministic guard (the model is not trusted to enforce the prompt alone) ─────

@pytest.mark.parametrize("text", [
    "Traceback (most recent call last):\n  File \"app.py\", line 3, in <module>\nModuleNotFoundError: x",
    "npm ERR! code ELIFECYCLE\nnpm ERR! webpack exited with 1",
    "    at Object.<anonymous> (/srv/app/node_modules/webpack/lib/x.js:10:5)",
    '{ "dependencies": { "react": "^18", "lodash": "^4" } }',
    "diff --git a/package.json b/package.json\n+++ b/package.json",
    "requests==2.31.0\nflask==3.0.0\n",
])
def test_technologies_named_in_machine_output_are_not_the_persons(text):
    out = extraction.guard_extractions(text, [
        item("uses_tool", "webpack"), item("has_skill", "React"), item("is_located_in", "Pune", "place_physical"),
        item("has_expertise_in", "supply chains", "skill_domain"),
    ])
    assert [a.object_name for a in out] == ["Pune", "supply chains"]      # tech dropped, the rest kept


def test_the_same_technologies_are_kept_when_the_person_is_speaking():
    assert len(extraction.guard_extractions("I use webpack and React every day", [
        item("uses_tool", "webpack"), item("has_skill", "React")])) == 2


@pytest.mark.parametrize("name,kept", [
    ("fix the login bug", False), ("rename this file", False), ("Bump the version", False),
    ("debugging the payment webhook", False), ("Verusa outreach pipeline", True), ("fixed-income research", True),
])
def test_a_one_off_task_is_not_a_work_stream(name, kept):
    out = extraction.guard_extractions("anything", [item("is_working_on", name, "project_assignment")])
    assert bool(out) is kept


async def test_mock_extraction_applies_the_guard_when_strict(strict, monkeypatch):
    monkeypatch.setattr(settings, "mock_llm", True)
    out = await extraction.extract_assertions("I am working on fix the login bug. I am building Verusa.")
    names = {a.object_name for a in out}
    assert "fix the login bug" not in names and "Verusa" in names


# ── second sighting ───────────────────────────────────────────────────────────────

def test_visible_sql_is_a_noop_unless_strict(monkeypatch):
    monkeypatch.setattr(settings, "feature_strict_tech", False)
    assert visible_sql() == "TRUE"
    monkeypatch.setattr(settings, "feature_strict_tech", True)
    assert "version < 2" in visible_sql("x") and "x.source = 'inferred'" in visible_sql("x")
    monkeypatch.setattr(settings, "feature_freshness_v2", True)
    assert "mention_count < 2" in visible_sql()


@pytest.mark.integration
async def test_a_skill_seen_once_stays_out_of_context_until_seen_twice(pg, strict, monkeypatch):
    monkeypatch.setattr(settings, "feature_ranked_context", True)
    uid = await make_user(pg)
    await seed_fact(pg, uid, "has_skill", "Webpack", confidence=0.72, version=1)       # once, inferred
    await seed_fact(pg, uid, "has_skill", "Rust", confidence=0.72, version=2)          # seen twice
    await seed_fact(pg, uid, "has_skill", "Python", confidence=0.95, version=1)        # strongly evidenced
    await seed_fact(pg, uid, "uses_tool", "Docker", confidence=0.72, version=1, source="declared")
    await seed_fact(pg, uid, "is_building", "Verusa", "project_venture", confidence=0.72, version=1)
    names = {f["object"] for f in await rank_context(pg, uid, topic=None, k=20)}
    assert names == {"Rust", "Python", "Docker", "Verusa"}


@pytest.mark.integration
async def test_the_review_inbox_waits_for_a_second_sighting_too(pg, strict):
    uid = await make_user(pg)
    await seed_fact(pg, uid, "has_skill", "Webpack", confidence=0.72, version=1)
    await seed_fact(pg, uid, "has_skill", "Rust", confidence=0.72, version=2)
    shown = {s["object"] for s in await findability.get_suggestions(pg, uid)}
    assert shown == {"Rust"}


@pytest.mark.integration
async def test_flag_off_shows_everything_as_before(pg, monkeypatch):
    monkeypatch.setattr(settings, "feature_strict_tech", False)
    uid = await make_user(pg)
    await seed_fact(pg, uid, "has_skill", "Webpack", confidence=0.72, version=1)
    assert {s["object"] for s in await findability.get_suggestions(pg, uid)} == {"Webpack"}


# ── per-call cap ──────────────────────────────────────────────────────────────────

def test_cap_keeps_the_first_five_in_priority_order():
    assert cap_tech_values(["a", "b"], ["c"], ["d", "e"], ["f", "g", "h"]) == (
        ["a", "b"], ["c"], ["d", "e"], [], 3)
    assert cap_tech_values(["a"], None, None, ["b"]) == (["a"], [], [], ["b"], 0)
    assert cap_tech_values(None, None, None, None) == ([], [], [], [], 0)


@pytest.mark.integration
async def test_report_user_info_trims_a_repo_dump_and_says_so(pg, strict, monkeypatch):
    import app.mcp_http as m
    uid = await make_user(pg)
    monkeypatch.setattr(m, "_pool", pg)
    monkeypatch.setattr(settings, "feature_s05_typed_capture", True)
    dump = ["webpack", "lodash", "jest", "eslint", "react", "moment", "express"]
    result = await m.report_user_info(tools=dump, uid=uid)
    assert result["saved"] is True and "ignored 2 more" in result["tech_note"]
    stored = await pg.fetch(
        "SELECT e.canonical_name FROM assertions a JOIN entities e ON e.id = a.object_entity_id WHERE a.user_id = $1", uid)
    assert len(stored) <= 4          # per-field cap already limited tools to 4; the note carries the rest
