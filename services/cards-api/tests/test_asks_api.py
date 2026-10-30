"""The owner's asks routes: authentication, validation and that nobody can touch another owner's ask
or credit."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import asks as routes
from services import beacons, owner_home, zynd_memory
from tests.asks_support import ASK_1, HELPER, OWNER, ask_row, iso, offer_row, use_db  # noqa: F401
from tests.test_asks import cards_db

OFFER = "00000000-0000-4000-8000-0000000000d1"


@pytest.fixture
def client(monkeypatch, use_db):
    db = use_db(cards_db(asks=[ask_row(created_days=1)],
                         ask_offers=[offer_row("card-b", offer_id=OFFER, credited_at=iso(days=1))]))
    monkeypatch.setattr(owner_home, "enabled", lambda: True)
    emails = {"Bearer ana": "ana@x.test", "Bearer bob": "bob@x.test", "Bearer cy": "cy@x.test", "Bearer nobody": "nobody@x.test"}

    def principal(authorization):
        from api.mcp import _owner_email
        from fastapi import HTTPException
        if authorization not in emails:
            raise HTTPException(401, "Sign in")
        return emails[authorization]
    monkeypatch.setattr("api.owner_home._principal", lambda authorization: type("P", (), {"email": principal(authorization)})())
    monkeypatch.setattr(beacons, "save_beacon", lambda *a: None)
    monkeypatch.setattr(zynd_memory, "ping_revalidate", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(routes.router, prefix="/cards")
    return TestClient(app), db


def auth(who):
    return {"Authorization": f"Bearer {who}"}


def test_every_route_needs_a_session(client):
    app, _ = client
    assert app.get("/cards/mine/asks").status_code == 401
    assert app.get("/cards/mine/credits").status_code == 401
    assert app.post(f"/cards/mine/asks/{ASK_1}/outcome", json={"outcome": "still_looking"}).status_code == 401
    assert app.post(f"/cards/mine/credits/{OFFER}/hide").status_code == 401


def test_the_owner_lists_their_ask_with_who_offered(client):
    app, _ = client
    body = app.get("/cards/mine/asks", headers=auth("ana")).json()
    assert [a["id"] for a in body["asks"]] == [ASK_1]
    assert [o["handle"] for o in body["asks"][0]["offers"]] == ["bob"]
    assert app.get("/cards/mine/asks", headers=auth("bob")).json() == {"asks": []}      # bob's own list is not ana's


def test_someone_without_a_card_gets_a_clear_404(client):
    app, _ = client
    assert app.get("/cards/mine/asks", headers=auth("nobody")).status_code == 404


def test_the_owner_answers_and_credits_a_helper(client):
    app, db = client
    response = app.post(f"/cards/mine/asks/{ASK_1}/outcome", headers=auth("ana"),
                        json={"outcome": "helped", "helper_card_ids": ["card-b"]})
    assert response.status_code == 200 and response.json()["credited"] == 1
    assert db.rows("asks")[0]["outcome"] == "helped"


def test_another_owner_cannot_answer_or_probe_an_ask_that_is_not_theirs(client):
    app, db = client
    for who in ("bob", "cy"):
        response = app.post(f"/cards/mine/asks/{ASK_1}/outcome", headers=auth(who),
                            json={"outcome": "helped", "helper_card_ids": ["card-b"]})
        assert response.status_code == 404
        assert app.post(f"/cards/mine/asks/{ASK_1}/outcome", headers=auth(who), json={"outcome": "solved_elsewhere"}).status_code == 404
    assert db.rows("asks")[0]["outcome"] is None


def test_outcome_bodies_are_validated(client):
    app, _ = client
    post = lambda body: app.post(f"/cards/mine/asks/{ASK_1}/outcome", headers=auth("ana"), json=body).status_code
    assert post({"outcome": "bogus"}) == 422
    assert post({"outcome": "helped", "helper_card_ids": ["x"] * 21}) == 422
    assert post({"outcome": "helped", "helper_card_ids": [""]}) == 422
    assert post({"outcome": "helped", "helper_card_ids": ["y" * 65]}) == 422
    assert post({"outcome": "solved_elsewhere", "owner": "spoof"}) == 422
    assert post({"outcome": "helped"}) == 422                                      # a helper is required
    assert post({"outcome": "helped", "helper_card_ids": ["card-c"]}) == 422       # not an offerer
    assert post({"outcome": "still_looking"}) == 200


def test_a_helper_hides_their_own_credit_only(client):
    app, db = client
    assert app.post(f"/cards/mine/credits/{OFFER}/hide", headers=auth("ana")).status_code == 404      # the asker cannot
    assert app.post(f"/cards/mine/credits/{OFFER}/hide", headers=auth("cy")).status_code == 404
    assert db.rows("ask_offers")[0]["credit_hidden_at"] is None
    assert app.post(f"/cards/mine/credits/{OFFER}/hide", headers=auth("bob")).json() == {"hidden": True}
    assert db.rows("ask_offers")[0]["credit_hidden_at"]
    assert app.post("/cards/mine/credits/not-a-uuid/hide", headers=auth("bob")).status_code == 404
