"""The ask composer's backend: ask kinds and the optional link on the beacon, POST/DELETE /cards/mine/ask,
the posts-per-day limit, the new fields on GET /cards/mine/asks, the feed's kind filter, the digest's
kind label and that the publish event never carries the text. No migration: kind and url live in the
beacon JSON on the card."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api import asks as routes
from api import feed as feed_routes
from models.card import ASK_KINDS, Beacon
from services import asks, beacons, events, feed, owner_home, zynd_memory
from services import digest as digest_service
from tests.asks_support import ASK_1, ASK_2, NOW, OWNER, Db, MissingTablesDb, ask_row, card_row, iso, offer_row, use_db  # noqa: F401
from tests.test_asks import cards_db
from tests.test_feed import beacon as feed_beacon
from tests.test_feed import page, row as feed_row

TEXT = "Building a team for ETHGlobal Bangkok, need a Solidity dev"
LINK = "https://ethglobal.com/events/bangkok"
SECRET_WORDS = "very-private-words-xyz"


def auth(who):
    return {"Authorization": f"Bearer {who}"}


@pytest.fixture
def emitted(monkeypatch):
    calls = []
    monkeypatch.setattr(events, "emit", lambda event, **kw: calls.append((event, kw)))
    return calls


@pytest.fixture
def client(monkeypatch, use_db, emitted):
    """The real routes and the real save_beacon over an in-memory database: ana owns card-a, bob card-b."""
    db = use_db(cards_db())
    monkeypatch.setattr(owner_home, "enabled", lambda: True)
    emails = {"Bearer ana": "ana@x.test", "Bearer bob": "bob@x.test", "Bearer nobody": "nobody@x.test"}

    def principal(authorization):
        if authorization not in emails:
            raise HTTPException(401, "Sign in")
        return type("P", (), {"email": emails[authorization]})()
    monkeypatch.setattr("api.owner_home._principal", principal)
    monkeypatch.setattr(zynd_memory, "ping_revalidate", lambda *a, **k: None)
    routed = []
    monkeypatch.setattr(asks, "schedule_routing", lambda ask_id, row, text: routed.append((ask_id, text)))
    app = FastAPI()
    app.include_router(routes.router, prefix="/cards")
    http = TestClient(app)
    http.routed = routed
    return http, db


# --- The beacon model ---------------------------------------------------------------------------

def stored(**extra):
    return {"text": "Old", "created_at": iso(days=1), "expires_at": (NOW + timedelta(days=5)).isoformat(), **extra}


def test_an_old_beacon_without_kind_or_url_parses_and_reads_as_other():
    old = Beacon.model_validate(stored())
    assert old.kind is None and old.url is None
    assert asks.beacon_details({"beacon": {**stored(), "id": ASK_1}}, ASK_1) == {"kind": None, "url": None}
    assert feed_item(beacon=stored())["content"]["kind"] == "other"


def test_stored_bad_values_read_back_as_none_instead_of_breaking_the_card():
    bad = Beacon.model_validate(stored(kind="crypto-bro", url="javascript:alert(1)"))
    assert bad.kind is None and bad.url is None
    assert Beacon.model_validate(stored(kind="team", url=" https://a.test/x ")).url == "https://a.test/x"
    assert Beacon.model_validate(stored(url="https://a.test/" + "x" * 500)).url is None


def test_every_kind_has_a_label():
    assert list(ASK_KINDS) == ["team", "cofounder", "hiring", "work", "feedback", "users", "investors", "other"]
    assert ASK_KINDS["investors"] == "Raising money" and ASK_KINDS["cofounder"] == "Looking for a co-founder"


# --- POST /cards/mine/ask -----------------------------------------------------------------------

def test_posting_an_ask_saves_the_beacon_with_kind_and_link_and_routes_it(client, emitted):
    http, db = client
    response = http.post("/cards/mine/ask", headers=auth("ana"), json={"kind": "team", "text": f"  {TEXT}  ", "url": LINK})
    assert response.status_code == 200
    body = response.json()
    assert body["ask_id"] == body["beacon"]["id"]
    assert body["beacon"]["text"] == TEXT and body["beacon"]["kind"] == "team" and body["beacon"]["url"] == LINK
    stored_beacon = db.rows("agent_profile_cards")[0]["card"]["beacon"]
    assert stored_beacon["id"] == body["ask_id"] and stored_beacon["kind"] == "team"
    (ask,) = db.rows("asks")
    assert ask["id"] == body["ask_id"] and ask["card_id"] == "card-a" and ask["text"] == TEXT
    assert http.routed == [(body["ask_id"], TEXT)]
    assert [kw["meta"] for name, kw in emitted if name == "ask_published"] == [{"kind": "team", "replaced": False}]


def test_the_link_is_optional(client):
    http, _ = client
    response = http.post("/cards/mine/ask", headers=auth("ana"), json={"kind": "hiring", "text": "Hiring two Go engineers"})
    assert response.status_code == 200 and response.json()["beacon"]["url"] is None


def test_posting_again_replaces_the_live_ask_and_says_so_in_the_event(client, emitted):
    http, db = client
    first = http.post("/cards/mine/ask", headers=auth("ana"), json={"kind": "team", "text": TEXT}).json()
    second = http.post("/cards/mine/ask", headers=auth("ana"), json={"kind": "feedback", "text": "Want feedback on my deck"}).json()
    rows = {r["id"]: r for r in db.rows("asks")}
    assert rows[first["ask_id"]]["end_reason"] == "replaced" and rows[second["ask_id"]].get("ended_at") is None
    assert db.rows("agent_profile_cards")[0]["card"]["beacon"]["id"] == second["ask_id"]
    published = [kw["meta"] for name, kw in emitted if name == "ask_published"]
    assert published == [{"kind": "team", "replaced": False}, {"kind": "feedback", "replaced": True}]


@pytest.mark.parametrize("body", [
    {"kind": "crypto", "text": "x"},                                                  # not a kind
    {"text": "no kind"},                                                              # a kind is required
    {"kind": "team", "text": ""},
    {"kind": "team", "text": "   "},
    {"kind": "team", "text": "x" * 281},
    {"kind": "team", "text": "ok", "url": "javascript:alert(1)"},
    {"kind": "team", "text": "ok", "url": "ftp://files.test/a"},
    {"kind": "team", "text": "ok", "url": "https://a.test/" + "x" * 500},
    {"kind": "team", "text": "ok", "url": "https://a.test/has space"},
    {"kind": "team", "text": "ok", "url": "https://"},
    {"kind": "team", "text": "ok", "owner": "spoof"},                                 # nothing else is read
    {"kind": "team", "text": "ok", "id": ASK_1},
])
def test_bad_bodies_are_422_and_publish_nothing(client, body):
    http, db = client
    assert http.post("/cards/mine/ask", headers=auth("ana"), json=body).status_code == 422
    assert db.rows("asks") == [] and "beacon" not in db.rows("agent_profile_cards")[0]["card"]


def test_280_characters_is_the_most_and_a_blank_link_means_none(client):
    http, _ = client
    ok = http.post("/cards/mine/ask", headers=auth("ana"), json={"kind": "other", "text": "x" * 280, "url": "  "})
    assert ok.status_code == 200 and ok.json()["beacon"]["url"] is None


def test_the_by_handle_beacon_routes_take_kind_and_link_too(client):
    from api import owner_home as owner_routes
    http, db = client
    app = FastAPI()
    app.include_router(owner_routes.router, prefix="/cards")
    old = TestClient(app)
    put = old.put("/cards/by-handle/ana/beacon", headers=auth("ana"), json={"text": "An ask", "kind": "work", "url": LINK})
    assert put.status_code == 200 and put.json()["beacon"]["kind"] == "work" and put.json()["beacon"]["url"] == LINK
    assert old.put("/cards/by-handle/ana/beacon", headers=auth("ana"), json={"text": "An ask", "url": "javascript:1"}).status_code == 422
    assert old.put("/cards/by-handle/ana/beacon", headers=auth("ana"), json={"text": "An ask", "kind": "nope"}).status_code == 422
    assert old.put("/cards/by-handle/ana/beacon", headers=auth("ana"), json={"text": "No kind at all"}).status_code == 200


def test_a_card_that_changed_underneath_is_a_409(client):
    http, db = client
    original = db.table

    def stale(name):
        query = original(name)
        if name == "agent_profile_cards":
            real = query.update
            query.update = lambda payload: real(payload).eq("updated_at", "not-the-version")
        return query
    db.table = stale
    assert http.post("/cards/mine/ask", headers=auth("ana"), json={"kind": "team", "text": TEXT}).status_code == 409
    assert db.rows("asks") == []


def test_only_a_published_card_can_post(client):
    http, db = client
    db.rows("agent_profile_cards")[0]["status"] = "draft"
    assert http.post("/cards/mine/ask", headers=auth("ana"), json={"kind": "team", "text": TEXT}).status_code == 409


# --- Who may call -------------------------------------------------------------------------------

def test_every_route_needs_a_session_and_a_card(client):
    http, _ = client
    assert http.post("/cards/mine/ask", json={"kind": "team", "text": TEXT}).status_code == 401
    assert http.delete("/cards/mine/ask").status_code == 401
    assert http.post("/cards/mine/ask", headers=auth("stranger"), json={"kind": "team", "text": TEXT}).status_code == 401
    assert http.post("/cards/mine/ask", headers=auth("nobody"), json={"kind": "team", "text": TEXT}).status_code == 404
    assert http.delete("/cards/mine/ask", headers=auth("nobody")).status_code == 404


def test_the_card_is_always_the_sessions_own(client):
    http, db = client
    http.post("/cards/mine/ask", headers=auth("bob"), json={"kind": "team", "text": "Bob's ask"})
    cards = {r["handle"]: r["card"] for r in db.rows("agent_profile_cards")}
    assert cards["bob"]["beacon"]["text"] == "Bob's ask" and "beacon" not in cards["ana"]
    assert [r["card_id"] for r in db.rows("asks")] == ["card-b"]


# --- DELETE /cards/mine/ask ---------------------------------------------------------------------

def test_taking_the_ask_down_clears_the_beacon_and_ends_it_as_dismissed(client):
    http, db = client
    posted = http.post("/cards/mine/ask", headers=auth("ana"), json={"kind": "team", "text": TEXT}).json()
    assert http.delete("/cards/mine/ask", headers=auth("ana")).status_code == 204
    assert db.rows("agent_profile_cards")[0]["card"]["beacon"] is None
    (ask,) = db.rows("asks")
    assert ask["id"] == posted["ask_id"] and ask["end_reason"] == "dismissed" and ask["ended_at"]


def test_taking_down_when_nothing_is_live_is_fine(client):
    http, _ = client
    assert http.delete("/cards/mine/ask", headers=auth("ana")).status_code == 204


# --- The posts-per-day limit --------------------------------------------------------------------

def posted_ago(n, **delta):
    """n asks of card-a made `delta` ago, by the real clock (save_beacon reads it)."""
    when = (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()
    return [ask_row(f"00000000-0000-4000-8000-0000000001{i:02d}", "card-a", ended_at=when, end_reason="replaced", created_at=when)
            for i in range(n)]


def test_the_sixth_publish_in_24_hours_is_a_429_and_stores_nothing(monkeypatch, use_db, emitted):
    db = use_db(cards_db(asks=posted_ago(asks.ASK_POSTS_PER_DAY, hours=23)))
    with pytest.raises(HTTPException) as caught:
        beacons.save_beacon("ana", "ana@x.test", TEXT, "team", None)
    assert caught.value.status_code == 429 and "5 asks a day" in caught.value.detail
    assert len(db.rows("asks")) == 5 and "beacon" not in db.rows("agent_profile_cards")[0]["card"]
    assert not [e for e in emitted if e[0] == "ask_published"]


def test_four_in_24_hours_still_leaves_room_for_the_fifth(monkeypatch, use_db, emitted):
    use_db(cards_db(asks=posted_ago(asks.ASK_POSTS_PER_DAY - 1, hours=23)))
    monkeypatch.setattr(asks, "schedule_routing", lambda *a: None)
    assert beacons.save_beacon("ana", "ana@x.test", TEXT, "team", None)["kind"] == "team"


def test_posts_older_than_24_hours_and_other_cards_posts_do_not_count(monkeypatch, use_db, emitted):
    others = [ask_row(f"00000000-0000-4000-8000-0000000002{i:02d}", "card-b", created_at=datetime.now(timezone.utc).isoformat())
              for i in range(6)]
    use_db(cards_db(asks=posted_ago(5, hours=25) + others))
    monkeypatch.setattr(asks, "schedule_routing", lambda *a: None)
    assert beacons.save_beacon("ana", "ana@x.test", TEXT, "team", None)["text"] == TEXT


def test_the_limit_is_a_429_over_http_and_taking_down_is_never_limited(client):
    http, db = client
    db.tables["asks"] = posted_ago(asks.ASK_POSTS_PER_DAY, hours=1)
    assert http.post("/cards/mine/ask", headers=auth("ana"), json={"kind": "team", "text": TEXT}).status_code == 429
    assert http.delete("/cards/mine/ask", headers=auth("ana")).status_code == 204


def test_the_limit_is_skipped_when_the_asks_tables_are_missing(monkeypatch, use_db, emitted):
    use_db(cards_db(MissingTablesDb))
    monkeypatch.setattr(asks, "schedule_routing", lambda *a: None)
    value = beacons.save_beacon("ana", "ana@x.test", TEXT, "team", None)
    assert value["text"] == TEXT


# --- The event never carries the text -----------------------------------------------------------

def test_the_publish_event_has_only_kind_and_replaced(client, emitted):
    http, _ = client
    http.post("/cards/mine/ask", headers=auth("ana"), json={"kind": "investors", "text": SECRET_WORDS, "url": LINK})
    (event,) = [e for e in emitted if e[0] == "ask_published"]
    assert event[1]["meta"] == {"kind": "investors", "replaced": False}
    assert SECRET_WORDS not in repr(emitted) and LINK not in repr(emitted)


def test_the_event_is_one_only_the_server_can_emit():
    assert "ask_published" in events.SERVER_EVENTS and "ask_published" not in events.ALLOWED_EVENTS


# --- GET /cards/mine/asks -----------------------------------------------------------------------

def listing_db(use_db, asks_rows, **tables):
    beacon = {"id": ASK_1, "text": "Need a React developer", "kind": "team", "url": LINK, "created_at": iso(days=1),
              "expires_at": (NOW + timedelta(days=6)).isoformat()}
    return use_db(Db(agent_profile_cards=[
        card_row("card-a", "ana", "Ana Rao", owner_user_id=OWNER, beacon=beacon),
        card_row("card-b", "bob", "Bob Lee"), card_row("card-c", "cy", "Cy Park")], asks=asks_rows, **tables))


def test_the_owners_list_carries_kind_link_routed_and_offer_count(use_db):
    listing_db(use_db, [ask_row(ASK_1, created_days=1)],
               ask_offers=[offer_row("card-b"), offer_row("card-c", helper_user_id="u-c")],
               ask_routes=[{"ask_id": ASK_1, "helper_card_id": f"h{i}"} for i in range(3)])
    (live,) = asks.list_for_owner({"id": "card-a", "handle": "ana", "card": {"beacon": {
        "id": ASK_1, "text": "Need a React developer", "kind": "team", "url": LINK,
        "created_at": iso(days=1), "expires_at": (NOW + timedelta(days=6)).isoformat()}}}, NOW)["asks"]
    assert live["kind"] == "team" and live["url"] == LINK
    assert live["routed"] == 3 and live["offer_count"] == 2 and len(live["offers"]) == 2


def test_the_list_costs_four_queries_however_many_asks(use_db):
    many = [ask_row(f"00000000-0000-4000-8000-0000000003{i:02d}", created_days=8 + i % 3, lives_days=7, text=f"Ask {i}") for i in range(8)]
    db = listing_db(use_db, many, ask_offers=[offer_row("card-b", ask_id=m["id"], helper_user_id=f"u{i}") for i, m in enumerate(many)],
                    ask_routes=[{"ask_id": m["id"], "helper_card_id": "card-b"} for m in many])
    listed = asks.list_for_owner({"id": "card-a", "handle": "ana", "card": {}}, NOW)["asks"]
    assert len(listed) == 8 and all(a["routed"] == 1 and a["offer_count"] == 1 for a in listed)
    assert db.asked == ["asks", "ask_offers", "agent_profile_cards", "ask_routes"]


def test_an_ask_that_is_no_longer_the_beacon_has_no_kind(use_db):
    listing_db(use_db, [ask_row(ASK_2, created_days=9, lives_days=7)])
    (ended,) = asks.list_for_owner({"id": "card-a", "handle": "ana", "card": {"beacon": {"id": ASK_1, "kind": "team", "text": "x"}}}, NOW)["asks"]
    assert ended["status"] == "ended" and ended["kind"] is None and ended["url"] is None and ended["routed"] == 0


def test_the_list_route_returns_the_new_fields(client):
    http, db = client
    posted = http.post("/cards/mine/ask", headers=auth("ana"), json={"kind": "cofounder", "text": TEXT, "url": LINK}).json()
    db.tables["ask_routes"] = [{"ask_id": posted["ask_id"], "helper_card_id": "card-b"}]
    (live,) = http.get("/cards/mine/asks", headers=auth("ana")).json()["asks"]
    assert live["id"] == posted["ask_id"] and live["kind"] == "cofounder" and live["url"] == LINK
    assert live["routed"] == 1 and live["offer_count"] == 0


# --- The feed -----------------------------------------------------------------------------------

def feed_item(**card):
    (item,) = page([feed_row("ana", **card)])["items"]
    return item


def kind_beacon(kind, url=None, text="An ask"):
    return {**feed_beacon(text), "kind": kind, "url": url}


def test_ask_items_carry_kind_and_link():
    item = feed_item(beacon=kind_beacon("cofounder", LINK))
    assert item["content"] == {"text": "An ask", "kind": "cofounder", "url": LINK}


def test_the_kind_filter_keeps_only_asks_of_that_kind():
    rows = [feed_row("ana", beacon=kind_beacon("team")), feed_row("bob", beacon=kind_beacon("hiring")),
            feed_row("cy", beacon=feed_beacon("Old ask without a kind")), feed_row("di", beacon=kind_beacon("team"))]
    handles = lambda **kw: sorted(i["author"]["handle"] for i in page(rows, filter="asks", **kw)["items"])
    assert handles() == ["ana", "bob", "cy", "di"]
    assert handles(kind="team") == ["ana", "di"]
    assert handles(kind="hiring") == ["bob"]
    assert handles(kind="other") == ["cy"]                      # an old ask with no kind is "other"
    assert handles(kind="investors") == []


def test_other_items_are_not_asks_and_never_match_a_kind():
    rows = [feed_row("ana", beacon=kind_beacon("team"), published_days=1)]
    assert [i["kind"] for i in page(rows, filter="asks", kind="team")["items"]] == ["ask"]


def feed_client(monkeypatch):
    seen = {}
    monkeypatch.setattr(feed_routes, "_uid", lambda authorization, x_zynd_user: "user-1")
    monkeypatch.setattr(feed_routes.feed, "feed_for_user", lambda uid, **kw: seen.update(kw) or
                        {"items": [], "next_cursor": None, "viewer": {"has_card": True, "handle": "me"}})
    monkeypatch.setattr(feed_routes.feed, "record_view", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(feed_routes.router, prefix="/cards")
    return TestClient(app), seen


def test_the_feed_route_validates_and_forwards_the_kind(monkeypatch):
    http, seen = feed_client(monkeypatch)
    head = auth("t")
    assert http.get("/cards/feed", params={"filter": "asks", "kind": "team"}, headers=head).status_code == 200
    assert seen["kind"] == "team" and seen["filter"] == "asks"
    assert http.get("/cards/feed", params={"filter": "asks"}, headers=head).status_code == 200 and seen["kind"] is None
    assert http.get("/cards/feed", params={"filter": "asks", "kind": "crypto"}, headers=head).status_code == 422
    assert http.get("/cards/feed", params={"kind": "team"}, headers=head).status_code == 422             # only with filter=asks
    assert http.get("/cards/feed", params={"filter": "network", "kind": "team"}, headers=head).status_code == 422


# --- The morning digest -------------------------------------------------------------------------

def digest_pair(routed):
    extras = {"asks": {"routed": routed, "prompts": [], "credits": [], "marks": {}}}
    return (digest_service.render_digest("alice", None, None, name="Alice", extras=extras),
            digest_service.render_digest_html("alice", None, None, name="Alice", extras=extras))


def test_the_digest_prefixes_an_ask_with_its_kind_label_when_it_has_one():
    text, html = digest_pair([{"ask_id": "a", "text": "Need a designer", "asker_name": "Bob", "asker_handle": "bob", "kind": "team"},
                              {"ask_id": "b", "text": "Old style ask", "asker_name": "Cy", "asker_handle": "cy", "kind": None}])
    assert "- Building a team · Bob: Need a designer" in text and "- Cy: Old style ask" in text
    assert "Building a team: Need a designer" in html and "Something else" not in html


def test_the_digest_label_is_escaped(monkeypatch):
    monkeypatch.setitem(ASK_KINDS, "team", '<script>alert(1)</script> & co')
    _, html = digest_pair([{"ask_id": "a", "text": "Need a designer", "asker_name": "Bob", "asker_handle": "bob", "kind": "team"}])
    assert "<script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt; &amp; co" in html


def test_the_digest_reads_the_kind_from_the_askers_beacon(use_db):
    beacon = {"id": ASK_1, "text": "Need a React developer", "kind": "hiring", "created_at": iso(days=1),
              "expires_at": (NOW + timedelta(days=6)).isoformat()}
    use_db(Db(agent_profile_cards=[card_row("card-a", "ana", "Ana Rao", beacon=beacon), card_row("card-b", "bob", "Bob Lee")],
              asks=[ask_row(ASK_1, "card-a", created_days=1)],
              ask_routes=[{"ask_id": ASK_1, "helper_card_id": "card-b", "digest_sent_at": None, "created_at": iso(hours=2)}]))
    items = asks.digest_items({"id": "card-b", "handle": "bob"}, set(), NOW)
    assert [r["kind"] for r in items["routed"]] == ["hiring"]
