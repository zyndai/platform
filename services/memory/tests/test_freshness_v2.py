"""Phase 4 — freshness done right: last_seen_at, mention_count, idempotent decay, stale facts kept."""
import pathlib
import re
import uuid

import pytest

from app.config import settings
from app.services import control, decay, job_runs
from app.services.export import rank_context
from app.services.facts import write_fact
from seed import make_user, seed_fact

pytestmark = pytest.mark.integration


@pytest.fixture
def v2(monkeypatch):
    monkeypatch.setattr(settings, "feature_fact_families", True)
    monkeypatch.setattr(settings, "feature_freshness_v2", True)
    monkeypatch.setattr(settings, "feature_ranked_context", True)


async def row(pg, aid):
    return await pg.fetchrow(
        "SELECT confidence, base_confidence, last_seen_at, mention_count, valid_until, version FROM assertions WHERE id = $1", aid)


# ── effective flag ────────────────────────────────────────────────────────────────

def test_v2_needs_the_unified_write_path(monkeypatch):
    monkeypatch.setattr(settings, "feature_freshness_v2", True)
    monkeypatch.setattr(settings, "feature_fact_families", False)
    assert settings.freshness_v2 is False
    monkeypatch.setattr(settings, "feature_fact_families", True)
    assert settings.freshness_v2 is True


# ── decay ─────────────────────────────────────────────────────────────────────────

async def test_decay_recomputes_from_the_base_and_is_idempotent(pg, v2):
    uid = await make_user(pg)
    aid = await seed_fact(pg, uid, "is_learning", "Rust", confidence=0.9, days_ago=30, base=0.9)   # half-life 30d
    await decay.run_decay_job(pg)
    first = await row(pg, aid)
    assert first["confidence"] == pytest.approx(0.45, abs=0.005) and first["base_confidence"] == 0.9
    history = await pg.fetchval("SELECT count(*) FROM assertion_history WHERE assertion_id = $1", aid)

    summary = await decay.run_decay_job(pg)           # again, straight away

    assert summary["decayed"] == 0 and summary["mode"] == "v2"
    assert (await row(pg, aid))["confidence"] == first["confidence"]
    assert await pg.fetchval("SELECT count(*) FROM assertion_history WHERE assertion_id = $1", aid) == history


async def test_the_old_job_over_decays_and_the_new_one_does_not(pg, v2, monkeypatch):
    """is_working_on (14-day half-life), last seen 10 days ago, run nightly for 10 nights.
    Intended: 0.9 x 0.5^(10/14) = 0.55. Legacy compounds it away."""
    uid = await make_user(pg)
    legacy = await seed_fact(pg, uid, "is_working_on", "legacy job", "project_assignment", confidence=0.9, days_ago=10)
    monkeypatch.setattr(settings, "feature_freshness_v2", False)
    for _ in range(10):
        await decay.run_decay_job(pg)
    assert (await row(pg, legacy))["confidence"] < 0.35            # far below the intended 0.55

    uid2 = await make_user(pg)
    fixed = await seed_fact(pg, uid2, "is_working_on", "v2 job", "project_assignment", confidence=0.9, days_ago=10)
    monkeypatch.setattr(settings, "feature_freshness_v2", True)
    for _ in range(10):
        await decay.run_decay_job(pg)
    assert (await row(pg, fixed))["confidence"] == pytest.approx(0.9 * 0.5 ** (10 / 14), abs=0.005)


async def test_time_bound_facts_are_never_archived_by_age(pg, v2):
    uid = await make_user(pg)
    old_work = await seed_fact(pg, uid, "is_working_on", "ancient migration", "project_assignment", confidence=0.9, days_ago=400)
    old_building = await seed_fact(pg, uid, "is_building", "old product", "project_venture", confidence=0.9, days_ago=900)
    await decay.run_decay_job(pg)
    for aid in (old_work, old_building):
        r = await row(pg, aid)
        assert r["valid_until"] is None and r["confidence"] < 0.1       # near zero, but still active


async def test_facts_that_are_not_time_bound_are_still_archived_below_the_threshold(pg, v2):
    uid = await make_user(pg)
    belief = await seed_fact(pg, uid, "believes", "an old opinion", "belief_opinion", confidence=0.9, days_ago=900)   # 90d
    keep = await seed_fact(pg, uid, "believes", "a recent opinion", "belief_opinion", confidence=0.9, days_ago=5)
    summary = await decay.run_decay_job(pg)
    assert (await row(pg, belief))["valid_until"] is not None and (await row(pg, keep))["valid_until"] is None
    assert summary["archived"] == 1


async def test_no_decay_predicates_are_untouched(pg, v2):
    uid = await make_user(pg)
    aid = await seed_fact(pg, uid, "is_located_in", "Pune", "place_physical", confidence=0.9, days_ago=2000)
    await decay.run_decay_job(pg)
    assert (await row(pg, aid))["confidence"] == 0.9


# ── write_fact records the evidence ───────────────────────────────────────────────

async def put(pg, uid, predicate, name, chunk=None, **kw):
    kw.setdefault("confidence", 0.8)
    kw.setdefault("source", "inferred")
    kw.setdefault("source_system", "claude")
    async with pg.acquire() as conn, conn.transaction():
        return await write_fact(conn, uid, predicate, name, entity_type="skill_technical", trace_chunk_id=chunk, **kw)


async def chunk(pg, uid):
    return str(await pg.fetchval(
        "INSERT INTO trace_chunks (user_id, source_system, raw_text, content_hash) VALUES ($1,'claude','t',$2) RETURNING id",
        uid, uuid.uuid4().hex))


async def test_a_new_fact_starts_with_one_mention_and_its_own_base(pg, v2):
    uid = await make_user(pg)
    result = await put(pg, uid, "has_skill", "Rust", await chunk(pg, uid))
    r = await row(pg, result.assertion_id)
    assert r["mention_count"] == 1 and r["base_confidence"] == r["confidence"] and r["last_seen_at"] is not None


async def test_mentions_count_distinct_chunks_not_reprocessing(pg, v2):
    uid = await make_user(pg)
    c1, c2 = await chunk(pg, uid), await chunk(pg, uid)
    aid = (await put(pg, uid, "has_skill", "Rust", c1)).assertion_id
    await put(pg, uid, "has_skill", "Rust", c1)            # the same chunk processed again (a retry)
    assert (await row(pg, aid))["mention_count"] == 1
    await put(pg, uid, "has_skill", "Rust", c2)            # a second, different chunk
    assert (await row(pg, aid))["mention_count"] == 2
    await put(pg, uid, "has_skill", "Rust", c2)
    assert (await row(pg, aid))["mention_count"] == 2


async def test_fresh_evidence_resets_decay_and_moves_the_base(pg, v2):
    uid = await make_user(pg)
    aid = await seed_fact(pg, uid, "has_skill", "Rust", confidence=0.4, days_ago=700, base=0.8)
    before = await row(pg, aid)
    await put(pg, uid, "has_skill", "Rust", await chunk(pg, uid), confidence=0.9)
    after = await row(pg, aid)
    assert after["base_confidence"] > 0.8 and after["confidence"] == after["base_confidence"]
    assert after["last_seen_at"] > before["last_seen_at"]
    await decay.run_decay_job(pg)
    assert (await row(pg, aid))["confidence"] == pytest.approx(after["base_confidence"], abs=0.01)   # seen just now


async def test_a_weaker_report_keeps_the_stronger_fact_current(pg, v2):
    uid = await make_user(pg)
    aid = await seed_fact(pg, uid, "has_expertise_in", "Docker", confidence=0.8, days_ago=300, seen_days_ago=300)
    await put(pg, uid, "uses_tool", "Docker", await chunk(pg, uid))
    r = await row(pg, aid)
    assert r["mention_count"] == 2
    assert (await pg.fetchval("SELECT now() - $1::timestamptz < interval '1 minute'", r["last_seen_at"])) is True


async def test_confirming_a_fact_moves_its_base_so_decay_cannot_undo_it(pg, v2):
    uid = await make_user(pg)
    aid = await seed_fact(pg, uid, "is_learning", "Rust", confidence=0.3, days_ago=20, base=0.5)
    await control.confirm_fact(pg, uid, "is_learning", "Rust")
    await decay.run_decay_job(pg)
    r = await row(pg, aid)
    assert r["base_confidence"] == 0.97 and r["confidence"] == pytest.approx(0.97, abs=0.005)


# ── the plan's "done when" ────────────────────────────────────────────────────────

async def test_a_working_on_fact_last_seen_31_days_ago_is_stale_not_gone(pg, v2):
    uid = await make_user(pg)
    aid = await seed_fact(pg, uid, "is_working_on", "invoice parser", "project_assignment",
                          confidence=0.9, days_ago=31, seen_days_ago=31)
    await decay.run_decay_job(pg)

    default = await rank_context(pg, uid, topic=None, k=20)
    related = await rank_context(pg, uid, topic="invoice parser", k=20)

    assert "invoice parser" not in {f["object"] for f in default}
    hit = next(f for f in related if f["object"] == "invoice parser")
    assert hit["stale"] is True and hit["section"] == "related"
    assert (await row(pg, aid))["valid_until"] is None


async def test_ranking_counts_staleness_from_last_seen_not_first_observed(pg, v2):
    uid = await make_user(pg)
    await seed_fact(pg, uid, "is_working_on", "revived work", "project_assignment", confidence=0.9,
                    days_ago=200, seen_days_ago=2)                  # first noted long ago, seen two days ago
    names = {f["object"] for f in await rank_context(pg, uid, topic=None, k=20)}
    assert "revived work" in names


async def test_inferred_skill_needs_two_distinct_chunks_before_it_is_visible(pg, v2, monkeypatch):
    monkeypatch.setattr(settings, "feature_strict_tech", True)
    uid = await make_user(pg)
    c1, c2 = await chunk(pg, uid), await chunk(pg, uid)
    await put(pg, uid, "has_skill", "Webpack", c1, confidence=0.7)
    await put(pg, uid, "has_skill", "Webpack", c1, confidence=0.7)            # retry of the same chunk
    assert "Webpack" not in {f["object"] for f in await rank_context(pg, uid, topic=None, k=20)}
    await put(pg, uid, "has_skill", "Webpack", c2, confidence=0.7)
    assert "Webpack" in {f["object"] for f in await rank_context(pg, uid, topic=None, k=20)}


# ── is the decay job running? ─────────────────────────────────────────────────────

async def test_job_runs_report_when_decay_last_ran(pg):
    assert (await job_runs.status(pg, "decay", 48)) == {"last_run_at": None, "age_hours": None, "ok": False}
    await job_runs.record(pg, "decay", {"decayed": 3})
    fresh = await job_runs.status(pg, "decay", 48)
    assert fresh["ok"] is True and fresh["age_hours"] < 0.1
    await pg.execute("UPDATE job_runs SET last_run_at = now() - interval '49 hours' WHERE job = 'decay'")
    assert (await job_runs.status(pg, "decay", 48))["ok"] is False


async def test_the_worker_job_records_its_run(pg, v2):
    from app import worker
    await worker.decay_cron({})
    assert (await job_runs.status(pg, "decay", 48))["ok"] is True


# ── the migration is safe to apply to a live table ────────────────────────────────

SCHEMA = pathlib.Path(__file__).resolve().parents[1] / "sql" / "schema.sql"


def phase4_block() -> str:
    text = SCHEMA.read_text()
    start = text.index("-- Freshness v2")
    return text[start:]


async def test_schema_change_is_expand_only_backfills_and_is_idempotent(pg):
    """Rehearse the migration on a table shaped like production's before Phase 4."""
    await pg.execute("DROP SCHEMA IF EXISTS rehearsal CASCADE; CREATE SCHEMA rehearsal")
    async with pg.acquire() as conn:
        await conn.execute("SET search_path = rehearsal")
        await conn.execute("""CREATE TABLE assertions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL,
            predicate text NOT NULL, confidence double precision NOT NULL,
            observed_at timestamptz, extracted_at timestamptz NOT NULL DEFAULT now(), valid_until timestamptz)""")
        user = uuid.uuid4()
        await conn.execute(
            """INSERT INTO assertions (user_id, predicate, confidence, observed_at, extracted_at, valid_until) VALUES
               ($1,'is_working_on',0.5, now() - interval '40 days', now() - interval '50 days', NULL),
               ($1,'has_skill',0.7, NULL, now() - interval '9 days', NULL),
               ($1,'believes',0.2, now() - interval '5 days', now() - interval '6 days', now() - interval '1 day')""", user)
        before = await conn.fetch("SELECT id, user_id, predicate, confidence, observed_at, extracted_at, valid_until FROM assertions ORDER BY predicate")

        await conn.execute(phase4_block())
        await conn.execute(phase4_block())        # a second deploy applies it again

        after = await conn.fetch(
            "SELECT id, user_id, predicate, confidence, observed_at, extracted_at, valid_until, last_seen_at, mention_count, base_confidence "
            "FROM assertions ORDER BY predicate")
        assert [tuple(r)[:7] for r in after] == [tuple(r) for r in before]          # nothing existing was changed
        by = {r["predicate"]: r for r in after}
        assert by["is_working_on"]["last_seen_at"] == by["is_working_on"]["observed_at"]
        assert by["has_skill"]["last_seen_at"] == by["has_skill"]["extracted_at"]   # no observed_at: fall back
        assert all(r["mention_count"] == 1 and r["base_confidence"] == r["confidence"] for r in after)
        assert await conn.fetchval("SELECT count(*) FROM pg_indexes WHERE schemaname='rehearsal' AND indexname='assertions_user_active_seen'") == 1
        assert await conn.fetchval("SELECT count(*) FROM job_runs") == 0
        await conn.execute("RESET search_path")
    await pg.execute("DROP SCHEMA rehearsal CASCADE")


def test_the_migration_block_has_no_destructive_statement():
    block = phase4_block().upper()
    code = "\n".join(line for line in block.splitlines() if not line.strip().startswith("--"))
    for forbidden in ("DROP ", "DELETE ", "TRUNCATE", "ALTER COLUMN", "RENAME"):
        assert forbidden not in code, forbidden
    assert re.search(r"ADD COLUMN IF NOT EXISTS LAST_SEEN_AT", code)


# ── /health ───────────────────────────────────────────────────────────────────────

async def test_health_is_unchanged_when_v2_is_off(client):
    assert (await client.get("/health")).json() == {"status": "ok"}


async def test_health_says_whether_decay_has_run(client, v2):
    from app.db import get_pool
    await get_pool().execute("DELETE FROM job_runs WHERE job = 'decay'")
    body = (await client.get("/health")).json()
    assert body["status"] == "ok"                              # still 200 for monitors
    assert body["decay"]["ok"] is False and "decay has not run" in body["warnings"][0]

    await job_runs.record(get_pool(), "decay", {})
    body = (await client.get("/health")).json()
    assert body["decay"]["ok"] is True and "warnings" not in body
