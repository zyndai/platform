"""People search Phase 0 (docs/plans/ZYND_PEOPLE_SEARCH_PLAN.md): names, soft topics, grounded LLM
topics, the Zynd floor, and QuickEnrich requests, results and cache."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.mcp_http as m
from app.services import people_discovery as discovery
from app.services import people_query as pq
from app.services import people_results as pr
from app.services import people_search
from app.services.people_query import Intent, detect_intent, parse_target_heuristic


# ── 0.3 intent ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,name,company", [
    ("chandan", "chandan", ""),
    ("Chandan Kumar", "Chandan Kumar", ""),
    ("send a request to chandan from zynd", "chandan", "zynd"),
    ("Can you send a request to Chandan from Zynd?", "Chandan", "Zynd"),
    ("@chandan-kumar-2en8", "chandan-kumar-2en8", ""),
    ("connect me with Priya Sharma", "Priya Sharma", ""),
    ("find John at Stripe", "John", "Stripe"),
    ("who is Sam Altman", "Sam Altman", ""),
    ("people named Rao", "Rao", ""),
])
def test_a_name_is_recognised(text, name, company):
    assert detect_intent(text) == Intent("name", name, company)


@pytest.mark.parametrize("text", [
    "AI", "VC", "fintech", "rust engineer", "seed investor", "investor from India", "someone from Zynd",
    "find me people in Pune", "people building AI agents", "marketing", "founders", "a b c d", "",
    "seed-stage investor who backs AI dev tools in India",
])
def test_a_description_stays_a_target(text):
    assert detect_intent(text).kind == "target"


def test_like_me_is_its_own_intent():
    assert detect_intent("like_me").kind == "like_me" and detect_intent("People like me").kind == "like_me"


# ── 0.1 soft topics ──────────────────────────────────────────────────────────────

def test_topics_are_sent_as_topics_never_as_skills():
    for text in ("chandan", "seed-stage investor who backs AI dev tools in India", "chandan from zynd"):
        params = discovery.cards_search_params(text, 10, parse_target_heuristic(text))
        assert "skills" not in params, text
        assert params["relax"] == "true"
    assert discovery.cards_search_params("x", 10, parse_target_heuristic("chandan"))["topics"] == "chandan"


def test_only_an_explicit_skill_is_required():
    params = discovery.cards_search_params("t", 10, parse_target_heuristic("find me someone who knows Rust"))
    assert params["skills"] == "rust" and params["topics"] == "Rust"
    assert parse_target_heuristic("Rust or Python developer").required_skills == ()
    assert parse_target_heuristic("seed investor AI dev tools").required_skills == ()




# ── 0.4 grounded LLM topics ──────────────────────────────────────────────────────

def test_llm_topics_must_come_from_the_query():
    base = parse_target_heuristic("seed-stage investor who backs AI dev tools in India")
    merged = pq._merge_llm(base, {"role": "investor", "stage": "seed", "location": "India",
                                  "topics": ["technology innovation", "AI dev tools", "software innovation"]})
    assert merged.topics == ("AI dev tools",)


def test_when_every_llm_topic_is_invented_the_heuristic_topics_are_kept():
    base = parse_target_heuristic("seed-stage investor who backs AI dev tools in India")
    merged = pq._merge_llm(base, {"topics": ["technology innovation", "software innovation"]})
    assert merged.topics == base.topics


def test_grounding_is_plural_insensitive():
    assert pq._grounded(["developer tool"], "backs developer tools") == ["developer tool"]


# ── 0.6 QuickEnrich request ──────────────────────────────────────────────────────

def test_the_investor_request_excludes_the_grievance_officers():
    body = discovery.quickenrich_body(parse_target_heuristic("seed-stage investor who backs AI dev tools in India"), 10)
    assert body == {
        "page": 1, "per_page": 10,
        "title": {"include": list(pq.ROLE_TITLE_FILTERS["investor"][0]),
                  "exclude": list(pq.ROLE_TITLE_FILTERS["investor"][1])},
        "bio_li": {"include": ["seed", "AI dev tools"], "exclude": []},
        "country_code": {"include": ["IN"], "exclude": []},
    }
    for word in ("Grievance", "Relations", "Communications"):
        assert word in body["title"]["exclude"]


@pytest.mark.parametrize("role", sorted(pq.ROLES))
def test_every_role_has_title_include_and_exclude(role):
    query = pq.TargetQuery(raw=role, role=role, titles=pq.ROLES[role][1], company_hint=role in pq._COMPANY_ROLES)
    body = discovery.quickenrich_body(query, 5)
    include, exclude = pq.ROLE_TITLE_FILTERS[role]
    assert body["title"] == {"include": list(include), "exclude": list(exclude)}


def test_company_topics_stay_whole_phrases():
    query = pq.TargetQuery(raw="r", role="founder", topics=("developer tools", "AI agents"), company_hint=True)
    assert discovery.company_phrases(query) == ["developer tools", "AI agents"]
    assert discovery.company_phrases(pq.TargetQuery(raw="r", role="investor", company_hint=True, stage="seed")) == [
        "seed", "venture", "capital"]
    assert discovery.company_phrases(pq.TargetQuery(raw="r", topics=("a of data",), company_hint=True)) == ["data"]
    assert discovery.company_phrases(pq.TargetQuery(raw="r", topics=("tools",), company_hint=True)) == []


def test_a_non_company_role_gets_no_bio_keywords():
    body = discovery.quickenrich_body(parse_target_heuristic("rust engineer in Berlin"), 5)
    assert "bio_li" not in body and body["locality"] == {"include": ["Berlin"], "exclude": []}


# ── 0.7 QuickEnrich results ──────────────────────────────────────────────────────

RAW = [
    {"first_name": "Investor", "last_name": "Grievance", "title": "Investor Grievance Officer", "company_name": "Dayco Securities",
     "employee_linkedin": "linkedin.com/in/grievance", "city": "Mumbai", "country_code": "IN"},
    {"first_name": "Asha", "last_name": "Rao", "title": "Angel Investor", "company_name": "Rao Ventures",
     "employee_linkedin": "www.linkedin.com/in/asha", "city": "Bengaluru", "country_code": "IN", "email": "a@b.c",
     "employee_phone": "555", "has_email": True},
    {"first_name": "N/A", "last_name": "N/A", "title": "Partner", "company_name": "N/A"},
    {"first_name": "Tom", "last_name": "Lee", "title": "Venture Partner", "company_name": "Lee Capital",
     "employee_linkedin": "https://linkedin.com/in/tom", "locality": "Austin", "country_code": "US"},
]


def test_shaping_keeps_location_fixes_the_url_and_never_the_contact_values():
    rows = discovery._shape_qe(RAW)
    assert [r["name"] for r in rows] == ["Investor Grievance", "Asha Rao", "Tom Lee"]    # the nameless, URL-less row is gone
    asha = rows[1]
    assert asha["linkedin_url"] == "https://www.linkedin.com/in/asha"
    assert asha["location"] == "Bengaluru, India" and rows[2]["location"] == "Austin, United States"
    assert "a@b.c" not in repr(rows) and "555" not in repr(rows) and asha["has_email"] is True




def test_linkedin_people_are_ranked_by_fit():
    query = parse_target_heuristic("investor in Bengaluru")
    ranked = discovery.rank_quickenrich(discovery._shape_qe(RAW), query)
    assert [r["name"] for r in ranked][0] == "Asha Rao"            # right title and city
    assert all(0.30 <= r["score"] <= 0.55 for r in ranked)
    assert ranked[0]["score"] > ranked[-1]["score"]
    # with no place asked for, only the title decides: the excluded word ranks last
    by_title = discovery.rank_quickenrich(discovery._shape_qe(RAW), parse_target_heuristic("investor"))
    assert [r["name"] for r in by_title] == ["Asha Rao", "Tom Lee", "Investor Grievance"]


def test_person_from_external_uses_the_rank_score_and_location():
    person = pr.person_from_external({"name": "A", "title": "Investor", "company": "X", "linkedin_url": "u",
                                      "location": "Pune, India", "score": 0.5}, 7)
    assert person["score"] == 0.5 and person["location"] == "Pune, India"
    assert pr.person_from_external({"name": "A"}, 2)["score"] == 0.448


# ── 0.8 cache ────────────────────────────────────────────────────────────────────

class FakeHTTP:
    calls = 0

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json, headers):
        FakeHTTP.calls += 1
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"data": RAW}
        return resp


@pytest.fixture
def qe(monkeypatch):
    FakeHTTP.calls = 0
    store = {}
    monkeypatch.setattr(discovery.settings, "quickenrich_base_url", "https://qe.example")
    monkeypatch.setattr(discovery.settings, "quickenrich_api_key", "k")
    monkeypatch.setattr(discovery.httpx, "AsyncClient", FakeHTTP)
    monkeypatch.setattr(discovery, "_cache_get", AsyncMock(side_effect=lambda key: store.get(key)))
    monkeypatch.setattr(discovery, "_cache_set", AsyncMock(side_effect=lambda key, rows: store.__setitem__(key, rows)))
    return store


async def test_an_identical_request_is_served_from_the_cache(qe):
    query = parse_target_heuristic("investor in Bengaluru")
    first, w1 = await discovery.search_quickenrich("investor in Bengaluru", 5, query=query)
    second, w2 = await discovery.search_quickenrich("investor in Bengaluru", 5, query=query)
    assert w1 is None and w2 is None and FakeHTTP.calls == 1 and first == second
    assert "a@b.c" not in repr(qe) and "555" not in repr(qe)       # the cache holds flags, never contact values




# ── 0.3 names in QuickEnrich ─────────────────────────────────────────────────────

def test_name_matching_is_by_word_and_prefix():
    assert discovery.name_matches("chandan", "Chandan Kumar")
    assert discovery.name_matches("kumar chandan", "Chandan Kumar")
    assert discovery.name_matches("chan", "Chandan Kumar") and discovery.name_matches("cha", "Chandan Kumar")
    assert not discovery.name_matches("ch", "Chandan Kumar")           # too short to be a prefix
    assert not discovery.name_matches("priya", "Chandan Kumar") and not discovery.name_matches("", "x")


async def test_a_named_person_at_a_company_is_found_among_the_companys_people(qe):
    rows, warning = await discovery.search_quickenrich_by_name("asha", "Rao Ventures", 5)
    assert warning is None and [r["name"] for r in rows] == ["Asha Rao"]


async def test_name_search_says_so_when_quickenrich_is_not_configured(monkeypatch):
    monkeypatch.setattr(discovery.settings, "quickenrich_base_url", "")
    assert await discovery.search_quickenrich_by_name("a", "b", 5) == ([], "quickenrich_not_configured")


async def test_lookup_cards_calls_the_lookup_endpoint(monkeypatch):
    monkeypatch.setattr(discovery.settings, "cards_api_base_url", "http://cards.test")
    seen = {}

    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params):
            seen.update(url=url, params=params)
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"results": [{"handle": "chandan-kumar-2en8", "claimed": True, "name": "Chandan Kumar",
                                                   "match_score": 0.95, "match_reasons": ["Name match"]}]}
            return resp

    monkeypatch.setattr(discovery.httpx, "AsyncClient", Client)
    rows, warning = await discovery.lookup_cards("chandan", 5)
    assert warning is None and seen["url"] == "http://cards.test/v1/agents/lookup"
    assert seen["params"] == {"name": "chandan", "limit": 5, "include_unclaimed": "true"}
    assert rows[0]["handle"] == "chandan-kumar-2en8" and rows[0]["why"] == ["Name match"]
    assert await discovery.lookup_cards("a", 5) == ([], None)


# ── the whole search ─────────────────────────────────────────────────────────────

def card(handle, score=0.8, **kw):
    return {"source": "zynd_card", "handle": handle, "claimed": kw.pop("claimed", True), "name": kw.pop("name", handle.title()),
            "headline": kw.pop("headline", "Investor"), "location": "Pune", "skills": [], "match_score": score,
            "why": kw.pop("why", ["Matches your search terms"]), "url": f"https://cards.zynd.ai/p/{handle}",
            "linkedin_url": "", "connection_eligible": False, **kw}


@pytest.fixture
def world():
    state = {"cards": ([], None), "lookup": ([], None), "zynd": [], "directory": {}, "external": ([], None),
             "by_name": ([], None), "own": None}

    async def directory(pool, ids):
        out = {i: state["directory"][i] for i in ids if i in state["directory"]}
        if state["own"] and "caller" in ids:
            out["caller"] = state["own"]
        return out

    patches = {
        "pool": patch("app.mcp_http._get_pool", AsyncMock(return_value=MagicMock())),
        "cards": patch("app.services.people_search.people_discovery.search_cards", AsyncMock(side_effect=lambda *a, **k: state["cards"])),
        "lookup": patch("app.services.people_search.people_discovery.lookup_cards", AsyncMock(side_effect=lambda *a, **k: state["lookup"])),
        "zynd_search": patch("app.services.people_search.search_by_query", AsyncMock(side_effect=lambda *a, **k: state["zynd"])),
        "external": patch("app.services.people_search.people_discovery.search_quickenrich", AsyncMock(side_effect=lambda *a, **k: state["external"])),
        "by_name": patch("app.services.people_search.people_discovery.search_quickenrich_by_name", AsyncMock(side_effect=lambda *a, **k: state["by_name"])),
        "directory": patch("app.services.people_search.card_directory.cards_for_users", AsyncMock(side_effect=directory)),
        "prefs": patch("app.services.people_search.cards_network.preferences", AsyncMock(return_value={"ok": True, "preferences": {}})),
        "group": patch("app.services.people_search.cards_network.group_search", AsyncMock(return_value={"ok": True, "results": []})),
    }
    state["mocks"] = {k: p.start() for k, p in patches.items()}
    yield state
    for p in patches.values():
        p.stop()


async def run(target, **kw):
    return await m.find_people(target, uid="caller", **kw)


async def test_a_name_returns_that_person_first_with_no_topic_filter(world):
    world["lookup"] = ([card("chandan-kumar-2en8", 0.95, name="Chandan Kumar", headline="Zynd", why=["Name match"])], None)
    result = await run("chandan")
    assert result["intent"] == "name" and result["parsed"] == {"name": "chandan"}
    (person,) = result["people"]
    assert person["handle"] == "chandan-kumar-2en8" and person["match_quality"] == "close"
    assert "name_needs_company" in " ".join(result["warnings"])       # not an exact full name, no company
    world["mocks"]["cards"].assert_not_called()                       # a name is not run through the topic pipeline
    world["mocks"]["by_name"].assert_not_called()


async def test_a_full_name_is_an_exact_match_and_needs_no_company(world):
    world["lookup"] = ([card("chandan-kumar-2en8", 0.95, name="Chandan Kumar", why=["Name match"])], None)
    result = await run("Chandan Kumar")
    assert result["people"][0]["match_quality"] == "exact" and "warnings" not in result


async def test_several_people_with_the_name_come_with_a_note(world):
    world["lookup"] = ([card("a-rao", 0.9, name="Asha Rao"), card("b-rao", 0.8, name="Bala Rao")], None)
    result = await run("Rao")
    assert len(result["people"]) == 2 and "tell them apart" in result["note"]


async def test_a_company_adds_a_linkedin_search_by_name(world):
    world["lookup"] = ([card("chandan-kumar-2en8", 0.95, name="Chandan Kumar", why=["Name match"])], None)
    world["by_name"] = ([{"name": "Chandan Singh", "title": "Engineer", "company": "Zynd", "linkedin_url":
                          "https://www.linkedin.com/in/cs"}], None)
    result = await run("send a request to chandan from zynd")
    assert result["parsed"] == {"name": "chandan", "company": "zynd"}
    assert [p["name"] for p in result["people"]] == ["Chandan Kumar", "Chandan Singh"]
    assert result["people"][0]["next_action"] == "connect" and result["people"][1]["next_action"] == "view_profile"
    world["mocks"]["by_name"].assert_awaited_once()
    assert "warnings" not in result


async def test_nobody_by_that_name_falls_back_to_the_normal_search(world):
    world["cards"] = ([card("ada", 0.6)], None)
    result = await run("zorblax")
    assert result["intent"] == "target" and [p["handle"] for p in result["people"]] == ["ada"]
    assert "Nobody named" in result["note"] and any("name_needs_company" in w for w in result["warnings"])


async def test_a_description_is_not_looked_up_as_a_name(world):
    world["cards"] = ([card("ada")], None)
    result = await run("seed investor in India")
    assert result["intent"] == "target"
    world["mocks"]["lookup"].assert_not_called()


async def test_the_caller_is_not_found_by_their_own_name(world):
    world["own"] = {"handle": "me", "name": "Me", "headline": "", "location": "", "claimed": True}
    world["lookup"] = ([card("me", 0.95, name="Me"), card("mia", 0.8, name="Mia")], None)
    assert [p["handle"] for p in (await run("Mia"))["people"]] == ["mia"]


# ── 0.5 Zynd floor ───────────────────────────────────────────────────────────────

def zynd(uid, similarity, matched_on=None):
    return {"user_id": uid, "display_name": uid, "similarity": similarity, "matched_on": matched_on or []}


async def test_a_weak_zynd_only_hit_is_dropped_but_kept_when_cards_found_them_too(world):
    world["cards"] = ([card("ada", 0.6)], None)
    world["zynd"] = [zynd("weak", 0.25), zynd("also-in-cards", 0.25), zynd("strong", 0.5)]
    world["directory"] = {
        "weak": {"handle": "wes", "name": "Wes", "headline": "", "location": "", "claimed": True},
        "also-in-cards": {"handle": "ada", "name": "Ada", "headline": "", "location": "", "claimed": True},
        "strong": {"handle": "sue", "name": "Sue", "headline": "", "location": "", "claimed": True}}
    result = await run("seed investor in India", sources="cards,zynd")
    handles = [p["handle"] for p in result["people"]]
    assert "wes" not in handles and "ada" in handles and "sue" in handles
    assert not any("_weak" in p for p in result["people"])


async def test_per_fact_matches_have_a_lower_floor_and_a_real_reason(world):
    world["zynd"] = [zynd("u1", 0.4, ["building AI agents"]), zynd("u2", 0.4)]
    world["directory"] = {
        "u1": {"handle": "uma", "name": "Uma", "headline": "", "location": "", "claimed": True},
        "u2": {"handle": "uli", "name": "Uli", "headline": "", "location": "", "claimed": True}}
    result = await run("seed investor in India", sources="zynd")
    assert [p["handle"] for p in result["people"]] == ["uma"]                # 0.40 clears 0.35, not 0.45
    assert result["people"][0]["why"] == ["Zynd profile · building AI agents"]


async def test_blurry_zynd_hits_never_get_the_generic_reason(world):
    world["zynd"] = [zynd("u2", 0.6)]
    world["directory"] = {"u2": {"handle": "uli", "name": "Uli", "headline": "", "location": "", "claimed": True}}
    assert (await run("seed investor in India", sources="zynd"))["people"][0]["why"] == []


# ── 0.8 early LinkedIn start ─────────────────────────────────────────────────────

LINKEDIN = [{"name": "Asha Rao", "title": "Angel Investor", "company": "Rao Ventures",
             "linkedin_url": "https://www.linkedin.com/in/asha", "score": 0.5}]


async def test_linkedin_starts_early_and_is_used_when_cards_come_up_short(world):
    world["cards"] = ([card("ada", 0.9)], None)
    world["external"] = (LINKEDIN, None)
    result = await run("seed investor who backs AI dev tools in India", k=5)
    assert "quickenrich" in result["searched"] and result["people"][-1]["name"] == "Asha Rao"
    world["mocks"]["external"].assert_awaited_once()


async def test_the_early_linkedin_answer_is_dropped_when_cards_are_enough(world):
    world["cards"] = ([card(f"p{i}", 0.9) for i in range(5)], None)
    world["external"] = (LINKEDIN, None)
    result = await run("seed investor who backs AI dev tools in India", k=5)
    assert "quickenrich" not in result["searched"] and all(p["sources"] == ["card"] for p in result["people"])


# ── group search ─────────────────────────────────────────────────────────────────

async def test_group_search_sends_soft_topics_and_relaxes(world):
    await run("investor who backs AI dev tools in Pune", group_id="g1")
    args, kwargs = world["mocks"]["group"].await_args
    assert args[6] == "" and kwargs == {"topics": "AI dev tools", "relax": True}
