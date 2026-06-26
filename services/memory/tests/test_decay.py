import pytest

from app.config import settings
from app.db import get_pool
from app.services.decay import apply_decay, parse_halflife_days, run_decay_job, run_orphan_cleanup


# ---- Unit ----

def test_parse_halflife_days():
    assert parse_halflife_days("exponential(halflife=30d)") == 30
    assert parse_halflife_days("none") is None
    assert parse_halflife_days("garbage") is None


@pytest.mark.parametrize("conf,halflife,days,expected", [
    (0.8, 30, 0, 0.8),     # no time elapsed -> unchanged
    (0.8, 30, 30, 0.4),    # one half-life -> halved
    (0.8, 30, 60, 0.2),    # two half-lives -> quartered
    (0.8, 14, 7, 0.5657),  # half a half-life
])
def test_apply_decay(conf, halflife, days, expected):
    assert apply_decay(conf, halflife, days) == pytest.approx(expected, abs=1e-4)


# ---- Integration ----

pytest_integration = pytest.mark.integration


async def _dev_uid() -> str:
    return await get_pool().fetchval("SELECT id FROM users WHERE email = $1", settings.dev_user_email)


async def _insert_assertion(uid, predicate, decay_fn, confidence, days_ago, name, etype):
    pool = get_pool()
    eid = await pool.fetchval(
        "INSERT INTO entities (user_id, canonical_name, entity_type) VALUES ($1,$2,$3) RETURNING id",
        uid, name, etype,
    )
    aid = await pool.fetchval(
        """INSERT INTO assertions
             (user_id, predicate, object_entity_id, confidence, source_system, decay_fn, observed_at)
           VALUES ($1,$2,$3,$4,'chatgpt',$5, now() - ($6 * interval '1 day'))
           RETURNING id""",
        uid, predicate, eid, confidence, decay_fn, days_ago,
    )
    return aid, eid


@pytest_integration
async def test_transient_fades_faster_than_stable(client):
    # The M4 exit criterion: after 7 days, is_working_on (14d half-life) is
    # measurably lower than is_affiliated_with (no decay).
    pool = get_pool()
    uid = await _dev_uid()
    work_id, _ = await _insert_assertion(uid, "is_working_on", "exponential(halflife=14d)", 0.8, 7, "API rate limit fix", "project_assignment")
    aff_id, _ = await _insert_assertion(uid, "is_affiliated_with", "none", 0.8, 7, "YC W25", "place_institutional")

    result = await run_decay_job(pool)

    work = await pool.fetchval("SELECT confidence FROM assertions WHERE id=$1", work_id)
    aff = await pool.fetchval("SELECT confidence FROM assertions WHERE id=$1", aff_id)
    assert work == pytest.approx(0.8 * 0.5 ** (7 / 14), abs=1e-3)  # ~0.5657
    assert aff == pytest.approx(0.8)  # no-decay predicate untouched
    assert work < aff
    assert result["decayed"] >= 1

    assert await pool.fetchval(
        "SELECT count(*) FROM assertion_history WHERE assertion_id=$1 AND change_reason='decay'", work_id) == 1
    assert await pool.fetchval(
        "SELECT count(*) FROM assertion_history WHERE assertion_id=$1 AND change_reason='decay'", aff_id) == 0


@pytest_integration
async def test_low_confidence_is_archived_not_deleted(client):
    pool = get_pool()
    uid = await _dev_uid()
    aid, _ = await _insert_assertion(uid, "is_seeking", "exponential(halflife=7d)", 0.12, 30, "backend co-founder", "collaborator")

    await run_decay_job(pool)

    row = await pool.fetchrow("SELECT confidence, valid_until FROM assertions WHERE id=$1", aid)
    assert row is not None                 # row still exists (never deleted)
    assert row["valid_until"] is not None  # archived
    assert row["confidence"] < 0.1
    assert await pool.fetchval(
        "SELECT count(*) FROM assertion_history WHERE assertion_id=$1 AND change_reason='decay'", aid) == 1


@pytest_integration
async def test_fresh_assertion_not_rewritten(client):
    pool = get_pool()
    uid = await _dev_uid()
    aid, _ = await _insert_assertion(uid, "is_learning", "exponential(halflife=30d)", 0.8, 0, "Rust", "skill_technical")

    await run_decay_job(pool)

    # days_elapsed ~ 0 -> no measurable decay -> no write, no history noise.
    assert await pool.fetchval("SELECT count(*) FROM assertion_history WHERE assertion_id=$1", aid) == 0


@pytest_integration
async def test_orphan_cleanup_removes_unreferenced_entities(client):
    pool = get_pool()
    uid = await _dev_uid()
    orphan_id = await pool.fetchval(
        "INSERT INTO entities (user_id, canonical_name, entity_type) VALUES ($1,'lonely concept','concept_topic') RETURNING id", uid)
    _, ref_eid = await _insert_assertion(uid, "is_learning", "exponential(halflife=30d)", 0.8, 0, "Referenced", "skill_technical")

    result = await run_orphan_cleanup(pool)

    assert result["entities_deleted"] >= 1
    assert await pool.fetchval("SELECT count(*) FROM entities WHERE id=$1", orphan_id) == 0
    assert await pool.fetchval("SELECT count(*) FROM entities WHERE id=$1", ref_eid) == 1  # referenced kept
