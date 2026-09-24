"""
Behaviour of api/guards.py on real routes: who may call what.

Supabase is never contacted — token verification and table reads are
monkeypatched. The app is used without its lifespan (no heartbeats etc.).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import config
import main
from api.auth import get_current_user

SERVICE_KEY = "svc-test-key"


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows
        self._filters: list[tuple[str, str]] = []

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def limit(self, _n):
        return self

    def execute(self):
        return _Result([r for r in self._rows if all(r.get(c) == v for c, v in self._filters)])


class _FakeSupabase:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables

    def table(self, name):
        return _Query(self._tables.get(name, []))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_SERVICE_KEY", SERVICE_KEY)
    monkeypatch.setattr(config, "INTERNAL_SERVICE_KEYS", [])

    async def fake_current_user(request):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer user:"):
            raise HTTPException(status_code=401, detail="Missing or invalid token")
        return {"id": auth.removeprefix("Bearer user:"), "email": None, "user_metadata": {}}

    async def fake_live_user_id(token):
        if not token.startswith("user:"):
            raise HTTPException(status_code=401, detail="Session could not be verified")
        return token.removeprefix("user:")

    monkeypatch.setattr("api.guards.get_current_user", fake_current_user)
    monkeypatch.setattr("api.guards._live_user_id", fake_live_user_id)
    return TestClient(main.app)


def as_user(uid: str) -> dict:
    return {"Authorization": f"Bearer user:{uid}"}


SERVICE = {"Authorization": f"Bearer {SERVICE_KEY}"}


# ── Account deletion (self only, live check, never services) ──────────

def test_delete_account_requires_a_token(client):
    assert client.delete("/api/persona/u1/account").status_code == 401


def test_delete_account_rejects_another_user(client, monkeypatch):
    purge = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr("api.persona.purge_user_account", purge)
    assert client.delete("/api/persona/u1/account", headers=as_user("u2")).status_code == 403
    purge.assert_not_called()


def test_delete_account_rejects_the_service_key(client, monkeypatch):
    purge = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr("api.persona.purge_user_account", purge)
    assert client.delete("/api/persona/u1/account", headers=SERVICE).status_code == 403
    purge.assert_not_called()


def test_delete_account_allows_the_owner(client, monkeypatch):
    purge = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr("api.persona.purge_user_account", purge)
    assert client.delete("/api/persona/u1/account", headers=as_user("u1")).status_code == 200
    purge.assert_awaited_once_with("u1")


# ── self_or_service ───────────────────────────────────────────────────

@pytest.fixture
def status_stub(monkeypatch):
    monkeypatch.setattr("api.persona.get_persona_status", lambda uid: {"deployed": True, "user_id": uid})


def test_status_owner_ok(client, status_stub):
    assert client.get("/api/persona/u1/status", headers=as_user("u1")).json()["user_id"] == "u1"


def test_status_other_user_forbidden(client, status_stub):
    assert client.get("/api/persona/u1/status", headers=as_user("u2")).status_code == 403


def test_status_service_ok(client, status_stub):
    assert client.get("/api/persona/u1/status", headers=SERVICE).status_code == 200


def test_status_wrong_bearer_is_unauthorized(client, status_stub):
    resp = client.get("/api/persona/u1/status", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_pending_meetings_other_user_forbidden(client, monkeypatch):
    monkeypatch.setattr("api.meetings.meetings_svc.list_pending_for_user", lambda uid: {"pending": []})
    assert client.get("/api/meetings/pending/u1", headers=as_user("u2")).status_code == 403
    assert client.get("/api/meetings/pending/u1", headers=as_user("u1")).status_code == 200


# ── Body-named actors ─────────────────────────────────────────────────

def test_register_cannot_register_someone_else(client, monkeypatch):
    create = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr("api.persona.create_persona", create)
    monkeypatch.setattr(config, "ZYND_WEBHOOK_BASE_URL", "https://example.test")
    body = {"user_id": "u1", "name": "A", "description": "d", "capabilities": []}
    assert client.post("/api/persona/register", json=body, headers=as_user("u2")).status_code == 403
    create.assert_not_called()
    assert client.post("/api/persona/register", json=body, headers=as_user("u1")).status_code == 200


# ── Thread / task participants ────────────────────────────────────────

@pytest.fixture
def fake_db(monkeypatch):
    db = _FakeSupabase({
        "dm_threads": [{"id": "t1", "initiator_id": "u1", "receiver_id": "agdns:bob"}],
        "persona_agents": [{"user_id": "u2", "agent_id": "agdns:bob"}],
        "agent_tasks": [{"id": "k1", "initiator_user_id": "u1", "recipient_user_id": "u2"}],
    })
    monkeypatch.setattr(config, "get_supabase", lambda: db)
    return db


def test_thread_meetings_participants_only(client, fake_db, monkeypatch):
    monkeypatch.setattr("api.meetings.meetings_svc.list_for_thread", lambda tid, include_resolved=False: [])
    assert client.get("/api/meetings/thread/t1", headers=as_user("u1")).status_code == 200
    # u2 is a participant through their persona agent id
    assert client.get("/api/meetings/thread/t1", headers=as_user("u2")).status_code == 200
    assert client.get("/api/meetings/thread/t1", headers=as_user("u3")).status_code == 403
    assert client.get("/api/meetings/thread/nope", headers=as_user("u1")).status_code == 404


def test_meeting_task_participants_only(client, fake_db, monkeypatch):
    monkeypatch.setattr("api.meetings.meetings_svc.get", lambda tid: {"id": tid})
    assert client.get("/api/meetings/k1", headers=as_user("u2")).status_code == 200
    assert client.get("/api/meetings/k1", headers=as_user("u3")).status_code == 403


def test_create_meeting_actor_must_be_caller(client, fake_db, monkeypatch):
    monkeypatch.setattr("api.meetings.meetings_svc.create_proposal", lambda **kw: {"id": "k2"})
    body = {
        "thread_id": "t1",
        "actor_user_id": "u1",
        "payload": {"title": "Sync", "start_time": "2026-10-01T10:00:00Z", "end_time": "2026-10-01T10:30:00Z"},
    }
    # u2 is a thread participant but may not act as u1
    assert client.post("/api/meetings", json=body, headers=as_user("u2")).status_code == 403
    # u3 claims to be u3 but is not on the thread
    outsider = {**body, "actor_user_id": "u3"}
    assert client.post("/api/meetings", json=outsider, headers=as_user("u3")).status_code == 403
    assert client.post("/api/meetings", json=body, headers=as_user("u1")).status_code == 200


# ── Telegram webhook secret ───────────────────────────────────────────

def test_telegram_webhook_requires_secret_when_configured(client, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_WEBHOOK_SECRET", "tg-secret")
    assert client.post("/api/telegram/webhook", json={}).status_code == 401
    ok = client.post("/api/telegram/webhook", json={},
                     headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret"})
    assert ok.status_code == 200


def test_telegram_register_route_is_gone(client):
    assert client.get("/api/telegram/register").status_code in (404, 405)


# ── OAuth connect codes ───────────────────────────────────────────────

def test_authorize_rejects_unknown_connect_code(client, monkeypatch):
    monkeypatch.setattr("api.oauth_routes._pop_pending_state", lambda state, provider: None)
    resp = client.get("/api/oauth/github/authorize?code=bogus", follow_redirects=False)
    assert resp.status_code == 401


def test_authorize_requires_code_or_token(client):
    assert client.get("/api/oauth/github/authorize", follow_redirects=False).status_code == 401


def test_connect_code_is_bound_to_the_signed_in_user(client, monkeypatch):
    stored = {}

    async def fake_user():
        return {"id": "u1", "email": None}

    main.app.dependency_overrides[get_current_user] = fake_user
    monkeypatch.setattr(
        "api.oauth_routes._store_pending_state",
        lambda state, user_id, provider, code_verifier=None: stored.update(state=state, user=user_id, provider=provider),
    )
    try:
        resp = client.post("/api/oauth/connect-code")
    finally:
        main.app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert stored["user"] == "u1" and stored["provider"] == "connect"
    assert resp.json()["code"] == stored["state"]
