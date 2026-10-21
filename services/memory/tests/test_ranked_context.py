"""Phase 1 — ranked context: what's true now by default, related older facts by topic."""
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.services import export
from app.services.export import (
    collapse_families,
    freshness,
    is_stale,
    rank_context,
    rank_rows,
)
from seed import make_user, seed_fact

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def row(predicate, name, *, conf=0.9, days=0.0, etype="skill_technical", relevance=None):
    seen = NOW - timedelta(days=days)
    return {
        "predicate": predicate, "object": name, "object_type": etype,
        "confidence": conf, "observed_at": seen, "seen_at": seen, "relevance": relevance,
    }


# ---- Unit: scoring pieces ----

def test_freshness_halves_every_halflife_and_ignores_no_decay():
    assert freshness("is_working_on", 0) == pytest.approx(1.0)
    assert freshness("is_working_on", 14) == pytest.approx(0.5)
    assert freshness("is_located_in", 9999) == 1.0


def test_staleness_uses_per_predicate_cutoffs():
    assert not is_stale("is_working_on", 30)
    assert is_stale("is_working_on", 31)          # D4: 30 days
    assert not is_stale("is_building", 100)
    assert is_stale("is_building", 121)
    assert not is_stale("has_skill", 5000)         # skills never go stale


def test_collapse_keeps_strongest_predicate_per_family():
    out = collapse_families([
        row("uses_tool", "javascript"), row("has_skill", "JavaScript"),
        row("has_expertise_in", "JS"),
    ])
    assert len(out) == 1 and out[0]["predicate"] == "has_expertise_in"


def test_collapse_keeps_learning_a_field_next_to_expertise_in_it():
    out = collapse_families([
        row("has_expertise_in", "machine learning", etype="skill_domain"),
        row("is_learning", "machine learning", etype="skill_domain"),
    ])
    assert len(out) == 2


def test_collapse_joins_learning_to_a_project_family():
    out = collapse_families([
        row("is_building", "Zynd", etype="project_venture"),
        row("is_learning", "Zynd", etype="project_venture"),
    ])
    assert [r["predicate"] for r in out] == ["is_building"]


def test_weaker_but_fresher_report_keeps_the_stronger_fact_current():
    out = collapse_families([
        row("is_building", "Zynd", days=200, etype="project_venture"),
        row("is_working_on", "Zynd", days=2, etype="project_venture"),
    ])
    assert out[0]["predicate"] == "is_building"
    assert out[0]["seen_at"] == NOW - timedelta(days=2)


# ---- Unit: selection ----

def test_no_topic_hides_stale_and_returns_at_most_k():
    rows = [row("has_skill", f"Skill{i}", conf=0.9 - i * 0.001) for i in range(40)]
    rows.append(row("is_working_on", "old thing", days=45, etype="project_venture"))
    out = rank_rows(rows, topic=False, k=10, now=NOW)
    assert len(out) == 10
    assert all(not f["stale"] for f in out)
    assert "old thing" not in {f["object"] for f in out}


def test_no_topic_ranks_fresh_current_work_above_old_alphabetical_noise():
    # The legacy query returned the alphabetically-first predicates. Here a fresh
    # is_working_on must beat a pile of low-weight, equally-confident skills.
    rows = [row("has_skill", f"S{i}") for i in range(30)]
    rows.append(row("is_working_on", "Launch", etype="project_venture", conf=0.9))
    out = rank_rows(rows, topic=False, k=5, now=NOW)
    assert "Launch" in {f["object"] for f in out}


def test_core_facts_always_included_but_capped_at_forty_percent():
    rows = [
        row("is_located_in", "Bengaluru", etype="place_physical", conf=0.6),
        row("is_affiliated_with", "Acme", etype="place_institutional", conf=0.6),
        *[row("has_expertise_in", f"Field{i}", conf=0.6, etype="skill_domain") for i in range(5)],
        *[row("is_building", f"Proj{i}", conf=0.6, etype="project_venture") for i in range(5)],
        *[row("is_working_on", f"Task{i}", conf=0.95, etype="project_venture") for i in range(20)],
    ]
    out = rank_rows(rows, topic=False, k=10, now=NOW)
    core = [f for f in out if f["section"] == "core"]
    assert 1 <= len(core) <= 4                      # 40% of 10
    assert len([f for f in out if f["section"] == "now"]) == len(out) - len(core)
    assert out[:len(core)] == core                  # core listed first


def test_topic_includes_stale_marked_and_drops_unrelated():
    rows = [
        row("is_working_on", "Rust parser", days=60, etype="project_venture", relevance=0.8),
        row("is_working_on", "Fresh rust thing", days=1, etype="project_venture", relevance=0.7),
        row("has_skill", "Cooking", relevance=0.1),
    ]
    out = rank_rows(rows, topic=True, k=10, now=NOW)
    by_name = {f["object"]: f for f in out}
    assert "Cooking" not in by_name
    assert by_name["Rust parser"]["stale"] is True
    assert by_name["Rust parser"]["section"] == "related"
    assert by_name["Fresh rust thing"]["section"] == "now"
    assert all("relevance" in f for f in out)


def test_topic_ranks_by_relevance_over_predicate_name():
    rows = [
        row("is_building", "Bakery", etype="project_venture", relevance=0.5),
        row("is_learning", "Rust", relevance=0.9),
    ]
    out = rank_rows(rows, topic=True, k=5, now=NOW)
    assert out[0]["object"] == "Rust"


def test_response_keeps_legacy_keys_and_adds_new_ones():
    out = rank_rows([row("has_skill", "Rust")], topic=False, k=5, now=NOW)[0]
    for key in ("statement", "predicate", "object", "object_type", "confidence", "observed_at"):
        assert key in out
    assert {"section", "stale", "last_seen_at"} <= set(out)


# ---- Integration (Postgres + pgvector) ----

@pytest.fixture
def ranked(monkeypatch):
    monkeypatch.setattr(settings, "feature_ranked_context", True)


@pytest.mark.integration
async def test_rank_context_no_topic_has_no_stale_and_no_family_duplicates(pg, ranked):
    uid = await make_user(pg)
    await seed_fact(pg, uid, "has_skill", "JavaScript")
    await seed_fact(pg, uid, "uses_tool", "javascript")
    await seed_fact(pg, uid, "has_expertise_in", "JS")
    await seed_fact(pg, uid, "is_working_on", "ancient migration", "project_assignment", days_ago=90)
    for i in range(60):
        await seed_fact(pg, uid, "has_skill", f"Library {i}", confidence=0.5 + i * 0.005)

    facts = await rank_context(pg, uid, topic=None, k=20)

    assert len(facts) <= 20
    assert not any(f["stale"] for f in facts)
    assert "ancient migration" not in {f["object"] for f in facts}
    js = [f for f in facts if f["object"].lower() in {"javascript", "js"}]
    assert len(js) <= 1


@pytest.mark.integration
async def test_rank_context_topic_changes_results_and_marks_stale(pg, ranked):
    uid = await make_user(pg)
    await seed_fact(pg, uid, "is_learning", "Rust async runtimes", confidence=0.8)
    await seed_fact(pg, uid, "is_building", "sourdough bread bakery", "project_venture", confidence=0.8)
    await seed_fact(pg, uid, "is_working_on", "Rust parser rewrite", "project_assignment",
                    confidence=0.85, days_ago=45)

    rust = await rank_context(pg, uid, topic="Rust async runtimes", k=5)
    bread = await rank_context(pg, uid, topic="sourdough bread bakery", k=5)

    assert rust[0]["object"] == "Rust async runtimes"
    assert bread[0]["object"] == "sourdough bread bakery"
    assert "sourdough bread bakery" not in {f["object"] for f in rust}
    # Mock embeddings are word-overlap hashes, so a bare "Rust" topic reaches both Rust
    # facts; the 45-day-old work stream comes back marked stale rather than hidden.
    broad = await rank_context(pg, uid, topic="Rust", k=5)
    parser = [f for f in broad if f["object"] == "Rust parser rewrite"]
    assert parser and parser[0]["stale"] and parser[0]["section"] == "related"

    default = await rank_context(pg, uid, topic=None, k=20)
    assert "Rust parser rewrite" not in {f["object"] for f in default}


@pytest.mark.integration
async def test_stale_fact_stays_active_in_the_database(pg, ranked):
    uid = await make_user(pg)
    aid = await seed_fact(pg, uid, "is_working_on", "old project", "project_assignment", days_ago=45)
    await rank_context(pg, uid, topic=None, k=20)
    assert await pg.fetchval("SELECT valid_until FROM assertions WHERE id = $1", aid) is None


@pytest.mark.integration
async def test_dismissed_and_archived_facts_are_never_returned(pg, ranked):
    uid = await make_user(pg)
    await seed_fact(pg, uid, "has_skill", "Dismissed skill", dismissed=True)
    await seed_fact(pg, uid, "has_skill", "Archived skill", archived=True)
    await seed_fact(pg, uid, "has_skill", "Kept skill")
    names = {f["object"] for f in await rank_context(pg, uid, topic=None, k=20)}
    assert names == {"Kept skill"}


@pytest.mark.integration
async def test_wrappers_follow_the_flag(pg, monkeypatch):
    uid = await make_user(pg)
    await seed_fact(pg, uid, "has_skill", "Rust")
    monkeypatch.setattr(settings, "feature_ranked_context", False)
    legacy = await export.active_context(pg, uid, 5)
    assert "section" not in legacy[0]
    monkeypatch.setattr(settings, "feature_ranked_context", True)
    new = await export.active_context(pg, uid, 5)
    assert new[0]["section"] in {"core", "now"}
