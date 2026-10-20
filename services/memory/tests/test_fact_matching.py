"""F4 — match a target against individual public facts, not one averaged profile vector."""
import pytest

from app.config import settings
from app.services import matching
from app.services.matching import score_people, search_aspects, search_by_query
from app.services.people_query import parse_target_heuristic
from seed import make_user, seed_fact


def fact(predicate, sims, confidence=0.9, name="x"):
    return {"predicate": predicate, "name": name, "confidence": confidence, "sims": sims}


# ── pure scoring ──────────────────────────────────────────────────────────────────

def test_aspects_cover_the_whole_target_then_its_parts_without_repeats():
    q = parse_target_heuristic("seed-stage investor who backs AI dev tools in India")
    aspects = search_aspects("seed-stage investor who backs AI dev tools in India", q)
    assert aspects == ["seed-stage investor who backs AI dev tools in India", "investor", "AI dev tools", "India"]
    assert search_aspects("  rust  ") == ["rust"] and search_aspects("") == []
    many = parse_target_heuristic("designer for climate, fintech, health and gaming in Pune")
    assert len(search_aspects("x", many)) <= matching.MAX_ASPECTS


def test_current_state_facts_outweigh_tools_and_old_learning():
    ranked = score_people({
        "tool-user": [fact("uses_tool", {0: 0.9})],
        "learner": [fact("is_learning", {0: 0.9})],
        "builder": [fact("is_building", {0: 0.9})],
        "employer": [fact("is_affiliated_with", {0: 0.9})],
    }, 1)
    order = [u for u, _, _ in ranked]
    assert set(order[:2]) == {"employer", "builder"}          # equal weight: either may lead
    assert order[2:] == ["learner", "tool-user"]


def test_best_three_facts_count_and_a_single_fact_is_discounted():
    ranked = dict((u, s) for u, s, _ in score_people({
        "three": [fact("is_building", {0: 0.8}), fact("has_expertise_in", {0: 0.8}), fact("is_working_on", {0: 0.8})],
        "one": [fact("is_building", {0: 0.8})],
        "one-plus-noise": [fact("is_building", {0: 0.8})] + [fact("is_learning", {0: 0.1}) for _ in range(20)],
    }, 1))
    assert ranked["three"] > ranked["one"]
    assert ranked["one"] == ranked["one-plus-noise"]          # unrelated facts neither help nor hurt


def test_covering_more_of_the_target_scores_higher():
    ranked = dict((u, s) for u, s, _ in score_people({
        "fits-all": [fact("is_affiliated_with", {0: 0.8, 1: 0.8}), fact("is_building", {2: 0.8})],
        "fits-one": [fact("is_affiliated_with", {0: 0.8}), fact("is_building", {0: 0.8})],
    }, 3))
    assert ranked["fits-all"] > ranked["fits-one"]


def test_facts_under_the_relatedness_floor_do_not_count_and_scores_are_bounded():
    assert score_people({"u": [fact("is_building", {0: 0.2})]}, 1) == []
    (_, score, _), = score_people({"u": [fact("is_building", {0: 1.0})] * 3}, 1)
    assert 0 < score <= 1.0
    assert score_people({}, 1) == []


def test_low_confidence_facts_count_for_less():
    ranked = dict((u, s) for u, s, _ in score_people({
        "sure": [fact("is_building", {0: 0.8}, confidence=0.95)],
        "unsure": [fact("is_building", {0: 0.8}, confidence=0.35)],
    }, 1))
    assert ranked["sure"] > ranked["unsure"]


# ── against Postgres ──────────────────────────────────────────────────────────────

pytestmark_db = pytest.mark.integration


async def public(pg, uid, predicate, name, etype="skill_domain"):
    await seed_fact(pg, uid, predicate, name, etype, approved=True)


@pytest.fixture
def per_fact(monkeypatch):
    monkeypatch.setattr(settings, "feature_fact_matching", True)
    # names come from Cards in production; here nobody has one, so keep the real display names
    async def keep(pool, results):
        return results
    monkeypatch.setattr(matching, "_enrich_and_dedup", keep)


@pytest.mark.integration
async def test_the_person_whose_facts_fit_the_target_ranks_first(pg, per_fact):
    caller, fund, game, nobody = [await make_user(pg) for _ in range(4)]
    await public(pg, fund, "is_affiliated_with", "Aurora Ventures", "place_institutional")
    await public(pg, fund, "is_building", "developer tools investing thesis", "project_venture")
    await public(pg, fund, "has_expertise_in", "AI developer tools")
    await public(pg, game, "is_building", "indie game engine", "project_venture")
    await public(pg, game, "has_expertise_in", "game design")
    await public(pg, nobody, "has_expertise_in", "bookkeeping")
    q = parse_target_heuristic("investor in AI developer tools")

    rows = await search_by_query(pg, caller, "investor in AI developer tools", query=q)

    assert [r["user_id"] for r in rows] == [fund]
    assert any("AI developer tools" in m for m in rows[0]["matched_on"])


@pytest.mark.integration
async def test_two_interests_stay_distinct_instead_of_blurring_into_one_vector(pg, per_fact):
    caller, hybrid = await make_user(pg), await make_user(pg)
    await public(pg, hybrid, "has_expertise_in", "venture capital")
    await public(pg, hybrid, "is_building", "indie game engine", "project_venture")
    for target in ("venture capital", "indie game engine"):
        rows = await search_by_query(pg, caller, target)
        assert [r["user_id"] for r in rows] == [hybrid], target       # each interest finds them on its own


@pytest.mark.integration
async def test_private_facts_never_match_and_the_caller_never_finds_themselves(pg, per_fact):
    caller, other = await make_user(pg), await make_user(pg)
    await public(pg, caller, "is_building", "AI developer tools", "project_venture")
    await seed_fact(pg, other, "is_building", "AI developer tools", "project_venture")      # not approved
    assert await search_by_query(pg, caller, "AI developer tools") == []


@pytest.mark.integration
async def test_archived_and_dismissed_public_facts_do_not_match(pg, per_fact):
    caller, other = await make_user(pg), await make_user(pg)
    await seed_fact(pg, other, "is_building", "AI developer tools", "project_venture", approved=True, archived=True)
    assert await search_by_query(pg, caller, "AI developer tools") == []


@pytest.mark.integration
async def test_results_keep_the_legacy_row_shape(pg, per_fact):
    caller, other = await make_user(pg), await make_user(pg)
    await public(pg, other, "has_expertise_in", "AI developer tools")
    (row,) = await search_by_query(pg, caller, "AI developer tools")
    assert {"user_id", "display_name", "similarity", "assertion_count"} <= set(row)
    assert 0 < row["similarity"] <= 1 and row["assertion_count"] == 1
    assert "socials" not in row and "contact" not in row


@pytest.mark.integration
async def test_flag_off_still_uses_the_cluster_vector_path(pg, monkeypatch):
    monkeypatch.setattr(settings, "feature_fact_matching", False)
    caller = await make_user(pg)
    assert await search_by_query(pg, caller, "anything at all") == []        # no user_embeddings rows
