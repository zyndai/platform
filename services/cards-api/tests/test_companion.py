from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

import config
from api import companion as routes
from api.auth import Principal, verify_supabase_jwt
from models.card import AgentProfileCard
from services import companion, owner_home
from services.signals import derive_public_signals
from tests.fake_supabase import FakeSupabase

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


class Db(FakeSupabase):
    """The fake plus the two things the companion service needs from it: the column defaults
    cards.companion_devices has, and the companion_save_fields function."""

    def __init__(self, **tables):
        super().__init__(**tables)
        self.saves: list[dict] = []
        self.save_errors: list[str] = []

    def new_row(self, name, item):
        row = super().new_row(name, item)
        if name == "companion_devices":
            row.setdefault("last_used_at", row["created_at"])
            row.setdefault("revoked_at", None)
        return row

    def rpc(self, name, params):
        assert name == "companion_save_fields"
        def run():
            if self.save_errors:
                raise APIError({"code": self.save_errors.pop(0), "message": "boom", "details": None, "hint": None})
            self.saves.append(params)
            return SimpleNamespace(data={**(self.card or {}), **params["p_patch"], "handle": params["p_handle"],
                                         "updated_at": "2026-10-27T12:00:00+00:00"})
        return SimpleNamespace(execute=run)

    card: dict | None = None


@pytest.fixture
def db(monkeypatch):
    fake = Db()
    fake.card = {"working_on": ["Old thing"], "exploring": []}
    monkeypatch.setattr(config, "get_supabase", lambda: fake)
    monkeypatch.setattr(owner_home, "current_row", lambda email: (
        {"handle": "alice", "status": "published", "card": fake.card, "updated_at": "t"} if email == "alice@test.invalid" else None))
    monkeypatch.setattr(companion, "ping_revalidate", lambda handle: None)
    return fake


# ── Which links may go on a public card ──────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("https://github.com/zyndai/platform", "https://github.com/zyndai/platform"),
    ("https://www.Example.com/a?utm_source=x&b=1&fbclid=z#frag", "https://www.example.com/a?b=1"),
    ("https://example.com", "https://example.com/"),
    ("https://example.com:443/p", "https://example.com/p"),
    ("https://example.com:8443/p", "https://example.com:8443/p"),
    ("https://x.com/dil/status/123?s=20&t=abc", "https://x.com/dil/status/123"),
    ("https://youtu.be/abc?t=42&si=zzz", "https://youtu.be/abc?t=42&si=zzz"),
    ("  https://8.8.8.8/x  ", "https://8.8.8.8/x"),
])
def test_clean_url_keeps_the_public_form(raw, expected):
    assert companion.clean_url(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "   ", "javascript:alert(1)", "file:///etc/passwd", "chrome://extensions", "ftp://example.com/x",
    "http://localhost:3000/", "http://127.0.0.1/", "http://10.0.0.5/admin", "http://192.168.1.1/",
    "http://169.254.169.254/latest", "http://[::1]/", "http://0.0.0.0/", "http://intranet/wiki",
    "http://jira.corp/browse/X-1", "https://build.internal/job/1", "https://nas.local/", "http://2130706433/",
    "https://user:pass@example.com/", "https://example.com@evil.test/", "https://example.com:99999/",
    "https://example.com/" + "a" * 600,
])
def test_clean_url_refuses_what_must_not_be_public(raw):
    with pytest.raises(ValueError):
        companion.clean_url(raw)


def test_url_key_treats_spellings_of_one_page_as_equal():
    assert companion.url_key("https://www.a.com/p/") == companion.url_key("https://a.com/p")
    assert companion.url_key("https://a.com/p?x=1") != companion.url_key("https://a.com/p?x=2")


# ── The two lists ────────────────────────────────────────────────────────────

def test_working_on_goes_on_top_without_duplicates_and_stays_within_the_public_cap():
    out = companion.add_working_on_line(["a", "B", "c", "d"], "  b ")
    assert out == ["b", "a", "c", "d"]
    out = companion.add_working_on_line(["a", "b", "c", "d"], "new")
    assert out == ["new", "a", "b", "c"]
    assert len(out) == companion.WORKING_ON_CAP
    with pytest.raises(ValueError):
        companion.add_working_on_line(["a"], "   ")
    assert companion.remove_working_on_line(["a", "B"], "b") == ["a"]


def test_working_on_text_loses_control_characters_and_is_cut():
    out = companion.add_working_on_line([], "x\n\ty\x00" + "z" * 300)
    assert out[0].startswith("x y ") and len(out[0]) == companion.WORKING_ON_TEXT_MAX


def test_exploring_bumps_a_repeat_instead_of_duplicating_and_is_capped():
    first = companion.build_item("https://a.com/p?utm_source=x", "A page", "article", "", NOW)
    again = companion.build_item("https://www.a.com/p/", "A page, again", "blog", "note", NOW)
    cur = companion.add_exploring_item(companion.add_exploring_item([], first), again)
    assert [(i["title"], i["kind"]) for i in cur] == [("A page, again", "blog")]
    many = []
    for n in range(companion.EXPLORING_MAX + 3):
        many = companion.add_exploring_item(many, companion.build_item(f"https://a.com/{n}", "t", "link", "", NOW))
    assert len(many) == companion.EXPLORING_MAX and many[0]["url"].endswith(f"/{companion.EXPLORING_MAX + 2}")
    assert companion.remove_exploring_item(many, "https://a.com/10")[0]["url"].endswith("/9")


def test_build_item_normalises_kind_title_and_note():
    item = companion.build_item("https://www.site.com/x", "", "podcast", "n" * 500, NOW)
    assert item.kind == "link" and item.title == "site.com" and len(item.note) == companion.NOTE_MAX
    assert item.added_at == NOW.isoformat()


# ── Public card ──────────────────────────────────────────────────────────────

def test_a_clip_stops_showing_on_the_public_card_after_30_days_but_stays_stored():
    fresh = {"url": "https://a.com/new", "added_at": (NOW - timedelta(days=29)).isoformat()}
    stale = {"url": "https://a.com/old", "added_at": (NOW - timedelta(days=31)).isoformat()}
    undated = {"url": "https://a.com/undated"}
    card = AgentProfileCard(id="c", exploring=[fresh, stale, undated])
    assert len(card.exploring) == 3
    assert [i.url for i in derive_public_signals(card, NOW).exploring] == ["https://a.com/new"]


def test_a_stored_entry_that_is_not_a_web_link_cannot_break_the_card():
    card = AgentProfileCard(id="c", exploring=[{"url": "javascript:alert(1)"}, "junk", None, {"url": "https://a.com/ok"}])
    assert [i.url for i in card.exploring] == ["https://a.com/ok"]


# ── Device tokens ────────────────────────────────────────────────────────────

def test_pairing_stores_only_a_hash_of_the_token(db):
    token, row = companion.create_device("Alice@Test.invalid", "Chrome on Linux")
    assert token.startswith("zdc_") and len(token) > 40
    stored = db.rows("companion_devices")[0]
    assert stored["token_hash"] == companion.hash_token(token) and token not in str(stored)
    assert stored["owner_email"] == "alice@test.invalid"
    assert companion.device_for_token(token)["id"] == row["id"]


def test_a_token_that_is_unknown_revoked_or_idle_is_refused(db):
    token, row = companion.create_device("alice@test.invalid", "x")
    for bad in (None, "", "zdc_nope", "eyJhbGciOiJFUzI1NiJ9.e30.sig", token[:-1] + "x", "zdc_" + "a" * 300):
        assert companion.device_for_token(bad) is None
    db.rows("companion_devices")[0]["last_used_at"] = (datetime.now(timezone.utc) - timedelta(days=companion.TOKEN_IDLE_DAYS + 1)).isoformat()
    assert companion.device_for_token(token) is None
    db.rows("companion_devices")[0]["last_used_at"] = datetime.now(timezone.utc).isoformat()
    assert companion.device_for_token(token) is not None
    assert companion.revoke_device("alice@test.invalid", row["id"])
    assert companion.device_for_token(token) is None


def test_use_refreshes_last_used_only_when_it_is_stale(db):
    token, _ = companion.create_device("alice@test.invalid", "x")
    recent = datetime.now(timezone.utc).isoformat()
    db.rows("companion_devices")[0]["last_used_at"] = recent
    companion.device_for_token(token)
    assert db.rows("companion_devices")[0]["last_used_at"] == recent
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    db.rows("companion_devices")[0]["last_used_at"] = old
    companion.device_for_token(token)
    assert db.rows("companion_devices")[0]["last_used_at"] > old


def test_pairing_an_eleventh_browser_revokes_the_least_recently_used(db):
    tokens = [companion.create_device("alice@test.invalid", f"b{n}")[0] for n in range(companion.MAX_DEVICES)]
    for n, row in enumerate(db.rows("companion_devices")):
        row["last_used_at"] = (datetime.now(timezone.utc) - timedelta(days=10 - n * 0.5)).isoformat()
    companion.create_device("alice@test.invalid", "newest")
    live = [d["label"] for d in companion.list_devices("alice@test.invalid")]
    assert len(live) == companion.MAX_DEVICES and "b0" not in live and "newest" in live
    assert companion.device_for_token(tokens[0]) is None


def test_one_person_cannot_list_or_revoke_anothers_devices(db):
    _, row = companion.create_device("alice@test.invalid", "mine")
    assert companion.list_devices("bob@test.invalid") == []
    assert not companion.revoke_device("bob@test.invalid", row["id"])
    assert all("token_hash" not in d for d in companion.list_devices("alice@test.invalid"))


# ── Saving to the card ───────────────────────────────────────────────────────

def test_save_sends_the_stored_list_as_the_expected_value(db):
    companion.set_working_on("alice@test.invalid", "Companion")
    assert db.saves == [{"p_email": "alice@test.invalid", "p_handle": "alice",
                         "p_patch": {"working_on": ["Companion", "Old thing"]}, "p_expected": {"working_on": ["Old thing"]}}]


def test_a_save_that_changes_nothing_writes_nothing(db):
    companion.drop_working_on("alice@test.invalid", "not there")
    assert db.saves == []


def test_a_conflict_is_retried_once_on_the_fresh_card_then_reported(db):
    db.save_errors = ["40001"]
    companion.set_working_on("alice@test.invalid", "Companion")
    assert len(db.saves) == 1
    db.save_errors = ["40001", "40001"]
    with pytest.raises(companion.CompanionError) as err:
        companion.set_working_on("alice@test.invalid", "Again")
    assert err.value.status == 409


@pytest.mark.parametrize("code,status", [("42501", 403), ("22023", 422)])
def test_database_refusals_become_clear_errors(db, code, status):
    db.save_errors = [code]
    with pytest.raises(companion.CompanionError) as err:
        companion.set_working_on("alice@test.invalid", "x")
    assert err.value.status == status


def test_no_card_means_nothing_to_write(db):
    with pytest.raises(companion.CompanionError) as err:
        companion.set_working_on("nobody@test.invalid", "x")
    assert err.value.status == 404


def test_a_private_link_is_refused_before_anything_is_written(db):
    with pytest.raises(ValueError):
        companion.add_exploring("alice@test.invalid", "http://localhost:3000/secret", "t", "link", "")
    assert db.saves == []


# ── Routes ───────────────────────────────────────────────────────────────────

@pytest.fixture
def client(db, monkeypatch):
    app = FastAPI()
    app.include_router(routes.router, prefix="/cards/companion")
    monkeypatch.setattr(routes, "_principal", lambda authorization: Principal(
        email="alice@test.invalid", sub="u1", iss="i") if authorization == "Bearer website-session" else (_ for _ in ()).throw(
        routes.HTTPException(401, "Unauthorized")))
    monkeypatch.setattr(companion, "profile", lambda email: (
        {"handle": "alice", "name": "Alice"} if email == "alice@test.invalid" else (_ for _ in ()).throw(companion.CompanionError(404, "Create your card first"))))
    return TestClient(app)


def pair(client):
    res = client.post("/cards/companion/pair", json={"label": "Chrome"}, headers={"Authorization": "Bearer website-session"})
    assert res.status_code == 200, res.text
    return res.json()


def test_pairing_needs_a_signed_in_website_session(client):
    assert client.post("/cards/companion/pair", json={}).status_code == 401
    assert client.post("/cards/companion/pair", json={}, headers={"Authorization": "Bearer zdc_whatever"}).status_code == 401
    body = pair(client)
    assert body["token"].startswith("zdc_") and body["profile"]["handle"] == "alice"
    assert "token_hash" not in body["device"] and body["device"]["label"] == "Chrome"


def test_the_device_token_reads_and_writes_the_card(client, db):
    auth = {"Authorization": f"Bearer {pair(client)['token']}"}
    res = client.post("/cards/companion/working-on", json={"text": "Zynd Companion"}, headers=auth)
    assert res.status_code == 200 and res.json()["working_on"][0] == "Zynd Companion"
    res = client.post("/cards/companion/exploring", headers=auth,
                      json={"url": "https://github.com/zyndai/platform?utm_source=x", "title": "platform", "kind": "repo", "note": "reading"})
    assert res.status_code == 200
    saved = db.saves[-1]["p_patch"]["exploring"][0]
    assert saved["url"] == "https://github.com/zyndai/platform" and saved["kind"] == "repo"
    bad = client.post("/cards/companion/exploring", json={"url": "http://192.168.0.2/x"}, headers=auth)
    assert bad.status_code == 422 and "Private" in bad.json()["detail"]


def test_a_website_session_is_not_a_device_token(client):
    res = client.post("/cards/companion/working-on", json={"text": "x"}, headers={"Authorization": "Bearer website-session"})
    assert res.status_code == 401
    assert client.get("/cards/companion/me").status_code == 401


def test_a_device_token_works_nowhere_else():
    token = companion.new_token()
    assert verify_supabase_jwt(f"Bearer {token}") is None


def test_revoking_from_the_website_stops_the_extension_at_once(client):
    body = pair(client)
    auth = {"Authorization": f"Bearer {body['token']}"}
    assert client.get("/cards/companion/me", headers=auth).status_code == 200
    listed = client.get("/cards/companion/devices", headers={"Authorization": "Bearer website-session"}).json()["devices"]
    assert [d["id"] for d in listed] == [body["device"]["id"]]
    gone = client.delete(f"/cards/companion/devices/{body['device']['id']}", headers={"Authorization": "Bearer website-session"})
    assert gone.status_code == 204
    assert client.get("/cards/companion/me", headers=auth).status_code == 401
    assert client.delete(f"/cards/companion/devices/{body['device']['id']}", headers={"Authorization": "Bearer website-session"}).status_code == 404


def test_disconnect_revokes_this_device_only(client):
    first, second = pair(client), pair(client)
    assert client.post("/cards/companion/disconnect", headers={"Authorization": f"Bearer {first['token']}"}).status_code == 204
    assert client.get("/cards/companion/me", headers={"Authorization": f"Bearer {first['token']}"}).status_code == 401
    assert client.get("/cards/companion/me", headers={"Authorization": f"Bearer {second['token']}"}).status_code == 200


def test_before_the_migration_is_applied_the_routes_say_so(client, monkeypatch):
    def boom(*a, **k):
        raise APIError({"code": "PGRST205", "message": "relation does not exist", "details": None, "hint": None})
    monkeypatch.setattr(companion, "create_device", boom)
    res = client.post("/cards/companion/pair", json={}, headers={"Authorization": "Bearer website-session"})
    assert res.status_code == 503 and "not available" in res.json()["detail"]
