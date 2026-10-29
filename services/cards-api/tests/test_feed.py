"""The action feed (services/feed.py, api/feed.py): what each source turns into, who is left out,
how items are ranked, and that the endpoint needs a session. build_feed is pure, so these tests use
fake cards and a fixed `now` and touch no database."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
from api import feed as routes
from models.card import AgentProfileCard
from services import card_cache, feed, feed_github, match_prefs, network

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
UID = "00000000-0000-0000-0000-000000000001"


def ago(**delta) -> str:
    return (NOW - timedelta(**delta)).isoformat()


def row(handle, *, name=None, unit=None, claimed=True, published_days=None, **card):
    """A snapshot-shaped row. Card fields are given as keyword arguments (beacon, zynd_memory, ...)."""
    card.setdefault("identity", {"name": name or handle.title(), "headline": f"{handle} headline", "location": "Pune",
                                 "avatar_url": "", "links": card.pop("links", {})})
    model = AgentProfileCard.model_validate({"id": f"id-{handle}", "handle": handle, **card})
    published = (NOW - timedelta(days=published_days)).isoformat() if published_days is not None else ""
    return {"id": f"id-{handle}", "handle": handle, "model": model, "unit": unit or [], "claimed": claimed,
            "published_at": published}


def beacon(text="Looking for a React developer", days_old=1, lives_days=7):
    created = NOW - timedelta(days=days_old)
    return {"text": text, "created_at": created.isoformat(), "expires_at": (created + timedelta(days=lives_days)).isoformat()}


def fact(text, *, approved_days=1, predicate="is_working_on"):
    return {"predicate": predicate, "object": text, "approved_at": ago(days=approved_days), "source": "memory"}


def page(rows, *, viewer=None, connections=None, blocked=None, github=None, **kw):
    return feed.build_feed(viewer or feed.Viewer(handle="me", card_id="id-me"), rows, connections or {}, blocked or set(),
                           github or {}, NOW, **kw)


def kinds(result):
    return [(i["kind"], i["author"]["handle"]) for i in result["items"]]


# --- Each source ------------------------------------------------------------------------------

def test_a_live_beacon_becomes_an_ask_stamped_with_its_creation_time():
    result = page([row("ana", beacon=beacon("Looking for a designer", days_old=2))])
    (item,) = result["items"]
    assert item["kind"] == "ask"
    assert item["content"] == {"text": "Looking for a designer"}
    assert item["at"] == ago(days=2)
    assert item["author"]["handle"] == "ana"
    assert item["author"]["name"] == "Ana"
    assert item["connection"] is None


def test_an_expired_beacon_makes_no_ask():
    assert page([row("ana", beacon=beacon(days_old=9, lives_days=7))])["items"] == []


def test_is_working_on_facts_become_items_and_plain_working_on_strings_do_not():
    result = page([row("ana", working_on=["Plain string, no timestamp"], zynd_memory=[
        fact("A voice agent for clinics"), fact("Has skill", predicate="has_skill")])])
    assert [(i["kind"], i["content"]["text"]) for i in result["items"]] == [("working_on", "A voice agent for clinics")]


def test_expired_and_out_of_window_facts_are_excluded():
    expired = fact("Old thing", approved_days=20)            # is_working_on lives 14 days
    result = page([row("ana", zynd_memory=[expired, fact("Fresh thing", approved_days=2)])])
    assert [i["content"]["text"] for i in result["items"]] == ["Fresh thing"]


def test_exploring_items_show_title_and_link_inside_the_window():
    clip = {"url": "https://example.com/paper", "title": "A paper", "note": "worth a read", "kind": "paper", "added_at": ago(days=1)}
    old = {"url": "https://example.com/old", "title": "Old", "kind": "link", "added_at": ago(days=40)}
    result = page([row("ana", exploring=[clip, old])])
    (item,) = result["items"]
    assert item["kind"] == "exploring"
    assert item["content"] == {"title": "A paper", "url": "https://example.com/paper", "note": "worth a read", "kind": "paper"}


def test_a_recently_published_card_is_a_joined_item_with_headline_and_topics():
    result = page([row("ana", published_days=3, can_help_with=["Rust", "Hiring", "Pricing", "Fundraising"])])
    (item,) = result["items"]
    assert item["kind"] == "joined"
    assert item["content"] == {"headline": "ana headline", "can_help_with": ["Rust", "Hiring", "Pricing"]}
    assert item["reason"] == feed.REASON_NEW
    assert page([row("bob", published_days=45)])["items"] == []


def test_unclaimed_cards_take_no_part_because_they_cannot_be_messaged():
    assert page([row("ana", claimed=False, beacon=beacon(), published_days=1)])["items"] == []


def test_github_items_come_from_the_cache_and_recent_ones_are_not_marked_earlier():
    events = [
        {"id": "1", "type": "release", "repo": "ana/lib", "title": "v1.0", "url": "https://github.com/ana/lib/releases/tag/v1.0", "at": ago(days=1)},
        {"id": "2", "type": "pull_request", "repo": "x/y", "title": "Fix bug", "url": "https://github.com/x/y/pull/3", "at": ago(days=60)},
    ]
    result = page([row("ana")], github={"ana": events})
    item = result["items"][0]
    assert item["kind"] == "github" and item["earlier"] is False
    assert item["content"] == {"type": "release", "repo": "ana/lib", "title": "v1.0", "url": "https://github.com/ana/lib/releases/tag/v1.0"}
    assert [i["earlier"] for i in result["items"]] == [False, True]      # the 60-day-old one comes after


def test_a_post_shows_a_short_preview_and_a_link_not_the_full_text():
    long = " ".join(["word"] * 150)
    samples = [{"platform": "linkedin", "excerpt": long, "url": "https://www.linkedin.com/posts/ana-1", "posted_at": "2026-10-25"}]
    (item,) = page([row("ana", writing_samples=samples)])["items"]
    assert item["kind"] == "post"
    assert item["content"]["platform"] == "linkedin"
    assert item["content"]["url"] == "https://www.linkedin.com/posts/ana-1"
    preview = item["content"]["preview"]
    assert len(preview) <= feed.POST_PREVIEW_CHARS + 1 and preview.endswith("…")
    assert preview[:-1].rstrip().endswith("word")          # cut on a word boundary


def test_posts_without_a_usable_date_or_outside_the_window_are_skipped():
    base = {"platform": "x", "excerpt": "Shipped it", "url": "https://x.com/ana/status/1"}
    samples = [{**base, "posted_at": ""}, {**base, "url": "https://x.com/ana/status/2", "posted_at": "not a date"},
               {**base, "url": "https://x.com/ana/status/3", "posted_at": "2025-01-01"},
               {**base, "platform": "blog", "url": "https://x.com/ana/status/4", "posted_at": "2026-10-27"}]
    assert page([row("ana", writing_samples=samples)])["items"] == []


def test_preview_keeps_short_text_whole_and_trims_long_text_on_a_word():
    assert feed.preview("  short   post ") == "short post"
    out = feed.preview("alpha beta gamma " * 30, limit=50)
    assert out.endswith("…") and len(out) <= 51
    assert out[:-1] in ("alpha beta gamma alpha beta gamma alpha beta", "alpha beta gamma alpha beta gamma alpha")


# --- Who is left out --------------------------------------------------------------------------

def test_the_viewers_own_card_is_excluded():
    rows = [row("me", beacon=beacon()), row("ana", beacon=beacon())]
    assert kinds(page(rows)) == [("ask", "ana")]


def test_blocked_authors_are_excluded():
    rows = [row("ana", beacon=beacon()), row("bob", beacon=beacon())]
    assert kinds(page(rows, blocked={"bob"})) == [("ask", "ana")]


def test_declined_and_revoked_connections_hide_the_author_like_a_block():
    inbox = [
        {"id": "c1", "status": "declined", "incoming": True, "partner": {"handle": "ana"}},
        {"id": "c2", "status": "revoked", "incoming": False, "partner": {"handle": "bob"}},
        {"id": "c3", "status": "pending", "incoming": False, "partner": {"handle": "cy"}},
        {"id": "c4", "status": "pending", "incoming": True, "partner": {"handle": "di"}},
    ]
    connections, blocked = feed.connection_maps(inbox)
    assert blocked == {"ana", "bob"}
    rows = [row(h, beacon=beacon()) for h in ("ana", "bob", "cy", "di")]
    result = page(rows, connections=connections, blocked=blocked)
    assert sorted(i["author"]["handle"] for i in result["items"]) == ["cy", "di"]       # pending stays
    assert {i["author"]["handle"]: i["connection"]["incoming"] for i in result["items"]} == {"cy": False, "di": True}


def test_connection_maps_cover_blocks_in_both_directions_and_hidden_handles():
    inbox = [
        {"id": "c1", "status": "accepted", "incoming": False, "partner": {"handle": "Ana"}},
        {"id": "c2", "status": "blocked", "incoming": True, "partner": {"handle": "bob"}},      # bob blocked me
        {"id": "c3", "status": "blocked", "incoming": False, "partner": {"handle": "cy"}},      # I blocked cy
        {"id": "c4", "status": "pending", "incoming": True, "partner": {"handle": "di"}},
    ]
    by_handle, blocked = feed.connection_maps(inbox, hidden_handles=["Eve"])
    assert blocked == {"bob", "cy", "eve"}
    assert by_handle["ana"] == {"id": "c1", "status": "accepted", "incoming": False}
    assert by_handle["di"] == {"id": "c4", "status": "pending", "incoming": True}


# --- Filters, ranking, diversity ---------------------------------------------------------------

def test_the_asks_filter_keeps_only_asks():
    rows = [row("ana", beacon=beacon(), zynd_memory=[fact("Thing")])]
    assert kinds(page(rows, filter="asks")) == [("ask", "ana")]
    assert {k for k, _ in kinds(page(rows))} == {"ask", "working_on"}


def test_the_network_filter_keeps_only_accepted_connections():
    rows = [row("ana", beacon=beacon()), row("bob", beacon=beacon()), row("cy", beacon=beacon())]
    connections = {"ana": {"id": "c1", "status": "accepted", "incoming": False},
                   "bob": {"id": "c2", "status": "pending", "incoming": False}}
    assert kinds(page(rows, connections=connections, filter="network")) == [("ask", "ana")]


def test_each_item_carries_the_viewers_connection_state_with_the_author():
    rows = [row("ana", beacon=beacon()), row("bob", beacon=beacon())]
    connections = {"bob": {"id": "c2", "status": "pending", "incoming": True}}
    by_author = {i["author"]["handle"]: i["connection"] for i in page(rows, connections=connections)["items"]}
    assert by_author == {"ana": None, "bob": {"id": "c2", "status": "pending", "incoming": True}}


def test_a_fresh_connected_item_outranks_a_stale_unrelated_one():
    rows = [row("stale", beacon=beacon("Anything", days_old=1), zynd_memory=[fact("Old", approved_days=12)]),
            row("fresh", zynd_memory=[fact("New", approved_days=0)])]
    connections = {"fresh": {"id": "c", "status": "accepted", "incoming": False}}
    result = page(rows, connections=connections)
    assert result["items"][0]["author"]["handle"] == "fresh"
    assert result["items"][0]["reason"] == feed.REASON_CONNECTED


def test_a_connection_lifts_an_item_over_an_equally_fresh_stranger():
    rows = [row("stranger", zynd_memory=[fact("Thing", approved_days=1)]), row("friend", zynd_memory=[fact("Thing", approved_days=2)])]
    connections = {"friend": {"id": "c", "status": "accepted", "incoming": False}}
    assert [i["author"]["handle"] for i in page(rows, connections=connections)["items"]] == ["friend", "stranger"]


def test_similar_cards_rank_higher_and_say_why():
    viewer = feed.Viewer(handle="me", card_id="id-me", unit=[1.0, 0.0])
    rows = [row("far", unit=[0.0, 1.0], zynd_memory=[fact("Thing", approved_days=1)]),
            row("near", unit=[0.9, 0.436], zynd_memory=[fact("Thing", approved_days=1)])]
    result = page(rows, viewer=viewer)
    assert [i["author"]["handle"] for i in result["items"]] == ["near", "far"]
    assert [i["reason"] for i in result["items"]] == [feed.REASON_SIMILAR, ""]


def test_an_ask_that_overlaps_what_the_viewer_can_help_with_is_boosted():
    me = AgentProfileCard.model_validate({"id": "id-me", "handle": "me", "can_help_with": ["React", "Design systems"]})
    viewer = feed.Viewer(handle="me", card_id="id-me", card=me)
    rows = [row("other", beacon=beacon("Looking for a cofounder in biotech", days_old=0)),
            row("match", beacon=beacon("Need a React developer for a week", days_old=1))]
    result = page(rows, viewer=viewer)
    assert result["items"][0]["author"]["handle"] == "match"
    assert result["items"][0]["reason"] == feed.REASON_CAN_HELP
    assert result["items"][1]["reason"] == ""


def test_one_author_is_capped_per_page_and_the_rest_move_to_later_pages():
    busy = row("busy", zynd_memory=[fact(f"Thing {i}", approved_days=0) for i in range(5)])
    others = [row(f"p{i}", zynd_memory=[fact("Thing", approved_days=3)]) for i in range(3)]
    first = page([busy, *others], limit=4)
    handles = [i["author"]["handle"] for i in first["items"]]
    assert handles.count("busy") == feed.PER_AUTHOR_CAP
    assert first["next_cursor"]
    second = page([busy, *others], limit=4, offset=feed.decode_cursor(first["next_cursor"]))
    assert [i["author"]["handle"] for i in second["items"]].count("busy") == 3       # nothing dropped
    assert second["next_cursor"] is None


def test_pagination_walks_every_item_once_in_a_stable_order():
    rows = [row(f"p{i}", zynd_memory=[fact(f"Thing {i}", approved_days=i % 10)]) for i in range(7)]
    seen, offset = [], 0
    while True:
        result = page(rows, limit=3, offset=offset)
        seen += [i["id"] for i in result["items"]]
        if not result["next_cursor"]:
            break
        offset = feed.decode_cursor(result["next_cursor"])
    assert len(seen) == len(set(seen)) == 7
    assert seen == [i["id"] for i in page(rows, limit=50)["items"]]


def test_item_ids_are_stable_between_calls():
    rows = [row("ana", beacon=beacon(), zynd_memory=[fact("Thing")])]
    assert [i["id"] for i in page(rows)["items"]] == [i["id"] for i in page(rows)["items"]]


def test_cursor_round_trips_and_rejects_foreign_values():
    assert feed.decode_cursor(feed.encode_cursor(40)) == 40
    assert feed.decode_cursor(None) == 0
    for bad in ("!!", "bm90LWEtY3Vyc29y", "by0x"):          # junk, "not-a-cursor", "o-1"
        with pytest.raises(ValueError):
            feed.decode_cursor(bad)


# --- feed_for_user wires the inputs together ---------------------------------------------------

@pytest.fixture
def wired(monkeypatch):
    rows = [row("me", unit=[1.0], beacon=beacon("mine")),
            row("ana", unit=[1.0], beacon=beacon("Need help"), links={"github": "https://github.com/ana-dev"}),
            row("bob", beacon=beacon("blocked person")),
            row("eve", beacon=beacon("hidden person"))]
    monkeypatch.setattr(feed, "published_rows", lambda: rows)
    monkeypatch.setattr(network, "_find_card_for_user", lambda uid: {"id": "id-me", "handle": "me", "card": {}})
    monkeypatch.setattr(network, "get_inbox", lambda uid: {"connections": [
        {"id": "c1", "status": "accepted", "incoming": False, "partner": {"handle": "ana"}},
        {"id": "c2", "status": "blocked", "incoming": True, "partner": {"handle": "bob"}}]})
    monkeypatch.setattr(match_prefs, "get", lambda uid: {"hide_person": ["eve"]})
    asked = []
    monkeypatch.setattr(feed_github, "get", lambda logins: asked.append(logins) or {})
    return asked


def test_feed_for_user_leaves_out_self_blocked_and_hidden_and_asks_the_cache_for_github(wired):
    result = feed.feed_for_user(UID, now=NOW)
    assert kinds(result) == [("ask", "ana")]
    assert result["items"][0]["connection"] == {"id": "c1", "status": "accepted", "incoming": False}
    assert result["viewer"] == {"has_card": True, "handle": "me"}
    assert wired == [["ana-dev"]]                  # only people who can appear are looked up


def test_a_viewer_without_a_card_still_gets_the_feed(wired, monkeypatch):
    monkeypatch.setattr(network, "_find_card_for_user", lambda uid: None)
    result = feed.feed_for_user(UID, now=NOW)
    assert result["viewer"] == {"has_card": False, "handle": None}
    assert ("ask", "ana") in kinds(result)


def test_feed_rows_fall_back_to_the_database_when_the_snapshot_is_too_big(monkeypatch):
    monkeypatch.setattr(card_cache, "snapshot", lambda: None)
    monkeypatch.setattr(feed, "_fallback", None)
    from services import cards as cards_service
    monkeypatch.setattr(cards_service, "list_published_rows", lambda columns=None: [
        {"id": "i1", "handle": "ana", "card": {"id": "i1", "beacon": beacon()}, "embedding": [3, 4], "owner_email": "a@x.test",
         "published_at": ago(days=1)}])
    (only,) = feed.published_rows()
    assert only["handle"] == "ana" and only["claimed"] and only["unit"] == pytest.approx([0.6, 0.8])


# --- The endpoint ------------------------------------------------------------------------------

def client(monkeypatch):
    monkeypatch.setattr(config, "MEMORY_SERVICE_TOKEN", "memory-feed-test")
    app = FastAPI()
    app.include_router(routes.router, prefix="/cards")
    return TestClient(app)


def test_the_feed_needs_a_session(monkeypatch):
    app = client(monkeypatch)
    assert app.get("/cards/feed").status_code == 401
    assert app.get("/cards/feed", headers={"Authorization": "Bearer not-a-session"}).status_code == 403


def test_the_feed_route_passes_filter_limit_and_cursor_for_the_bound_user(monkeypatch):
    app = client(monkeypatch)
    seen = {}
    monkeypatch.setattr(routes.feed, "feed_for_user", lambda uid, **kw: seen.update(uid=uid, **kw) or
                        {"items": [], "next_cursor": None, "viewer": {"has_card": False, "handle": None}})
    response = app.get("/cards/feed", params={"filter": "asks", "limit": 5, "cursor": feed.encode_cursor(10)},
                       headers={"Authorization": "Bearer memory-feed-test", "X-Zynd-User": UID})
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None, "viewer": {"has_card": False, "handle": None}}
    assert seen == {"uid": UID, "filter": "asks", "limit": 5, "offset": 10}


def test_the_feed_route_rejects_bad_parameters(monkeypatch):
    app = client(monkeypatch)
    monkeypatch.setattr(routes.feed, "feed_for_user", lambda uid, **kw: {})
    headers = {"Authorization": "Bearer memory-feed-test", "X-Zynd-User": UID}
    assert app.get("/cards/feed", params={"filter": "everything"}, headers=headers).status_code == 422
    assert app.get("/cards/feed", params={"limit": 51}, headers=headers).status_code == 422
    assert app.get("/cards/feed", params={"cursor": "garbage!"}, headers=headers).status_code == 422
