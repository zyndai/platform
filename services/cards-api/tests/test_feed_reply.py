"""POST /cards/feed/reply: the server picks the channel from the real connection state and re-checks
the author, the blocks and the item itself. Events carry counts and kinds, never message text."""
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import config
from api import feed as routes
from services import events, feed, feed_github, match_prefs, network
from tests.test_feed import NOW, UID, beacon, fact, row

MESSAGE = "Hi Ana, I can help with this: secret-words-123"
ASK_ID = f"ask:ana:{beacon()['created_at']}"


class Calls:
    def __init__(self):
        self.sent, self.requested, self.events = [], [], []


@pytest.fixture
def world(monkeypatch):
    calls = Calls()
    state = {
        "mine": {"id": "id-me", "handle": "me", "card": {}},
        "inbox": [],
        "hidden": [],
        "author": {"owner_user_id": "someone-else"},
        "request_result": None,
    }
    rows = [row("me", unit=[1.0]), row("ana", beacon=beacon("Need help with React"), zynd_memory=[fact("Voice agents")]),
            row("bob", beacon=beacon("Bob's ask"))]
    monkeypatch.setattr(feed, "published_rows", lambda: rows)
    monkeypatch.setattr(network, "_find_card_for_user", lambda uid: state["mine"])
    monkeypatch.setattr(network, "get_inbox", lambda uid: {"connections": state["inbox"]})
    monkeypatch.setattr(match_prefs, "get", lambda uid: {"hide_person": state["hidden"]})
    monkeypatch.setattr(feed_github, "get", lambda logins: {})

    def card_for_handle(handle):
        if state["author"] is None:
            raise HTTPException(404, "That verified Card is not available")
        return state["author"]
    monkeypatch.setattr(network, "_card_for_handle", card_for_handle)

    def request_connection(uid, handle, message=None):
        calls.requested.append((uid, handle, message))
        if isinstance(state["request_result"], Exception):
            raise state["request_result"]
        return state["request_result"] or {"connection": {"id": "new-c", "status": "pending", "incoming": False}, "existing": False}
    monkeypatch.setattr(network, "request_connection", request_connection)
    monkeypatch.setattr(network, "send_message", lambda uid, cid, content, client_id=None: calls.sent.append((uid, cid, content, client_id)) or {"message": {"id": "m"}})
    monkeypatch.setattr(events, "emit", lambda event, **kw: calls.events.append((event, kw)))
    return calls, state


def connected(status="accepted", incoming=False, handle="ana"):
    return [{"id": "c1", "status": status, "incoming": incoming, "partner": {"handle": handle}}]


def ask_id():
    return next(i["id"] for i in feed.rank_feed(
        feed.Viewer(handle="me", card_id="id-me"), [row("ana", beacon=beacon("Need help with React"))], {}, set(), {}, NOW)
        if i["kind"] == "ask")


def reply(item_id=None, message=MESSAGE, client_id=None):
    return feed.reply_to_item(UID, item_id or ask_id(), message, client_id, now=NOW)


# --- Channel decision ---------------------------------------------------------------------------

def test_a_connected_author_gets_a_direct_message_and_no_request(world):
    calls, state = world
    state["inbox"] = connected()
    result = reply(client_id="00000000-0000-4000-8000-000000000009")
    assert result == {"channel": "dm", "connection": {"id": "c1", "status": "accepted", "incoming": False}}
    assert calls.sent == [(UID, "c1", MESSAGE, "00000000-0000-4000-8000-000000000009")]
    assert calls.requested == []


def test_a_stranger_gets_a_connection_request_carrying_the_message(world):
    calls, _ = world
    result = reply()
    assert result == {"channel": "request", "connection": {"id": "new-c", "status": "pending", "incoming": False}}
    assert calls.requested == [(UID, "ana", MESSAGE)]
    assert calls.sent == []


def test_the_request_limit_reaches_the_caller(world):
    _, state = world
    state["request_result"] = HTTPException(429, "You can send at most 25 connection requests a week")
    with pytest.raises(HTTPException) as caught:
        reply()
    assert caught.value.status_code == 429 and "25" in caught.value.detail


def test_a_request_that_raced_in_as_accepted_becomes_a_direct_message(world):
    calls, state = world
    state["request_result"] = {"connection": {"id": "c9", "status": "accepted", "incoming": False}, "existing": True}
    assert reply()["channel"] == "dm"
    assert calls.sent[0][1] == "c9"


def test_an_existing_pending_request_from_a_race_is_a_conflict_not_a_second_request(world):
    _, state = world
    state["request_result"] = {"connection": {"id": "c9", "status": "pending", "incoming": False}, "existing": True}
    with pytest.raises(HTTPException) as caught:
        reply()
    assert caught.value.status_code == 409


# --- Refusals -----------------------------------------------------------------------------------

def refused(status, **kw):
    with pytest.raises(HTTPException) as caught:
        reply(**kw)
    assert caught.value.status_code == status
    return caught.value.detail


def test_pending_outgoing_is_already_requested(world):
    calls, state = world
    state["inbox"] = connected("pending", incoming=False)
    assert refused(409) == "Already requested"
    assert calls.sent == [] and calls.requested == []


def test_pending_incoming_points_to_the_network(world):
    _, state = world
    state["inbox"] = connected("pending", incoming=True)
    assert "Network" in refused(409)


@pytest.mark.parametrize("status", ["blocked", "declined", "revoked"])
def test_blocked_declined_and_revoked_authors_are_refused(world, status):
    calls, state = world
    state["inbox"] = connected(status)
    refused(403)
    assert calls.sent == [] and calls.requested == []


def test_an_author_the_viewer_hid_is_refused(world):
    _, state = world
    state["hidden"] = ["Ana"]
    refused(403)


def test_a_viewer_without_a_card_is_refused_with_a_clear_message(world):
    _, state = world
    state["mine"] = None
    assert "Create your Card" in refused(422)


def test_replying_to_your_own_item_is_refused(world):
    _, state = world
    state["author"] = {"owner_user_id": UID}
    refused(422)
    refused(422, item_id="ask:me:whatever")


def test_an_author_who_is_unpublished_or_unclaimed_is_not_found(world):
    _, state = world
    state["author"] = None
    refused(404)


def test_an_item_that_is_not_in_the_feed_is_not_found(world):
    refused(404, item_id="ask:ana:2020-01-01T00:00:00+00:00")
    refused(404, item_id="ask:nobody-here:x")


def test_malformed_item_ids_are_refused(world):
    for bad in ("nonsense", "ask:ana", "bogus:ana:key", "ask::key"):
        refused(422, item_id=bad)


# --- Events -------------------------------------------------------------------------------------

def test_a_reply_records_kind_channel_and_age_but_never_the_message(world):
    calls, _ = world
    reply()
    ((name, kw),) = calls.events
    assert name == "feed_reply"
    assert kw["handle"] == "ana"
    assert kw["meta"] == {"kind": "ask", "channel": "request", "earlier": False, "age_hours": 24}
    assert "secret-words-123" not in json.dumps(calls.events, default=str)


def test_refused_replies_record_nothing(world):
    calls, state = world
    state["inbox"] = connected("blocked")
    refused(403)
    assert calls.events == []


def test_an_event_failure_never_breaks_the_reply(world, monkeypatch):
    calls, _ = world
    monkeypatch.setattr(events, "emit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    assert reply()["channel"] == "request"
    feed.record_view(None, {"items": []}, filter="all", offset=0)         # does not raise either


def test_feed_events_are_server_only_so_the_public_endpoint_cannot_forge_them():
    assert {"feed_view", "feed_reply"} <= events.SERVER_EVENTS
    assert not {"feed_view", "feed_reply"} & events.ALLOWED_EVENTS


def test_a_feed_view_records_counts_per_kind(world):
    calls, _ = world
    page = feed.feed_for_user(UID, now=NOW)
    feed.record_view(None, page, filter="all", offset=0)
    ((name, kw),) = calls.events
    assert name == "feed_view"
    assert kw["meta"]["n"] == len(page["items"]) and kw["meta"]["kinds"]["ask"] == 2
    assert kw["meta"]["filter"] == "all" and kw["meta"]["offset"] == 0


# --- The route ----------------------------------------------------------------------------------

def client(monkeypatch):
    monkeypatch.setattr(config, "MEMORY_SERVICE_TOKEN", "memory-feed-test")
    app = FastAPI()
    app.include_router(routes.router, prefix="/cards")
    return TestClient(app), {"Authorization": "Bearer memory-feed-test", "X-Zynd-User": UID}


def test_the_reply_route_needs_a_session(monkeypatch):
    app, _ = client(monkeypatch)
    body = {"item_id": "ask:ana:x", "message": "hi"}
    assert app.post("/cards/feed/reply", json=body).status_code == 401
    assert app.post("/cards/feed/reply", json=body, headers={"Authorization": "Bearer junk"}).status_code == 403


def test_the_reply_route_validates_the_body(monkeypatch):
    app, headers = client(monkeypatch)
    monkeypatch.setattr(routes.feed, "reply_to_item", lambda *a, **k: {"channel": "dm"})
    post = lambda body: app.post("/cards/feed/reply", json=body, headers=headers).status_code
    assert post({"item_id": "ask:ana:x", "message": "   "}) == 422
    assert post({"item_id": "ask:ana:x", "message": "x" * 2001}) == 422
    assert post({"item_id": "x" * 201, "message": "hi"}) == 422
    assert post({"item_id": "ask:ana:x", "message": "hi", "channel": "dm"}) == 422       # the client cannot pick one
    assert post({"item_id": "ask:ana:x", "message": "hi", "client_id": "nope"}) == 422
    assert post({"item_id": "ask:ana:x", "message": "x" * 2000}) == 200


def test_the_reply_route_passes_the_stripped_message_and_the_bound_user(monkeypatch):
    app, headers = client(monkeypatch)
    seen = {}
    monkeypatch.setattr(routes.feed, "reply_to_item", lambda uid, item, msg, cid: seen.update(uid=uid, item=item, msg=msg, cid=cid) or {"channel": "dm"})
    response = app.post("/cards/feed/reply", headers=headers, json={
        "item_id": "ask:ana:x", "message": "  hello  ", "client_id": "00000000-0000-4000-8000-000000000009"})
    assert response.status_code == 200
    assert seen == {"uid": UID, "item": "ask:ana:x", "msg": "hello", "cid": "00000000-0000-4000-8000-000000000009"}
