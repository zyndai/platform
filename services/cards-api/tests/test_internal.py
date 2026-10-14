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