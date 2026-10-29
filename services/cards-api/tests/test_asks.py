"""Asks (services/asks.py): publish and dismiss, routing, offers, close-out, credits, and that none of
it can break what it is attached to when the tables are missing."""
import json
import logging
from datetime import timedelta

import pytest
from fastapi import HTTPException

from services import asks, beacons, events, feed, network, search, zynd_memory
from tests.asks_support import (ASK_1, ASK_2, HELPER, NOW, OWNER, Db, MissingTablesDb, ask_row, card_row, iso, offer_row,
                                use_db)  # noqa: F401  (use_db is a fixture)


def cards_db(db_class=Db, **tables):
    return db_class(agent_profile_cards=[
        card_row("card-a", "ana", "Ana Rao", owner_user_id=OWNER),
        card_row("card-b", "bob", "Bob Lee", owner_user_id=HELPER),
        card_row("card-c", "cy", "Cy Park", owner_user_id="00000000-0000-4000-8000-0000000000c1"),
    ], **tables)


@pytest.fixture
def scheduled(monkeypatch):
    calls = []
    monkeypatch.setattr(asks, "schedule_routing", lambda ask_id, row, text: calls.append((ask_id, row["id"], text)))
    return calls


@pytest.fixture
def emitted(monkeypatch):
    calls = []
    monkeypatch.setattr(events, "emit", lambda event, **kw: calls.append((event, kw)))
    return calls


# --- Publish and dismiss ------------------------------------------------------------------------

def test_publishing_gives_the_beacon_an_id_and_stores_the_ask_then_routes_it(use_db, scheduled):
    db = use_db(cards_db())
    value = beacons.save_beacon("ana", "ana@x.test", "Looking for a React developer")
    assert value["id"]
    (row,) = db.rows("asks")
    assert row["id"] == value["id"] and row["card_id"] == "card-a" and row["owner_user_id"] == OWNER
    assert row["text"] == "Looking for a React developer"
    assert db.rows("agent_profile_cards")[0]["card"]["beacon"]["id"] == value["id"]
    assert scheduled == [(value["id"], "card-a", "Looking for a React developer")]


def test_a_new_ask_ends_the_previous_one_as_replaced(use_db, scheduled):
    db = use_db(cards_db())
    first = beacons.save_beacon("ana", "ana@x.test", "First ask")
    db.rows("agent_profile_cards")[0]["updated_at"] = "v2"
    second = beacons.save_beacon("ana", "ana@x.test", "Second ask")
    rows = {r["id"]: r for r in db.rows("asks")}
    assert rows[first["id"]]["end_reason"] == "replaced" and rows[first["id"]]["ended_at"]
    assert rows[second["id"]].get("ended_at") is None


def test_dismissing_ends_the_ask_as_dismissed(use_db, scheduled):
    db = use_db(cards_db())
    value = beacons.save_beacon("ana", "ana@x.test", "An ask")
    db.rows("agent_profile_cards")[0]["updated_at"] = "v2"
    assert beacons.save_beacon("ana", "ana@x.test", None) is None
    (row,) = db.rows("asks")
    assert row["id"] == value["id"] and row["end_reason"] == "dismissed" and row["ended_at"]
    assert db.rows("agent_profile_cards")[0]["card"]["beacon"] is None


def test_a_beacon_published_before_asks_existed_still_parses_without_an_id():
    from models.card import Beacon

    beacon = Beacon.model_validate({"text": "Old", "created_at": iso(days=1), "expires_at": (NOW + timedelta(days=5)).isoformat()})
    assert beacon.id is None


def test_the_card_write_comes_first_a_failed_swap_stores_no_ask(use_db, scheduled):
    db = use_db(cards_db())
    db.rows("agent_profile_cards")[0]["updated_at"] = "v1"
    original = db.table

    def stale(name):
        query = original(name)
        if name == "agent_profile_cards":
            real = query.update
            query.update = lambda payload: real(payload).eq("updated_at", "not-the-version")
        return query
    db.table = stale
    with pytest.raises(HTTPException) as caught:
        beacons.save_beacon("ana", "ana@x.test", "Won't land")
    assert caught.value.status_code == 409
    assert db.rows("asks") == [] and scheduled == []


# --- The tables are missing (migration not applied) --------------------------------------------

def test_publish_dismiss_and_the_rest_work_without_the_tables_and_log_once(use_db, scheduled, emitted, caplog):
    db = use_db(cards_db(MissingTablesDb))
    caplog.set_level(logging.INFO, logger="services.asks")
    value = beacons.save_beacon("ana", "ana@x.test", "Looking for a designer")
    assert value["text"] == "Looking for a designer"
    db.rows("agent_profile_cards")[0]["updated_at"] = "v2"
    assert beacons.save_beacon("ana", "ana@x.test", None) is None
    assert scheduled == []                                  # nothing was stored, so nothing is routed
    assert asks.routed_ask_ids("card-a") == set()
    assert asks.credits_for_card("card-a") == {"count": 0, "items": []}
    assert asks.list_for_owner({"id": "card-a"}, NOW) == {"asks": []}
    assert asks.credits_for_owner("card-a") == {"credits": []}
    assert not asks.record_offer(ASK_1, asker_card_id="card-a", helper_user_id=HELPER, helper_card_id="card-b",
                                 connection_id=None, channel="dm", now=NOW)
    assert asks.digest_items({"id": "card-a"}, set(), NOW)["routed"] == []
    notes = [r.message for r in caplog.records if "tables not found" in r.message]
    assert len(notes) == 1 and notes[0].startswith("asks:")
    assert not asks.available()
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_missing_tables_are_checked_again_after_the_retry_interval(use_db, monkeypatch):
    use_db(cards_db(MissingTablesDb))
    asks.routed_ask_ids("card-a")
    assert not asks.available()
    monkeypatch.setattr(asks.time, "monotonic", lambda: asks._missing_until + 1)
    assert asks.available()


def test_other_failures_are_skipped_and_logged_by_code_without_the_row(use_db, caplog):
    class Boom(Db):
        def table(self, name):
            q = super().table(name)

            def fail():
                raise RuntimeError("secret-words-123 in a failing row")
            q.execute = fail
            return q
    use_db(Boom())
    caplog.set_level(logging.INFO, logger="services.asks")
    assert asks.routed_ask_ids("card-a") == set()
    assert asks.available()                                 # a real failure is not "tables missing"
    assert "secret-words-123" not in caplog.text


def test_a_failing_asks_insert_never_fails_the_publish(use_db, scheduled, monkeypatch):
    use_db(cards_db())
    monkeypatch.setattr(asks, "record_publish", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert beacons.save_beacon("ana", "ana@x.test", "Still publishes")["text"] == "Still publishes"


# --- Routing ------------------------------------------------------------------------------------

def result(handle, score, card_id=None):
    return {"handle": handle, "agent_id": card_id or f"card-{handle}", "match_score": score}


def test_select_routes_applies_threshold_cap_exclusions_and_order():
    results = [result("low", 0.59), result("a", 0.9), result("b", 0.8), result("me", 0.95), result("hidden", 0.85),
               result("c", 0.7), result("d", 0.65), result("e", 0.64), result("f", 0.61), result("a", 0.5)]
    picked = asks.select_routes(results, asker_handle="Me", excluded={"hidden"})
    assert [p["handle"] for p in picked] == ["a", "b", "c", "d", "e"]          # five, best first
    assert all(p["score"] >= asks.ASK_ROUTE_MIN_SCORE for p in picked)


def test_select_routes_needs_a_card_id_and_keeps_each_card_once():
    assert asks.select_routes([{"handle": "x", "match_score": 0.9}], asker_handle="me", excluded=set()) == []
    out = asks.select_routes([result("a", 0.7, "same"), result("a", 0.9, "same")], asker_handle="me", excluded=set())
    assert out == [{"card_id": "same", "handle": "a", "score": 0.9}]


def test_the_route_threshold_reuses_the_saved_search_alert_score():
    from services.saved_searches import STRONG_MATCH

    assert asks.ASK_ROUTE_MIN_SCORE == STRONG_MATCH and asks.ASK_ROUTE_MAX == 5


@pytest.fixture
def routing(use_db, monkeypatch):
    db = use_db(cards_db())
    seen = {}
    monkeypatch.setattr(search, "search_agents", lambda **kw: seen.update(kw) or [
        result("bob", 0.9, "card-b"), result("cy", 0.7, "card-c"), result("ana", 0.99, "card-a"), result("weak", 0.3, "card-w")])
    from services import match_prefs
    monkeypatch.setattr(match_prefs, "get", lambda uid: {"hide_person": []})
    monkeypatch.setattr(network, "get_inbox", lambda uid: {"connections": []})
    return db, seen


def row_a(db):
    return db.rows("agent_profile_cards")[0]


def test_routing_runs_the_people_search_with_the_ask_and_stores_the_best_matches(routing):
    db, seen = routing
    assert asks.route_ask(ASK_1, row_a(db), "Need a React developer") == 2
    assert seen["q"] == "Need a React developer" and seen["searcher"].handle == "ana" and seen["include_unclaimed"] is False
    assert {(r["helper_card_id"], r["score"]) for r in db.rows("ask_routes")} == {("card-b", 0.9), ("card-c", 0.7)}


def test_routing_twice_does_not_duplicate_routes(routing):
    db, _ = routing
    asks.route_ask(ASK_1, row_a(db), "Need a React developer")
    asks.route_ask(ASK_1, row_a(db), "Need a React developer")
    assert len(db.rows("ask_routes")) == 2


def test_routing_leaves_out_blocked_declined_revoked_and_hidden_pairs(routing, monkeypatch):
    db, _ = routing
    from services import match_prefs
    monkeypatch.setattr(match_prefs, "get", lambda uid: {"hide_person": ["cy"]})
    monkeypatch.setattr(network, "get_inbox", lambda uid: {"connections": [
        {"id": "c1", "status": "declined", "incoming": True, "partner": {"handle": "bob"}}]})
    assert asks.route_ask(ASK_1, row_a(db), "Need a React developer") == 0


def test_routing_leaves_out_people_who_hid_the_asker(routing):
    db, _ = routing
    db.tables["match_preferences"] = [{"user_id": HELPER, "kind": "hide_person", "value": "ana"}]
    asks.route_ask(ASK_1, row_a(db), "Need a React developer")
    assert [r["helper_card_id"] for r in db.rows("ask_routes")] == ["card-c"]


def test_routing_that_cannot_check_exclusions_routes_nobody(routing, monkeypatch):
    db, _ = routing
    monkeypatch.setattr(network, "get_inbox", lambda uid: (_ for _ in ()).throw(RuntimeError("down")))
    assert asks.route_safely(ASK_1, row_a(db), "Need a React developer") == 0
    assert db.rows("ask_routes") == []


def test_routing_failures_never_escape_the_background_task(routing, monkeypatch):
    db, _ = routing
    monkeypatch.setattr(search, "search_agents", lambda **kw: (_ for _ in ()).throw(RuntimeError("search down")))
    assert asks.route_safely(ASK_1, row_a(db), "x") == 0


def test_routed_asks_are_read_in_one_query(use_db):
    db = use_db(cards_db(ask_routes=[{"ask_id": ASK_1, "helper_card_id": "card-b", "score": 0.8},
                                    {"ask_id": ASK_2, "helper_card_id": "card-c", "score": 0.8}]))
    assert asks.routed_ask_ids("card-b") == {ASK_1}
    assert db.asked == ["ask_routes"]


# --- The feed uses routes -----------------------------------------------------------------------

def test_a_routed_ask_ranks_higher_and_says_why():
    from tests.test_feed import beacon, row
    from datetime import timezone

    stranger = row("zed", beacon=beacon("Looking for help", days_old=0))
    routed = row("ana", beacon={**beacon("Looking for help", days_old=2), "id": ASK_1})
    page = feed.build_feed(feed.Viewer(handle="me", card_id="id-me"), [stranger, routed], {}, set(), {}, NOW)
    assert page["items"][0]["author"]["handle"] == "zed"
    page = feed.build_feed(feed.Viewer(handle="me", card_id="id-me"), [stranger, routed], {}, set(), {}, NOW, routed={ASK_1})
    first = page["items"][0]
    assert first["author"]["handle"] == "ana" and first["reason"] == feed.REASON_ROUTED
    assert first["id"] == f"ask:ana:{ASK_1}"                  # the ask id is the item key
    assert "_ask_id" not in first


# --- Offers -------------------------------------------------------------------------------------

def offer(db, *, ask_id=ASK_1, helper="card-b", user=HELPER, channel="dm", connection=None, card="card-a"):
    return asks.record_offer(ask_id, asker_card_id=card, helper_user_id=user, helper_card_id=helper,
                             connection_id=connection, channel=channel, now=NOW)


def test_an_offer_is_stored_once_per_helper(use_db, emitted):
    db = use_db(cards_db(asks=[ask_row()]))
    assert offer(db, connection="00000000-0000-4000-8000-0000000000c9") is True
    assert offer(db) is False
    (stored,) = db.rows("ask_offers")
    assert stored["helper_card_id"] == "card-b" and stored["channel"] == "dm"
    assert [e for e, _ in emitted] == ["ask_offer"]
    assert emitted[0][1]["meta"] == {"channel": "dm"}
    assert "secret" not in json.dumps(emitted, default=str)


def test_offers_are_refused_on_your_own_ask_an_ended_ask_or_someone_elses_card(use_db):
    db = use_db(cards_db(asks=[ask_row(), ask_row(ASK_2, "card-c", ended_at=iso(hours=1), end_reason="dismissed")]))
    assert offer(db, helper="card-a", user=OWNER) is False                    # own ask
    assert offer(db, ask_id=ASK_2, card="card-c") is False                    # ended
    assert offer(db, card="card-c") is False                                  # the ask is not that card's
    db.rows("asks")[0]["expires_at"] = iso(hours=1)
    assert offer(db) is False                                                 # expired
    assert offer(db, channel="email") is False
    assert asks.record_offer("not-a-uuid", asker_card_id="card-a", helper_user_id=HELPER, helper_card_id="card-b",
                             connection_id=None, channel="dm", now=NOW) is False
    assert db.rows("ask_offers") == []


@pytest.fixture
def world(monkeypatch, use_db):
    """feed.reply_to_item with the network faked and the asks tables in memory."""
    from tests.test_feed import beacon, row
    db = use_db(cards_db(asks=[ask_row(ASK_1, "id-ana", created_days=1)]))
    rows = [row("me", unit=[1.0]), row("ana", beacon={**beacon("Need a React developer"), "id": ASK_1})]
    state = {"inbox": [], "sent": [], "requested": []}
    monkeypatch.setattr(feed, "published_rows", lambda: rows)
    monkeypatch.setattr(network, "_find_card_for_user", lambda uid: {"id": "id-me", "handle": "me", "card": {}})
    monkeypatch.setattr(network, "get_inbox", lambda uid: {"connections": state["inbox"]})
    from services import feed_github, match_prefs
    monkeypatch.setattr(match_prefs, "get", lambda uid: {"hide_person": []})
    monkeypatch.setattr(feed_github, "get", lambda logins: {})
    monkeypatch.setattr(network, "_card_for_handle", lambda h: {"id": "id-ana", "owner_user_id": "ana-user"})
    monkeypatch.setattr(network, "request_connection", lambda uid, h, m=None: state["requested"].append(m) or
                        {"connection": {"id": "00000000-0000-4000-8000-0000000000c9", "status": "pending", "incoming": False}, "existing": False})
    monkeypatch.setattr(network, "send_message", lambda uid, cid, content, client_id=None: state["sent"].append(content) or {})
    monkeypatch.setattr(events, "emit", lambda *a, **k: None)
    return db, state


def test_replying_to_an_ask_records_one_offer_and_a_second_reply_still_sends(world):
    db, state = world
    item_id = f"ask:ana:{ASK_1}"
    assert feed.reply_to_item(HELPER, item_id, "I can help", now=NOW)["channel"] == "request"
    state["inbox"] = [{"id": "00000000-0000-4000-8000-0000000000c9", "status": "accepted", "incoming": False,
                       "partner": {"handle": "ana"}}]
    assert feed.reply_to_item(HELPER, item_id, "Following up", now=NOW)["channel"] == "dm"
    assert state["sent"] == ["Following up"]
    (stored,) = db.rows("ask_offers")
    assert stored["ask_id"] == ASK_1 and stored["helper_card_id"] == "id-me" and stored["helper_user_id"] == HELPER
    assert stored["channel"] == "request" and stored["connection_id"] == "00000000-0000-4000-8000-0000000000c9"


def test_a_reply_still_goes_through_when_the_offer_cannot_be_recorded(world, monkeypatch):
    _, state = world
    monkeypatch.setattr(asks, "_sb", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    assert feed.reply_to_item(HELPER, f"ask:ana:{ASK_1}", "I can help", now=NOW)["channel"] == "request"
    assert state["requested"] == ["I can help"]


def test_replies_to_other_kinds_record_no_offer(world, monkeypatch):
    db, _ = world
    from tests.test_feed import fact, row
    monkeypatch.setattr(feed, "published_rows", lambda: [row("me", unit=[1.0]), row("ana", zynd_memory=[fact("Voice agents")])])
    item = feed.build_feed(feed.Viewer(handle="me", card_id="id-me"), feed.published_rows(), {}, set(), {}, NOW)["items"][0]
    feed.reply_to_item(HELPER, item["id"], "Me too", now=NOW)
    assert db.rows("ask_offers") == []


# --- Close-out ----------------------------------------------------------------------------------

def owner_row(handle="ana", card_id="card-a"):
    return {"id": card_id, "handle": handle}


@pytest.fixture
def closing(use_db, monkeypatch, emitted):
    db = use_db(cards_db(asks=[ask_row(created_days=1)],
                         ask_offers=[offer_row("card-b"), offer_row("card-c", helper_user_id="00000000-0000-4000-8000-0000000000c1")]))
    cleared, refreshed = [], []
    monkeypatch.setattr(beacons, "save_beacon", lambda handle, email, text: cleared.append((handle, email, text)))
    monkeypatch.setattr(zynd_memory, "ping_revalidate", lambda handle, **k: refreshed.append(handle))
    return db, cleared, refreshed, emitted


def answer(outcome, helpers=(), ask_id=ASK_1, row=None):
    return asks.set_outcome(row or owner_row(), "ana@x.test", ask_id, outcome, list(helpers), NOW)


def test_helped_credits_the_chosen_offerers_ends_a_live_ask_clears_the_beacon_and_refreshes_cards(closing):
    db, cleared, refreshed, emitted = closing
    result = answer("helped", ["card-b"])
    assert result == {"ask_id": ASK_1, "outcome": "helped", "credited": 1, "changed": True, "beacon_cleared": True}
    ask = db.rows("asks")[0]
    assert ask["outcome"] == "helped" and ask["ended_at"] and ask["end_reason"] == "solved"
    credited = {o["helper_card_id"]: o["credited_at"] for o in db.rows("ask_offers")}
    assert credited["card-b"] and credited["card-c"] is None
    assert cleared == [("ana", "ana@x.test", None)] and refreshed == ["bob"]
    assert emitted[-1][0] == "ask_outcome" and emitted[-1][1]["meta"] == {"outcome": "helped", "helpers": 1, "offers": 2, "was_active": True}


def test_solved_elsewhere_ends_a_live_ask_and_credits_nobody(closing):
    db, cleared, refreshed, _ = closing
    answer("solved_elsewhere")
    assert db.rows("asks")[0]["end_reason"] == "solved" and cleared and refreshed == []
    assert all(o["credited_at"] is None for o in db.rows("ask_offers"))


def test_still_looking_records_the_answer_without_ending_a_live_ask(closing):
    db, cleared, _, _ = closing
    answer("still_looking")
    ask = db.rows("asks")[0]
    assert ask["outcome"] == "still_looking" and ask["ended_at"] is None and cleared == []


def test_an_already_ended_ask_is_not_ended_again_or_the_beacon_cleared(closing):
    db, cleared, _, _ = closing
    db.rows("asks")[0].update(ended_at=iso(days=1), end_reason="dismissed")
    answer("helped", ["card-b"])
    assert db.rows("asks")[0]["end_reason"] == "dismissed" and cleared == []


def test_only_people_who_offered_can_be_credited(closing):
    db, *_ = closing
    for bad in (["card-zzz"], ["card-b", "card-a"]):
        with pytest.raises(HTTPException) as caught:
            answer("helped", bad)
        assert caught.value.status_code == 422
    assert db.rows("asks")[0]["outcome"] is None and all(o["credited_at"] is None for o in db.rows("ask_offers"))


def test_helped_needs_a_helper_and_the_other_outcomes_take_none(closing):
    for outcome, helpers in (("helped", []), ("solved_elsewhere", ["card-b"]), ("still_looking", ["card-b"]), ("bogus", [])):
        with pytest.raises(HTTPException) as caught:
            answer(outcome, helpers)
        assert caught.value.status_code == 422


def test_another_owners_ask_is_not_found(closing):
    with pytest.raises(HTTPException) as caught:
        answer("solved_elsewhere", row=owner_row("cy", "card-c"))
    assert caught.value.status_code == 404
    for bad_id in ("not-a-uuid", ASK_2):
        with pytest.raises(HTTPException) as caught:
            answer("solved_elsewhere", ask_id=bad_id)
        assert caught.value.status_code == 404


def test_the_same_answer_twice_changes_nothing_and_a_different_one_conflicts(closing):
    db, cleared, _, emitted = closing
    answer("helped", ["card-b"])
    before = [dict(o) for o in db.rows("ask_offers")]
    again = answer("helped", ["card-b"])
    assert again["changed"] is False and again["credited"] == 1
    assert db.rows("ask_offers") == before and len(cleared) == 1
    assert [e for e, _ in emitted].count("ask_outcome") == 1
    with pytest.raises(HTTPException) as caught:
        answer("solved_elsewhere")
    assert caught.value.status_code == 409


def test_a_beacon_that_cannot_be_cleared_does_not_undo_the_answer(closing, monkeypatch):
    db, *_ = closing
    monkeypatch.setattr(beacons, "save_beacon", lambda *a: (_ for _ in ()).throw(HTTPException(409, "changed")))
    assert answer("solved_elsewhere")["beacon_cleared"] is False
    assert db.rows("asks")[0]["outcome"] == "solved_elsewhere"


def test_outcome_without_the_tables_is_a_404_not_a_crash(use_db):
    use_db(cards_db(MissingTablesDb))
    with pytest.raises(HTTPException) as caught:
        answer("solved_elsewhere")
    assert caught.value.status_code == 404


# --- The owner's list ---------------------------------------------------------------------------

def test_the_owners_list_has_the_live_ask_and_unanswered_recent_ones_with_offers_in_four_queries(use_db):
    db = use_db(cards_db(
        asks=[ask_row(ASK_1, created_days=1, text="Live ask"),
              ask_row(ASK_2, created_days=12, lives_days=7, text="Expired five days ago"),
              ask_row("00000000-0000-4000-8000-000000000003", created_days=3, text="Answered", outcome="helped", ended_at=iso(days=2)),
              ask_row("00000000-0000-4000-8000-000000000004", created_days=30, text="Too old"),
              ask_row("00000000-0000-4000-8000-000000000005", created_days=5, text="Replaced, nobody offered", ended_at=iso(days=3), end_reason="replaced"),
              ask_row("00000000-0000-4000-8000-000000000006", card_id="card-c", text="Someone else's")],
        ask_offers=[offer_row("card-b"), offer_row("card-c", user="x", helper_user_id="00000000-0000-4000-8000-0000000000c1", ask_id=ASK_2)]))
    listed = asks.list_for_owner(owner_row(), NOW)["asks"]
    assert [(a["text"], a["status"]) for a in listed] == [("Live ask", "active"), ("Expired five days ago", "ended")]
    live, ended = listed
    assert [o["handle"] for o in live["offers"]] == ["bob"] and live["offers"][0]["name"] == "Bob Lee"
    assert [o["handle"] for o in ended["offers"]] == ["cy"]
    assert db.asked == ["asks", "ask_offers", "agent_profile_cards", "ask_routes"]


# --- Credits ------------------------------------------------------------------------------------

def credit(offer_id, asker="ana", *, ask="Need a React developer", credited=True, hidden=False, status="published", when=None):
    return {"id": offer_id, "credited_at": (when or iso(days=1)) if credited else None, "credit_hidden_at": iso(hours=1) if hidden else None,
            "credit_notified_at": None,
            "ask": {"id": "a", "text": ask, "card": {"handle": asker, "status": status, "card": {"identity": {"name": f"{asker.title()} Rao"}}}}}


def test_a_credit_shows_only_when_credited_not_hidden_and_the_asker_is_published():
    shaped = asks.shape_credits([credit("1"), credit("2", "bob", credited=False), credit("3", "cy", hidden=True),
                                 credit("4", "di", status="draft"), credit("5", "ed", status="merged")])
    assert shaped["count"] == 1 and [c["asker_handle"] for c in shaped["items"]] == ["ana"]
    assert shaped["items"][0]["asker_name"] == "Ana"


def test_credits_list_the_latest_three_count_people_and_cut_long_asks():
    rows = [credit(str(i), f"p{i}", when=iso(days=10 - i), ask="word " * 60) for i in range(5)]
    shaped = asks.shape_credits(rows)
    assert shaped["count"] == 5 and len(shaped["items"]) == asks.CREDITS_SHOWN
    assert [c["asker_handle"] for c in shaped["items"]] == ["p4", "p3", "p2"]
    assert len(shaped["items"][0]["ask"]) <= asks.CREDIT_ASK_CHARS + 1 and shaped["items"][0]["ask"].endswith("…")
    same_person = asks.shape_credits([credit("1"), credit("2")])
    assert same_person["count"] == 1 and len(same_person["items"]) == 2


def test_the_credit_query_hints_its_foreign_keys_or_postgrest_calls_the_embed_ambiguous():
    # Found against a real PostgREST: asks and cards are also related through the offers and routes
    # tables, so an unhinted embed fails with code 300 and every credit silently disappears.
    assert "asks!ask_offers_ask_id_fkey" in asks._CREDIT_SELECT
    assert "agent_profile_cards!asks_card_id_fkey" in asks._CREDIT_SELECT


def test_the_public_credits_never_expose_offer_ids(use_db, monkeypatch):
    monkeypatch.setattr(asks, "_credit_rows", lambda card_id: [credit("secret-offer-id")])
    public = asks.credits_for_card("card-b")
    assert public == {"count": 1, "items": [{"asker_handle": "ana", "asker_name": "Ana", "ask": "Need a React developer"}]}
    assert "secret-offer-id" not in json.dumps(public)
    assert asks.credits_for_card(None) == {"count": 0, "items": []}


def test_the_owner_sees_offer_ids_so_they_can_hide_a_credit(monkeypatch):
    monkeypatch.setattr(asks, "_credit_rows", lambda card_id: [credit("offer-1")])
    assert asks.credits_for_owner("card-b")["credits"][0]["offer_id"] == "offer-1"


def test_hiding_a_credit_is_owner_only_idempotent_and_refreshes_the_card(use_db, monkeypatch):
    offer_1 = "00000000-0000-4000-8000-0000000000d1"
    db = use_db(cards_db(asks=[ask_row()], ask_offers=[
        offer_row("card-b", offer_id=offer_1, credited_at=iso(days=1)),
        offer_row("card-c", offer_id="00000000-0000-4000-8000-0000000000d2", credited_at=iso(days=1), helper_user_id="x"),
        offer_row("card-b", offer_id="00000000-0000-4000-8000-0000000000d3", ask_id=ASK_2, helper_user_id="y")]))
    refreshed = []
    monkeypatch.setattr(zynd_memory, "ping_revalidate", lambda handle, **k: refreshed.append(handle))
    bob = {"id": "card-b", "handle": "bob"}
    assert asks.hide_credit(bob, offer_1, NOW) == {"hidden": True}
    hidden_at = db.rows("ask_offers")[0]["credit_hidden_at"]
    assert hidden_at and asks.hide_credit(bob, offer_1, NOW + timedelta(hours=1)) == {"hidden": True}
    assert db.rows("ask_offers")[0]["credit_hidden_at"] == hidden_at and refreshed == ["bob", "bob"]
    for other in ("00000000-0000-4000-8000-0000000000d2",    # someone else's offer
                  "00000000-0000-4000-8000-0000000000d3",    # mine but never credited
                  "00000000-0000-4000-8000-0000000000d9",    # does not exist
                  "nonsense"):
        with pytest.raises(HTTPException) as caught:
            asks.hide_credit(bob, other, NOW)
        assert caught.value.status_code == 404
    assert db.rows("ask_offers")[1]["credit_hidden_at"] is None


# --- Digest -------------------------------------------------------------------------------------

def digest_db(use_db):
    return use_db(cards_db(
        asks=[ask_row(ASK_1, "card-a", text="Need a React developer", created_days=1),
              ask_row(ASK_2, "card-c", text="Looking for a lawyer", created_days=2),
              ask_row("00000000-0000-4000-8000-000000000003", "card-c", text="Already over", created_days=2, ended_at=iso(hours=3), end_reason="dismissed"),
              ask_row("00000000-0000-4000-8000-000000000004", "card-b", text="Bob's ask that ended", created_days=9, lives_days=7),
              ask_row("00000000-0000-4000-8000-000000000005", "card-b", text="Bob's replaced one", created_days=9, ended_at=iso(days=8), end_reason="replaced")],
        ask_routes=[{"ask_id": ASK_1, "helper_card_id": "card-b", "score": 0.9, "created_at": iso(hours=2), "digest_sent_at": None},
                    {"ask_id": ASK_2, "helper_card_id": "card-b", "score": 0.8, "created_at": iso(hours=3), "digest_sent_at": None},
                    {"ask_id": "00000000-0000-4000-8000-000000000003", "helper_card_id": "card-b", "score": 0.8, "created_at": iso(hours=4), "digest_sent_at": None}]))


def test_the_digest_lists_live_routed_asks_up_to_the_cap_and_skips_blocked_askers(use_db):
    digest_db(use_db)
    items = asks.digest_items({"id": "card-b", "handle": "bob"}, set(), NOW)
    assert [r["text"] for r in items["routed"]] == ["Need a React developer", "Looking for a lawyer"]
    assert len(items["routed"]) <= asks.ASKS_PER_DIGEST
    assert items["routed"][0]["asker_name"] == "Ana"
    assert items["marks"]["routes"] == [ASK_1, ASK_2]
    blocked = asks.digest_items({"id": "card-b", "handle": "bob"}, {"ana"}, NOW)
    assert [r["asker_handle"] for r in blocked["routed"]] == ["cy"]


def test_the_digest_asks_the_owner_once_about_an_ended_ask_and_never_about_a_replaced_one(use_db):
    digest_db(use_db)
    items = asks.digest_items({"id": "card-b", "handle": "bob"}, set(), NOW)
    assert items["prompts"] == [{"ask_id": "00000000-0000-4000-8000-000000000004", "text": "Bob's ask that ended"}]
    asks.mark_digest_sent({"id": "card-b"}, items["marks"], NOW)
    again = asks.digest_items({"id": "card-b", "handle": "bob"}, set(), NOW)
    assert again["prompts"] == [] and again["routed"] == []


def test_the_digest_credit_line_comes_once_and_never_for_a_hidden_credit(use_db, monkeypatch):
    db = digest_db(use_db)
    rows = [credit("o1"), credit("o2", "cy", hidden=True), {**credit("o3", "di"), "credit_notified_at": iso(days=1)}]
    monkeypatch.setattr(asks, "_credit_rows", lambda card_id: rows)
    items = asks.digest_items({"id": "card-b", "handle": "bob"}, set(), NOW)
    assert items["credits"] == [{"asker_name": "Ana", "asker_handle": "ana", "ask": "Need a React developer"}]
    assert items["marks"]["credits"] == ["o1"]


def test_marking_sets_the_sent_fields(use_db):
    db = digest_db(use_db)
    db.tables["ask_offers"] = [offer_row("card-b", offer_id="o1", credited_at=iso(days=1))]
    asks.mark_digest_sent({"id": "card-b"}, {"routes": [ASK_1], "prompts": ["00000000-0000-4000-8000-000000000004"], "credits": ["o1"]}, NOW)
    assert {r["ask_id"]: r["digest_sent_at"] is not None for r in db.rows("ask_routes")}[ASK_1] is True
    assert [r["digest_sent_at"] for r in db.rows("ask_routes") if r["ask_id"] == ASK_2] == [None]
    assert next(a for a in db.rows("asks") if a["id"].endswith("4"))["outcome_prompted_at"]
    assert db.rows("ask_offers")[0]["credit_notified_at"]
