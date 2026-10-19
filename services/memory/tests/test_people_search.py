"""find_people: one list of people from Cards, Zynd members and (as a fallback) LinkedIn."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.mcp_http as m
from app.services import people_results as pr
from app.services import people_search


def card(handle, score=0.8, **kw):
    return {"source": "zynd_card", "handle": handle, "claimed": kw.pop("claimed", True), "name": handle.title(),
            "headline": "Investor", "location": "Pune", "skills": [], "match_score": score,
            "why": ["Matches your search terms"], "url": f"https://cards.zynd.ai/p/{handle}",
            "linkedin_url": kw.pop("linkedin_url", ""), "connection_eligible": False, **kw}


def zynd(uid, similarity=0.7):
    return {"user_id": uid, "display_name": uid, "similarity": similarity, "assertion_count": 6}


@pytest.fixture
def world():
    """Patch every collaborator of the search; tests set what each returns."""
    state = {"cards": ([], None), "zynd": [], "directory": {}, "external": ([], None), "own": None}

    async def directory(pool, ids):
        if state["directory"] is None:        # Cards unreachable
            return None
        out = {i: state["directory"][i] for i in ids if i in state["directory"]}
        if state["own"] and "caller" in ids:
            out["caller"] = state["own"]
        return out

    patches = [
        patch("app.mcp_http._get_pool", AsyncMock(return_value=MagicMock())),
        patch("app.services.people_search.people_discovery.search_cards",
              AsyncMock(side_effect=lambda *a, **k: state["cards"])),
        patch("app.services.people_search.search_by_query", AsyncMock(side_effect=lambda *a, **k: state["zynd"])),
        patch("app.services.people_search.match_users", AsyncMock(side_effect=lambda *a, **k: state["zynd"])),
        patch("app.services.people_search.people_discovery.search_quickenrich",
              AsyncMock(side_effect=lambda *a, **k: state["external"])),
        patch("app.services.people_search.card_directory.cards_for_users", AsyncMock(side_effect=directory)),
        patch("app.services.people_search.active_context", AsyncMock(return_value=[
            {"predicate": "is_building", "object": "AI agents"}, {"predicate": "has_skill", "object": "Python"}])),
    ]
    mocks = [p.start() for p in patches]
    state["mocks"] = dict(zip(["pool", "cards_search", "zynd_search", "match", "external_search", "directory_call", "ctx"], mocks))
    yield state
    for p in patches:
        p.stop()


async def run(target="seed investor in India", **kw):
    return await m.find_people(target, uid=kw.pop("uid", "caller"), **kw)


# ── shape ────────────────────────────────────────────────────────────────────────

async def test_one_list_of_people_with_one_shape(world):
    world["cards"] = ([card("ada", 0.9), card("sam", 0.4, claimed=False)], None)
    result = await run()
    assert set(result) >= {"target", "mode", "parsed", "people", "sources", "searched"}
    assert not {"zynd_users", "cards", "quickenrich"} & set(result)     # the three source lists are gone
    ada, sam = result["people"]
    assert set(ada) == {"handle", "name", "headline", "location", "why", "sources", "claimed", "score",
                        "next_action", "url", "skills", "linkedin_url"}
    assert (ada["handle"], ada["next_action"], ada["claimed"]) == ("ada", "connect", True)
    assert (sam["next_action"], sam["claimed"]) == ("view_profile", False)   # nobody to connect to yet
    assert result["parsed"]["role"] == "investor" and result["parsed"]["country_code"] == "IN"


async def test_results_never_carry_contact_details(world):
    world["cards"] = ([card("ada")], None)
    world["zynd"] = [{**zynd("u1"), "socials": {"linkedin": "https://x"}, "contact": "LinkedIn: https://x"}]
    world["directory"] = {"u1": {"handle": "bo", "name": "Bo", "headline": "VC", "location": "", "claimed": True}}
    blob = repr(await run())
    assert "socials" not in blob and "contact" not in blob and "LinkedIn: https://x" not in blob


# ── F5/F6: one person once, connectable by handle ─────────────────────────────────

async def test_a_zynd_member_and_their_card_are_one_person(world):
    world["cards"] = ([card("ada", 0.6)], None)
    world["zynd"] = [zynd("u1", 0.7)]
    world["directory"] = {"u1": {"handle": "ada", "name": "Ada", "headline": "Investor", "location": "Pune", "claimed": True}}
    result = await run()
    (ada,) = result["people"]
    assert sorted(ada["sources"]) == ["card", "zynd"]
    assert ada["score"] == 0.8                                   # best of the two + the agreement bonus
    assert "Matches their Zynd profile" in ada["why"] and "Matches your search terms" in ada["why"]


async def test_every_zynd_result_is_resolved_to_a_card_handle_or_dropped(world):
    world["zynd"] = [zynd("has-card"), zynd("no-card")]
    world["directory"] = {"has-card": {"handle": "kim", "name": "Kim", "headline": "", "location": "", "claimed": True}}
    result = await run(sources="zynd")
    assert [p["handle"] for p in result["people"]] == ["kim"]
    assert result["people"][0]["next_action"] == "connect"


async def test_a_card_lookup_outage_is_a_warning_not_a_crash(world):
    world["zynd"] = [zynd("u1")]
    world["directory"] = None
    world["cards"] = ([card("ada")], None)
    result = await run()
    assert [p["handle"] for p in result["people"]] == ["ada"]
    assert "cards_unavailable" in result["warnings"]


async def test_the_callers_own_card_is_never_a_result(world):
    world["own"] = {"handle": "me", "name": "Me", "headline": "", "location": "", "claimed": True}
    world["cards"] = ([card("me", 0.95), card("ada", 0.5)], None)
    assert [p["handle"] for p in (await run())["people"]] == ["ada"]


# ── F9: the external fallback ─────────────────────────────────────────────────────

async def test_linkedin_runs_only_when_too_few_strong_matches(world):
    world["cards"] = ([card(f"h{i}", 0.9) for i in range(3)], None)
    result = await run(k=3)
    world["mocks"]["external_search"].assert_not_awaited()
    assert "quickenrich" not in result["searched"]

    world["cards"] = ([card("weak", 0.2)], None)
    world["external"] = ([{"source": "quickenrich", "name": "Grace", "title": "Partner", "company": "Acme Ventures",
                           "linkedin_url": "https://www.linkedin.com/in/grace"}], None)
    result = await run(k=3)
    world["mocks"]["external_search"].assert_awaited_once()
    grace = next(p for p in result["people"] if p["name"] == "Grace")
    assert (grace["handle"], grace["sources"], grace["next_action"]) == (None, ["linkedin"], "view_profile")
    assert grace["headline"] == "Partner at Acme Ventures"


async def test_naming_quickenrich_always_runs_it(world):
    world["cards"] = ([card(f"h{i}", 0.9) for i in range(3)], None)
    result = await run(k=3, sources="cards,quickenrich")
    world["mocks"]["external_search"].assert_awaited_once()
    assert result["searched"] == ["cards", "quickenrich"]


async def test_a_linkedin_result_that_is_already_a_card_is_merged(world):
    world["cards"] = ([card("grace", 0.4, linkedin_url="https://www.linkedin.com/in/grace/")], None)
    world["external"] = ([{"source": "quickenrich", "name": "Grace H", "title": "Partner", "company": "Acme",
                           "linkedin_url": "https://linkedin.com/in/Grace"}], None)
    result = await run(k=5, sources="all")
    (grace,) = result["people"]
    assert grace["handle"] == "grace" and sorted(grace["sources"]) == ["card", "linkedin"]
    assert grace["next_action"] == "connect"


async def test_every_empty_or_failed_source_is_reported(world):
    world["cards"] = ([], "cards_unavailable")
    world["external"] = ([], "quickenrich_not_configured")
    result = await run()
    assert result["people"] == []
    assert set(result["warnings"]) == {"cards_unavailable", "quickenrich_not_configured"}


async def test_other_sources_survive_a_failing_one(world):
    world["mocks"]["zynd_search"].side_effect = RuntimeError("db")
    world["cards"] = ([card("ada")], None)
    result = await run()
    assert [p["handle"] for p in result["people"]] == ["ada"]
    assert "zynd_unavailable" in result["warnings"]


async def test_sources_filter_skips_the_others(world):
    result = await run(sources="zynd")
    world["mocks"]["cards_search"].assert_not_awaited()
    world["mocks"]["external_search"].assert_not_awaited()
    assert result["sources"] == ["zynd"]


# ── like_me ───────────────────────────────────────────────────────────────────────

async def test_like_me_compares_the_callers_own_profile(world):
    world["zynd"] = [zynd("u1", 0.8)]
    world["directory"] = {"u1": {"handle": "twin", "name": "Twin", "headline": "", "location": "", "claimed": True}}
    world["cards"] = ([card("peer", 0.6)], None)
    result = await run("like_me")
    assert result["mode"] == "like_me" and result["compared_with"] == "AI agents, Python"
    world["mocks"]["match"].assert_awaited_once()
    world["mocks"]["zynd_search"].assert_not_awaited()
    world["mocks"]["external_search"].assert_not_awaited()          # no role to search LinkedIn for
    assert {p["handle"] for p in result["people"]} == {"twin", "peer"}


async def test_like_me_without_a_profile_says_so(world):
    world["mocks"]["ctx"].return_value = []
    result = await run("like me")
    assert result["people"] == [] and "no_profile_to_compare" in result["warnings"][0]
    world["mocks"]["cards_search"].assert_not_awaited()


# ── pure merge rules ──────────────────────────────────────────────────────────────

def test_linkedin_key_normalizes_profile_urls():
    assert pr.linkedin_key("https://www.linkedin.com/in/Grace/") == pr.linkedin_key("linkedin.com/in/grace")
    assert pr.linkedin_key("https://example.com/in/grace") == ""
    assert pr.linkedin_key("https://linkedin.com/") == ""
    assert pr.linkedin_key(None) == ""


def test_merge_orders_by_score_then_claimed_and_keeps_external_below_cards():
    people = pr.merge_people([
        pr.person_from_external({"name": "Ext", "linkedin_url": "https://linkedin.com/in/e"}, 0),
        pr.person_from_card(card("low", 0.35)),
        pr.person_from_card(card("high", 0.9)),
    ])
    assert [p["name"] for p in people] == ["High", "Low", "Ext"]


def test_merge_never_invents_a_handle_for_external_people():
    (p,) = pr.merge_people([pr.person_from_external({"name": "X", "linkedin_url": "https://linkedin.com/in/x"}, 0)])
    assert p["handle"] is None and p["next_action"] == "view_profile" and p["url"].endswith("/in/x")


# ── two-way match (A1) ────────────────────────────────────────────────────────────

async def test_the_searchers_own_handle_goes_to_cards_so_two_way_matches_rank_higher(world):
    world["own"] = {"handle": "me", "name": "Me", "headline": "Founder", "location": "", "claimed": True}
    world["cards"] = ([card("investor", 0.7)], None)
    await run()
    assert world["mocks"]["cards_search"].await_args.kwargs["as_handle"] == "me"


async def test_a_searcher_without_a_card_searches_one_way(world):
    world["cards"] = ([card("investor", 0.7)], None)
    await run()
    assert world["mocks"]["cards_search"].await_args.kwargs["as_handle"] == ""
