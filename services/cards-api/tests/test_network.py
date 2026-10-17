from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import network
import config


UID = "00000000-0000-0000-0000-000000000001"


def client(monkeypatch):
    monkeypatch.setattr(config, "MEMORY_SERVICE_TOKEN", "memory-network-test")
    app = FastAPI()
    app.include_router(network.router, prefix="/cards")
    return TestClient(app)


def test_memory_service_can_call_cards_network_for_bound_user(monkeypatch):
    app = client(monkeypatch)
    seen = {}
    monkeypatch.setattr(network.network, "list_connections", lambda uid: seen.update(uid=uid) or {"connections": []})
    response = app.get(
        "/cards/network/connections",
        headers={"Authorization": "Bearer memory-network-test", "X-Zynd-User": UID},
    )
    assert response.status_code == 200
    assert response.json() == {"connections": []}
    assert seen == {"uid": UID}


def test_network_rejects_non_shared_account_session(monkeypatch):
    app = client(monkeypatch)
    response = app.get("/cards/network/connections", headers={"Authorization": "Bearer not-a-session"})
    assert response.status_code == 403


def test_service_calls_require_a_valid_bound_user(monkeypatch):
    app = client(monkeypatch)
    for user in (None, "not-a-uuid"):
        headers = {"Authorization": "Bearer memory-network-test"}
        if user:
            headers["X-Zynd-User"] = user
        assert app.get("/cards/network/connections", headers=headers).status_code == 401


def test_request_body_cannot_override_the_caller(monkeypatch):
    app = client(monkeypatch)
    response = app.post("/cards/network/connections", json={"target_handle": "alice", "user_id": UID}, headers={
        "Authorization": "Bearer memory-network-test", "X-Zynd-User": UID,
    })
    assert response.status_code == 422
