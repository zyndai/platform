import inspect

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


def test_inbox_route_uses_the_bound_user(monkeypatch):
    app = client(monkeypatch)
    seen = {}
    monkeypatch.setattr(network.network, "get_inbox", lambda uid: seen.update(uid=uid) or {
        "connections": [], "groups": [], "invitations": [],
    })
    response = app.get("/cards/network/inbox", headers={
        "Authorization": "Bearer memory-network-test", "X-Zynd-User": UID,
    })
    assert response.status_code == 200
    assert response.json() == {"connections": [], "groups": [], "invitations": []}
    assert seen == {"uid": UID}


def test_send_message_accepts_a_client_idempotency_key(monkeypatch):
    app = client(monkeypatch)
    seen = {}
    monkeypatch.setattr(network.network, "send_message", lambda uid, connection, content, client_id: seen.update({
        "uid": uid, "connection": connection, "content": content, "client_id": client_id,
    }) or {"message": {"id": "m"}})
    response = app.post(
        "/cards/network/connections/00000000-0000-4000-8000-000000000001/messages",
        json={"content": "hello", "client_id": "00000000-0000-4000-8000-000000000002"},
        headers={"Authorization": "Bearer memory-network-test", "X-Zynd-User": UID},
    )
    assert response.status_code == 200
    assert seen["client_id"] == "00000000-0000-4000-8000-000000000002"
    assert seen["content"] == "hello"


def test_read_mark_route(monkeypatch):
    app = client(monkeypatch)
    seen = {}
    monkeypatch.setattr(network.network, "mark_read", lambda uid, kind, target, seq: seen.update({
        "uid": uid, "kind": kind, "target": target, "seq": seq,
    }) or {"status": "ok"})
    response = app.post(
        "/cards/network/read",
        json={"kind": "dm", "id": "00000000-0000-4000-8000-000000000001", "seq": 7},
        headers={"Authorization": "Bearer memory-network-test", "X-Zynd-User": UID},
    )
    assert response.status_code == 200
    assert seen == {
        "uid": UID, "kind": "dm", "target": "00000000-0000-4000-8000-000000000001", "seq": 7,
    }


def test_people_suggest_route_uses_the_bound_user(monkeypatch):
    app = client(monkeypatch)
    seen = {}
    monkeypatch.setattr(network.network, "suggest_people", lambda uid, q: seen.update(uid=uid, q=q) or {"people": []})
    response = app.get("/cards/network/people/suggest", params={"q": "ali"}, headers={
        "Authorization": "Bearer memory-network-test", "X-Zynd-User": UID,
    })
    assert response.status_code == 200
    assert response.json() == {"people": []}
    assert seen == {"uid": UID, "q": "ali"}


def test_people_suggest_requires_a_session_and_caps_the_query(monkeypatch):
    app = client(monkeypatch)
    monkeypatch.setattr(network.network, "suggest_people", lambda uid, q: {"people": []})
    assert app.get("/cards/network/people/suggest", params={"q": "ali"}).status_code in (401, 403)
    headers = {"Authorization": "Bearer memory-network-test", "X-Zynd-User": UID}
    assert app.get("/cards/network/people/suggest", params={"q": "x" * 64}, headers=headers).status_code == 200
    assert app.get("/cards/network/people/suggest", params={"q": "x" * 65}, headers=headers).status_code == 422


def test_connection_status_route_is_not_swallowed_by_the_connection_id_routes(monkeypatch):
    app = client(monkeypatch)
    seen = {}
    monkeypatch.setattr(network.network, "connection_status", lambda uid, handle: seen.update(uid=uid, handle=handle) or {
        "connection": None, "can_connect": True, "reason": None,
    })
    response = app.get("/cards/network/connections/status", params={"handle": "alice"}, headers={
        "Authorization": "Bearer memory-network-test", "X-Zynd-User": UID,
    })
    assert response.status_code == 200
    assert response.json() == {"connection": None, "can_connect": True, "reason": None}
    assert seen == {"uid": UID, "handle": "alice"}


def test_connection_status_needs_a_handle_of_sane_length(monkeypatch):
    app = client(monkeypatch)
    monkeypatch.setattr(network.network, "connection_status", lambda uid, handle: {"self": True})
    headers = {"Authorization": "Bearer memory-network-test", "X-Zynd-User": UID}
    assert app.get("/cards/network/connections/status", headers=headers).status_code == 422
    assert app.get("/cards/network/connections/status", params={"handle": ""}, headers=headers).status_code == 422
    assert app.get("/cards/network/connections/status", params={"handle": "h" * 129}, headers=headers).status_code == 422
    assert app.get("/cards/network/connections/status", params={"handle": "h" * 128}, headers=headers).status_code == 200


def test_network_handlers_do_not_block_the_event_loop():
    # The Supabase client is synchronous. These handlers must be plain `def`
    # so FastAPI runs them in its threadpool instead of on the event loop.
    for handler in (
        network.inbox,
        network.connections,
        network.connection_status,
        network.suggest_people,
        network.connection_messages,
        network.send_connection_message,
        network.groups,
        network.group_messages,
        network.send_group_message,
        network.group_memory_list,
        network.group_memory_write,
        network.agent_preferences,
        network.update_agent_preferences,
        network.mark_read,
    ):
        assert not inspect.iscoroutinefunction(handler), handler.__name__
