"""A3 saved searches, A4 digest, A5 brief, A6 trust, A7 group search, A8 match controls."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import config
from models.card import AgentProfileCard
from services import connection_brief, digest_network, match_prefs, network, saved_searches, trust
from services import search as search_service
from tests.fake_supabase import FakeSupabase

ME, ANN, BOB, CY = (f"00000000-0000-0000-0000-00000000000{i}" for i in (1, 2, 3, 4))
NOW = datetime.now(timezone.utc)


def fact(pred, obj, days_ago=1):
    return {"predicate": pred, "object": obj, "source": "declared", "confidence": 0.9,
            "approved_at": (NOW - timedelta(days=days_ago)).isoformat()}


def row(card_id, handle, user, name="", headline="", *, claimed=True, memory=(), **fields):
    card = AgentProfileCard(id=card_id, status="published", handle=handle,
                            identity={"name": name or handle.title(), "headline": headline, "avatar_url": "", "links": {}},
                            zynd_memory=list(memory), **fields)
    return {"id": card_id, "handle": handle, "status": "published", "owner_user_id": user,
            "owner_email": f"{handle}@example.com" if claimed else None, "card": card.model_dump(mode="json")}


@pytest.fixture
def world(monkeypatch):
    sb = FakeSupabase(agent_profile_cards=[
        row("c-me", "me", ME, headline="Founder building AI agents", connect_with=["Investors"]),
        row("c-ann", "ann", ANN, headline="Seed investor", connect_with=["Founders"]),
        row("c-bob", "bob", BOB, headline="Backend engineer"),
        row("c-cy", "cy", CY, headline="Designer"),
    ])
    monkeypatch.setattr(network, "_sb", lambda: sb)
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    monkeypatch.setattr(config, "FEATURE_NETWORK_CONTROLS", True)
    monkeypatch.setattr(search_service, "embed_text", lambda q: [])          # no embedding service in tests
    return sb


def connect(sb, a, b, status="accepted", a_card=None, b_card=None):
    cards = {ME: "c-me", ANN: "c-ann", BOB: "c-bob", CY: "c-cy"}
    return sb.new_row("connections", {"connection_key": ":".join(sorted((a, b))), "requester_user_id": a,
                                      "requester_card_id": a_card or cards[a], "recipient_user_id": b,
                                      "recipient_card_id": b_card or cards[b], "status": status})


# ── A6: request limits ────────────────────────────────────────────────────────────

def test_a_person_can_only_send_so_many_requests_a_week(world):
    for i in range(trust.MAX_REQUESTS_PER_WEEK):
        world.new_row("connections", {"connection_key": f"k{i}", "requester_user_id": ME, "requester_card_id": "c-me",
                                      "recipient_user_id": f"x{i}", "recipient_card_id": f"cx{i}"})
    with pytest.raises(HTTPException) as err:
        network.request_connection(ME, "ann")
    assert err.value.status_code == 429


def test_old_requests_do_not_count_against_the_week(world):
    for i in range(trust.MAX_REQUESTS_PER_WEEK):
        r = world.new_row("connections", {"connection_key": f"k{i}", "requester_user_id": ME, "requester_card_id": "c-me",
                                          "recipient_user_id": f"x{i}", "recipient_card_id": f"cx{i}"})
        r["created_at"] = (NOW - timedelta(days=8)).isoformat()
    assert network.request_connection(ME, "ann")["existing"] is False


def test_someone_buried_in_requests_cannot_be_sent_more(world):
    for i in range(trust.MAX_PENDING_INCOMING):
        world.new_row("connections", {"connection_key": f"p{i}", "requester_user_id": f"x{i}", "requester_card_id": f"cx{i}",
                                      "recipient_user_id": ANN, "recipient_card_id": "c-ann", "status": "pending"})
    with pytest.raises(HTTPException) as err:
        network.request_connection(ME, "ann")
    assert err.value.status_code == 409


def test_repeating_a_request_is_never_rate_limited(world):
    first = network.request_connection(ME, "ann")
    for i in range(trust.MAX_REQUESTS_PER_WEEK):
        world.new_row("connections", {"connection_key": f"k{i}", "requester_user_id": ME, "requester_card_id": "c-me",
                                      "recipient_user_id": f"x{i}", "recipient_card_id": f"cx{i}"})
    again = network.request_connection(ME, "ann")
    assert again["existing"] is True and again["connection"]["id"] == first["connection"]["id"]


def test_limits_are_off_without_the_flag(world, monkeypatch):
    monkeypatch.setattr(config, "FEATURE_NETWORK_CONTROLS", False)
    for i in range(trust.MAX_REQUESTS_PER_WEEK + 5):
        world.new_row("connections", {"connection_key": f"k{i}", "requester_user_id": ME, "requester_card_id": "c-me",
                                      "recipient_user_id": f"x{i}", "recipient_card_id": f"cx{i}"})
    assert network.request_connection(ME, "ann")["existing"] is False


# ── A6: report, block, verification ───────────────────────────────────────────────

def test_reporting_a_card_is_stored_for_review_and_changes_nothing_else(world):
    out = trust.report_card(ME, "bob", "spam", "  sends the same pitch   to everyone ")
    assert out == {"reported": True, "handle": "bob", "already_reported": False}
    (report,) = world.rows("card_reports")
    assert (report["reporter_user_id"], report["target_card_id"], report["reason"], report["status"]) == (ME, "c-bob", "spam", "open")
    assert report["details"] == "sends the same pitch to everyone"
    assert world.rows("agent_profile_cards")[2]["status"] == "published"            # nothing automatic happens


def test_reporting_validates_and_does_not_duplicate_or_flood(world):
    with pytest.raises(HTTPException) as err:
        trust.report_card(ME, "bob", "because")
    assert err.value.status_code == 422
    with pytest.raises(HTTPException):
        trust.report_card(ME, "me", "spam")                                          # not your own
    with pytest.raises(HTTPException) as err:
        trust.report_card(ME, "nobody", "spam")
    assert err.value.status_code == 404
    trust.report_card(ME, "bob", "spam")
    assert trust.report_card(ME, "bob", "spam")["already_reported"] is True and len(world.rows("card_reports")) == 1
    for i in range(trust.MAX_REPORTS_PER_DAY):
        world.new_row("card_reports", {"reporter_user_id": ME, "target_card_id": f"t{i}", "reason": "spam"})
    with pytest.raises(HTTPException) as err:
        trust.report_card(ME, "cy", "spam")
    assert err.value.status_code == 429


def test_blocking_a_stranger_blocks_the_pair_and_hides_them(world):
    assert trust.block_card(ME, "bob") == {"blocked": True, "handle": "bob"}
    (conn,) = world.rows("connections")
    assert conn["status"] == "blocked" and conn["decided_at"]
    with pytest.raises(HTTPException):
        trust.block_card(ME, "me")
    assert match_prefs.get(ME)["hide_person"] == ["bob"]
    # the blocked person's own request now returns the blocked row instead of a new pending one
    assert network.request_connection(BOB, "me")["connection"]["status"] == "blocked"


def test_blocking_an_accepted_connection_ends_it(world):
    connect(world, ME, ANN)
    trust.block_card(ME, "ann")
    assert [c["status"] for c in world.rows("connections")] == ["blocked"]


def test_verifications_are_recorded_once_and_read_back_in_bulk(world):
    trust.record_verification("c-ann", "linkedin")
    trust.record_verification("c-ann", "linkedin")
    trust.record_verification("c-bob", "github")
    assert len(world.rows("card_verifications")) == 2
    assert trust.verified_by_card_ids(["c-ann", "c-bob", "c-cy"]) == {"c-ann": ["linkedin"], "c-bob": ["github"]}


def test_verification_cannot_be_set_through_the_card_json(world):
    card = AgentProfileCard.model_validate({"id": "x", "verified": {"linkedin": "2026-01-01"}, "identity": {"links": {}}})
    assert not hasattr(card, "verified")                         # the owner-editable model has no such field
    assert trust.verified_by_card_ids(["x"]) == {}


def test_the_trust_features_are_off_without_the_flag(world, monkeypatch):
    monkeypatch.setattr(config, "FEATURE_NETWORK_CONTROLS", False)
    for call in (lambda: trust.report_card(ME, "bob", "spam"), lambda: trust.block_card(ME, "bob"),
                 lambda: match_prefs.add(ME, "mute_topic", "crypto"), lambda: saved_searches.list_searches(ME)):
        with pytest.raises(HTTPException) as err:
            call()
        assert err.value.status_code == 404
    trust.record_verification("c-ann", "linkedin")
    assert not world.rows("card_verifications") and trust.verified_by_card_ids(["c-ann"]) == {}
    assert match_prefs.get(ME) == {"hide_person": [], "mute_topic": [], "less_like_this": []}


# ── A8: match preferences ─────────────────────────────────────────────────────────

def test_preferences_are_normalized_stored_once_and_listed(world):
    assert match_prefs.add(ME, "hide_person", "@Bob") == {"kind": "hide_person", "value": "bob"}
    match_prefs.add(ME, "hide_person", "bob")
    assert match_prefs.add(ME, "mute_topic", "  Crypto!! Trading ") == {"kind": "mute_topic", "value": "crypto trading"}
    match_prefs.add(ME, "less_like_this", "cy")
    assert match_prefs.get(ME) == {"hide_person": ["bob"], "mute_topic": ["crypto trading"], "less_like_this": ["cy"]}
    assert match_prefs.get(ANN)["hide_person"] == []                                 # per user


def test_preferences_reject_bad_input_and_unknown_cards(world):
    for kind, value, code in (("shrug", "x", 422), ("mute_topic", "   ", 422), ("hide_person", "nobody", 404)):
        with pytest.raises(HTTPException) as err:
            match_prefs.add(ME, kind, value)
        assert err.value.status_code == code


def test_a_preference_can_be_removed_and_removing_twice_is_a_404(world):
    match_prefs.add(ME, "mute_topic", "crypto")
    assert match_prefs.remove(ME, "mute_topic", "Crypto")["removed"] is True
    with pytest.raises(HTTPException):
        match_prefs.remove(ME, "mute_topic", "crypto")
    assert match_prefs.get(ME)["mute_topic"] == []


def test_the_preference_list_is_capped(world, monkeypatch):
    monkeypatch.setattr(match_prefs, "MAX_PER_USER", 2)
    match_prefs.add(ME, "mute_topic", "a1")
    match_prefs.add(ME, "mute_topic", "a2")
    with pytest.raises(HTTPException) as err:
        match_prefs.add(ME, "mute_topic", "a3")
    assert err.value.status_code == 409


def test_less_like_this_ranks_similar_people_lower(monkeypatch):
    from unittest.mock import MagicMock
    sb = MagicMock()
    sb.rpc.side_effect = RuntimeError("no rpc")
    monkeypatch.setattr(search_service.config, "get_supabase", lambda: sb)
    monkeypatch.setattr(search_service, "embed_text", lambda q: [])
    skills = [{"name": "Rust"}]
    rows = [row("c-a", "alike", "u1", headline="Backend engineer", skills=skills),
            row("c-b", "other", "u2", headline="Backend engineer", skills=[{"name": "Go"}])]
    monkeypatch.setattr(search_service.cards_service, "list_published_rows", lambda **kw: rows)
    disliked = AgentProfileCard.model_validate({**row("c-d", "disliked", "u3", headline="Backend engineer", skills=skills)["card"]})
    disliked.handle = "disliked"
    plain = {r["handle"]: r["match_score"] for r in search_service.search_agents(q="backend engineer", role="engineer", include_unclaimed=True)}
    tuned = {r["handle"]: r for r in search_service.search_agents(q="backend engineer", role="engineer", include_unclaimed=True, less_like=[disliked])}
    assert plain["alike"] == plain["other"] and tuned["other"]["match_score"] == plain["other"]
    assert tuned["alike"]["match_score"] < tuned["other"]["match_score"]
    assert "Similar to people you asked to see less of" in tuned["alike"]["match_reasons"]


# ── A3: saved searches ────────────────────────────────────────────────────────────

class Matches:
    """Controls what the saved-search runner's search returns."""
    def __init__(self, monkeypatch):
        self.results = []
        monkeypatch.setattr(search_service, "search_agents", lambda *a, **k: list(self.results))


def hit(handle, score=0.8, name=None):
    return {"handle": handle, "name": name or handle.title(), "match_score": score}


@pytest.fixture
def matches(monkeypatch):
    return Matches(monkeypatch)


def test_a_new_search_does_not_report_what_already_matched(world, matches):
    matches.results = [hit("ann"), hit("bob", 0.3)]
    out = saved_searches.add(ME, q="seed investor", role="investor", label="Seed investors")
    assert out["created"] is True and out["already_matching"] == 1
    assert world.rows("saved_searches")[0]["seen_handles"] == ["ann"]               # strong matches only
    assert saved_searches.run_all()["nudges"] == 0


def test_new_strong_matches_become_nudges_once(world, matches):
    saved_searches.add(ME, q="seed investor", label="Seed investors")
    matches.results = [hit("ann", 0.9, "Ann Lee"), hit("bob", 0.2)]
    stats = saved_searches.run_all()
    assert stats == {"searches": 1, "notified": 1, "nudges": 1, "failed": 0, "enabled": True}
    (nudge,) = world.rows("card_nudges")
    assert nudge["owner_email"] == "me@example.com" and nudge["kind"] == "saved_search" and nudge["href"] == "/p/ann"
    assert "Seed investors" in nudge["title"] and "Ann Lee" in nudge["title"]
    assert saved_searches.run_all()["nudges"] == 0                                    # already told
    assert len(world.rows("card_nudges")) == 1


def test_your_own_card_and_hidden_people_are_not_news(world, matches):
    saved_searches.add(ME, q="anyone", label="x")
    match_prefs.add(ME, "hide_person", "bob")
    matches.results = [hit("me"), hit("bob"), hit("cy")]
    saved_searches.run_all()
    assert [n["href"] for n in world.rows("card_nudges")] == ["/p/cy"]


def test_a_run_notifies_at_most_a_few_people_but_remembers_all(world, matches):
    saved_searches.add(ME, q="anyone")
    matches.results = [hit(f"h{i}") for i in range(7)]
    stats = saved_searches.run_all()
    assert stats["nudges"] == saved_searches.MAX_NOTIFY_PER_SEARCH
    assert len(world.rows("saved_searches")[0]["seen_handles"]) == 7


def test_saving_the_same_search_twice_is_idempotent_and_the_list_is_capped(world, matches, monkeypatch):
    first = saved_searches.add(ME, q="Seed  Investor", role="Investor")
    second = saved_searches.add(ME, q="seed investor", role="investor")
    assert second["created"] is False and second["search"]["id"] == first["search"]["id"]
    monkeypatch.setattr(saved_searches, "MAX_PER_USER", 2)
    saved_searches.add(ME, q="designers")
    with pytest.raises(HTTPException) as err:
        saved_searches.add(ME, q="engineers")
    assert err.value.status_code == 409


def test_a_saved_search_needs_something_to_search_for_and_a_card(world, matches):
    with pytest.raises(HTTPException) as err:
        saved_searches.add(ME, location="Pune")
    assert err.value.status_code == 422
    with pytest.raises(HTTPException) as err:
        saved_searches.add("00000000-0000-0000-0000-0000000000ff", q="investor")
    assert err.value.status_code == 409


def test_removing_stops_the_notifications_and_is_per_user(world, matches):
    sid = saved_searches.add(ME, q="seed investor")["search"]["id"]
    with pytest.raises(HTTPException):
        saved_searches.remove(ANN, sid)
    saved_searches.remove(ME, sid)
    matches.results = [hit("ann")]
    assert saved_searches.run_all()["searches"] == 0 and saved_searches.list_searches(ME)["searches"] == []


def test_one_failing_search_does_not_stop_the_others(world, matches, monkeypatch):
    saved_searches.add(ME, q="one")
    saved_searches.add(ME, q="two")
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return [hit("ann")]

    monkeypatch.setattr(search_service, "search_agents", flaky)
    stats = saved_searches.run_all()
    assert stats["failed"] == 1 and stats["nudges"] == 1


def test_the_runner_is_a_noop_without_the_flag(world, monkeypatch):
    monkeypatch.setattr(config, "FEATURE_NETWORK_CONTROLS", False)
    assert saved_searches.run_all()["enabled"] is False


# ── A5: connection brief ──────────────────────────────────────────────────────────

def cardmodel(**kw):
    c = AgentProfileCard(id="x", status="published", handle=kw.pop("handle", "x"),
                         identity={"name": kw.pop("name", "X"), "headline": kw.pop("headline", ""),
                                   "location": kw.pop("location", ""), "avatar_url": "", "links": {}}, **kw)
    return c


def test_the_brief_shows_what_each_side_is_doing_now_and_what_they_share():
    me = cardmodel(handle="me", skills=[{"name": "Python"}, {"name": "Rust"}], industries=["AI"], location="Pune, India",
                   zynd_memory=[fact("is_building", "agent platform")], can_help_with=["fundraising"])
    them = cardmodel(handle="ann", name="Ann", headline="Seed investor", skills=[{"name": "python"}], industries=["AI", "Fintech"],
                     location="Mumbai, India", love_talking_about=["AI"],
                     zynd_memory=[fact("is_seeking", "investment"), fact("is_working_on", "a new fund", 2), fact("is_working_on", "old thing", 400)])
    brief = connection_brief.build_brief(me, them)
    assert brief["partner"] == {"handle": "ann", "name": "Ann", "headline": "Seed investor"}
    assert [f["text"] for f in brief["now"]["you"]] == ["Building agent platform"]
    assert [f["text"] for f in brief["now"]["them"]] == ["Looking for investment", "Working on a new fund"]      # the 400-day-old fact is expired
    assert brief["shared"]["skills"] == ["python"] and brief["shared"]["industries"] == ["AI"] and brief["shared"]["location"] == "Mumbai, India"
    assert "You both care about python" in brief["suggested_topics"]
    assert any(t.startswith("Looking for investment") for t in brief["suggested_topics"])
    assert "Ask about: a new fund" in brief["suggested_topics"]


def test_the_brief_is_empty_not_invented_when_there_is_nothing_to_say():
    brief = connection_brief.build_brief(cardmodel(handle="a"), cardmodel(handle="b"))
    assert brief["now"] == {"you": [], "them": []} and brief["suggested_topics"] == []
    assert brief["shared"] == {"skills": [], "industries": [], "interests": [], "location": ""}


def test_the_brief_is_only_for_accepted_connections_between_the_two_people(world):
    pending = connect(world, ME, ANN, status="pending")
    with pytest.raises(HTTPException) as err:
        network.connection_brief(ME, pending["id"])
    assert err.value.status_code == 409
    pending["status"] = "accepted"
    out = network.connection_brief(ME, pending["id"])
    assert out["brief"]["partner"]["handle"] == "ann"
    assert network.connection_brief(ANN, pending["id"])["brief"]["partner"]["handle"] == "me"
    with pytest.raises(HTTPException) as err:
        network.connection_brief(BOB, pending["id"])
    assert err.value.status_code == 404


# ── A4: digest ────────────────────────────────────────────────────────────────────

def test_mutual_matches_need_to_fit_in_both_directions():
    me = cardmodel(handle="me", headline="Founder building AI agents", connect_with=["Investors"])
    fits = row("c1", "inv", "u1", headline="Seed investor", connect_with=["Founders"])
    one_way = row("c2", "inv2", "u2", headline="Seed investor")                       # does not say they want founders
    wrong_kind = row("c3", "eng", "u3", headline="Engineer", connect_with=["Founders"])     # fits them, not what I want
    unclaimed = row("c4", "inv3", "u4", headline="Angel investor", connect_with=["Founders"], claimed=False)
    got = digest_network.mutual_matches(me, [fits, one_way, wrong_kind, unclaimed], set())
    assert [m["handle"] for m in got] == ["inv"] and got[0]["wants"] == ["Founders"]
    assert digest_network.mutual_matches(me, [fits], {"inv"}) == []                   # already connected
    assert digest_network.mutual_matches(cardmodel(handle="me"), [fits], set()) == []


def test_connection_updates_are_this_weeks_approved_changes():
    ann = cardmodel(handle="ann", name="Ann", zynd_memory=[fact("is_seeking", "investment", 1), fact("is_building", "old", 20),
                                                              fact("has_skill", "Rust", 1)])
    updates = digest_network.connection_updates([ann])
    assert [(u["name"], u["change"]) for u in updates] == [("Ann", "Looking for investment")]


def test_the_digest_renders_the_network_section_in_text_and_html(world):
    from services import owner_notifications as notes
    network_section = digest_network.section(
        [{"handle": "inv", "name": "Inv", "headline": "", "wants": ["Founders"]}],
        [{"handle": "ann", "name": "Ann", "change": "Looking for investment", "approved_at": NOW.isoformat()}],
        ["New match for “seed investors”: Ann"])
    data = {"handle": "me", "name": "Me", "activity": {"available": False, "views": 0, "agent_hits": 0, "queries": []},
            "inbox_count": 0, "completeness": {"score": 80}, "network": network_section}
    text, markup = notes.render_weekly(data, None)
    assert "Your network this week" in text and "Inv wants to meet people like you (Founders)" in text
    assert "Ann: Looking for investment" in text and "New match for “seed investors”: Ann" in text
    assert "<h2>Your network this week</h2>" in markup and "Looking for investment" in markup
    data["network"] = None
    assert "Your network this week" not in notes.render_weekly(data, None)[0]
    assert digest_network.section([], [], []) is None


def test_the_network_section_is_skipped_without_the_flag(world, monkeypatch):
    from services import owner_notifications as notes
    monkeypatch.setattr(config, "FEATURE_NETWORK_CONTROLS", False)
    assert notes._network_section("me@example.com", {"owner_user_id": ME}, []) is None


def test_the_network_section_assembles_from_connections_and_cards(world):
    from services import owner_notifications as notes
    ann_row = row("c-ann", "ann", ANN, headline="Seed investor", connect_with=["Founders"],
                  memory=[fact("is_seeking", "investment", 1)])
    world.tables["agent_profile_cards"][1] = ann_row
    connect(world, ME, BOB)
    world.tables["agent_profile_cards"][2] = row("c-bob", "bob", BOB, headline="Engineer", memory=[fact("is_building", "a db", 1)])
    world.new_row("card_nudges", {"owner_email": "me@example.com", "kind": "saved_search", "title": "New match for “x”: Cy",
                                  "created_at": NOW.isoformat()})
    my = world.tables["agent_profile_cards"][0]
    got = notes._network_section("me@example.com", my, world.rows("agent_profile_cards"))
    assert [m["handle"] for m in got["mutual_matches"]] == ["ann"]
    assert [(u["name"], u["change"]) for u in got["connection_updates"]] == [("Bob", "Building a db")]
    assert got["saved_search_hits"] == ["New match for “x”: Cy"]


# ── A7: group-scoped search ───────────────────────────────────────────────────────

def test_group_search_covers_only_members_and_only_for_members(world):
    group = "g1"
    world.new_row("groups", {"id": group, "name": "Demo day", "owner_user_id": ME, "archived_at": None})
    for u in (ME, ANN, BOB):
        world.new_row("group_members", {"group_id": group, "user_id": u, "role": "member"})
    out = network.search_group(ME, group, q="investor")
    handles = [r["handle"] for r in out["results"]]
    assert set(handles) <= {"ann", "bob"} and "cy" not in handles and "me" not in handles      # cy is not in the group
    assert out["members_searched"] == 2 and handles[0] == "ann"
    assert all(r["claimed"] is True for r in out["results"])
    with pytest.raises(HTTPException) as err:
        network.search_group(CY, group, q="investor")                                          # not a member
    assert err.value.status_code == 404


def test_group_search_with_no_query_lists_the_members(world):
    world.new_row("groups", {"id": "g2", "name": "x", "owner_user_id": ME, "archived_at": None})
    for u in (ME, ANN, BOB):
        world.new_row("group_members", {"group_id": "g2", "user_id": u, "role": "member"})
    assert sorted(r["handle"] for r in network.search_group(ME, "g2")["results"]) == ["ann", "bob"]


# ── API plumbing ──────────────────────────────────────────────────────────────────

def test_the_routes_are_wired_and_need_the_service_identity(world, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import network as api
    monkeypatch.setattr(config, "MEMORY_SERVICE_TOKEN", "svc")
    app = FastAPI()
    app.include_router(api.router, prefix="/cards")
    client = TestClient(app)
    auth = {"Authorization": "Bearer svc", "X-Zynd-User": ME}

    assert client.post("/cards/network/cards/bob/report", json={"reason": "spam"}).status_code in (401, 403)
    assert client.post("/cards/network/cards/bob/report", headers=auth, json={"reason": "spam"}).json()["reported"] is True
    assert client.post("/cards/network/cards/bob/report", headers=auth, json={"reason": "nope"}).status_code == 422
    assert client.post("/cards/network/preferences", headers=auth, json={"kind": "mute_topic", "value": "crypto"}).status_code == 200
    assert client.get("/cards/network/preferences", headers=auth).json()["preferences"]["mute_topic"] == ["crypto"]
    assert client.post("/cards/network/preferences/remove", headers=auth, json={"kind": "mute_topic", "value": "crypto"}).json()["removed"]
    sid = client.post("/cards/network/saved-searches", headers=auth, json={"q": "seed investor"}).json()["search"]["id"]
    assert client.get("/cards/network/saved-searches", headers=auth).json()["searches"][0]["id"] == sid
    assert client.delete(f"/cards/network/saved-searches/{sid}", headers=auth).json()["removed"] is True
    assert client.post("/cards/network/saved-searches", headers=auth, json={"q": "x", "junk": 1}).status_code == 422


def test_the_cron_route_needs_the_cron_secret(world, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import internal
    monkeypatch.setattr(config, "CRON_SECRET", "cron")
    app = FastAPI()
    app.include_router(internal.router, prefix="/internal")
    client = TestClient(app)
    assert client.post("/internal/saved-searches/run").status_code == 401
    assert client.post("/internal/saved-searches/run", headers={"Authorization": "Bearer cron"}).json()["enabled"] is True


def test_the_saved_search_runner_calls_the_real_search_correctly(world, monkeypatch):
    """The other saved-search tests stub the search; this one runs it, so a wrong argument
    order (limit passed as experience_min, say) cannot hide."""
    from unittest.mock import MagicMock
    sb = MagicMock()
    sb.rpc.side_effect = RuntimeError("no rpc")
    monkeypatch.setattr(search_service.config, "get_supabase", lambda: sb)
    rows = [row("c-a", "match", "u1", headline="Backend engineer", skills=[{"name": "Rust"}]),
            row("c-b", "unclaimed", "u2", headline="Backend engineer", claimed=False)]
    monkeypatch.setattr(search_service.cards_service, "list_published_rows", lambda **kw: rows)
    got = saved_searches._strong("backend engineer", "engineer", "", "", "me", set())
    assert [r["handle"] for r in got] == ["match"]            # claimed only, strong only
