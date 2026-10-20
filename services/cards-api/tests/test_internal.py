"""Internal service-to-service endpoints (shared MEMORY_SERVICE_TOKEN auth)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import internal
import config

TOKEN = "shared-secret-token"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "MEMORY_SERVICE_TOKEN", TOKEN)
    app = FastAPI()
    app.include_router(internal.router, prefix="/internal")
    return TestClient(app)


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_refresh_card_memory_rejects_missing_token(client):
    r = client.post("/internal/refresh-card-memory", json={"email": "a@b.c"})
    assert r.status_code == 401


def test_refresh_card_memory_rejects_wrong_token(client):
    r = client.post(
        "/internal/refresh-card-memory", json={"email": "a@b.c"}, headers=auth("wrong")
    )
    assert r.status_code == 401


def test_refresh_card_memory_rejects_empty_email(client):
    r = client.post(
        "/internal/refresh-card-memory", json={"email": "   "}, headers=auth()
    )
    assert r.status_code == 422


def test_refresh_card_memory_refreshes_and_returns_snapshot(client, monkeypatch):
    calls = []

    def fake_refresh(email):
        calls.append(email)
        return [{"predicate": "is_building", "object": "SendPilot"}]

    monkeypatch.setattr("services.zynd_memory.refresh_owner_snapshot", fake_refresh)
    r = client.post(
        "/internal/refresh-card-memory", json={"email": "A@B.C"}, headers=auth()
    )
    assert r.status_code == 200
    assert calls == ["a@b.c"]
    assert r.json()["zynd_memory"] == [{"predicate": "is_building", "object": "SendPilot"}]


def test_refresh_card_memory_unknown_owner_returns_null(client, monkeypatch):
    monkeypatch.setattr("services.zynd_memory.refresh_owner_snapshot", lambda email: None)
    r = client.post(
        "/internal/refresh-card-memory", json={"email": "nobody@x.y"}, headers=auth()
    )
    assert r.status_code == 200
    assert r.json() == {"zynd_memory": None}

# ── cards-for-users: Memory resolves Zynd users to their Cards ────────────────────

UID_A = "11111111-1111-1111-1111-111111111111"
UID_B = "22222222-2222-2222-2222-222222222222"


def test_cards_for_users_rejects_missing_and_wrong_token(client):
    assert client.post("/internal/cards-for-users", json={"user_ids": [UID_A]}).status_code == 401
    assert client.post("/internal/cards-for-users", json={"user_ids": [UID_A]},
                       headers=auth("wrong")).status_code == 401


def test_cards_for_users_returns_public_identity_only(client, monkeypatch):
    seen = []
    monkeypatch.setattr("services.cards.cards_by_owner_user_ids", lambda ids: seen.append(ids) or {
        UID_A: {"handle": "ada", "name": "Ada", "headline": "Founder", "location": "Pune", "claimed": True}})
    r = client.post("/internal/cards-for-users", json={"user_ids": [UID_A, UID_B]}, headers=auth())
    assert r.status_code == 200
    assert r.json() == {"cards": {UID_A: {"handle": "ada", "name": "Ada", "headline": "Founder",
                                          "location": "Pune", "claimed": True}}}
    assert seen == [[UID_A, UID_B]]


def test_cards_for_users_caps_the_batch_and_rejects_junk(client):
    assert client.post("/internal/cards-for-users", headers=auth(),
                       json={"user_ids": [UID_A] * 51}).status_code == 422
    assert client.post("/internal/cards-for-users", headers=auth(),
                       json={"user_ids": ["not-a-uuid"]}).status_code == 422
    assert client.post("/internal/cards-for-users", headers=auth(),
                       json={"user_ids": [UID_A], "email": "x@y.z"}).status_code == 422


def test_cards_by_owner_user_ids_keeps_claimed_published_cards_and_no_emails(monkeypatch):
    from unittest.mock import MagicMock

    from services import cards as cards_service

    rows = [
        {"handle": "unclaimed", "owner_user_id": UID_B, "owner_email": None, "card": {"identity": {"name": "X"}}},
        {"handle": "ada-new", "owner_user_id": UID_A, "owner_email": "ada@example.com",
         "card": {"identity": {"name": "Ada", "headline": "Founder", "location": "Pune"}}},
        {"handle": "ada-old", "owner_user_id": UID_A, "owner_email": "ada@example.com",
         "card": {"identity": {"name": "Old Ada"}}},
    ]
    chain = MagicMock()
    for method in ("select", "in_", "eq", "order"):
        getattr(chain, method).return_value = chain
    chain.execute.return_value = MagicMock(data=rows)
    sb = MagicMock()
    sb.table.return_value = chain
    monkeypatch.setattr(cards_service.config, "get_supabase", lambda: sb)

    out = cards_service.cards_by_owner_user_ids([UID_A, UID_B, UID_A, ""])

    assert out == {UID_A: {"handle": "ada-new", "name": "Ada", "headline": "Founder",
                           "location": "Pune", "claimed": True}}      # newest first; unclaimed skipped
    assert "ada@example.com" not in repr(out)
    assert cards_service.cards_by_owner_user_ids([]) == {}
