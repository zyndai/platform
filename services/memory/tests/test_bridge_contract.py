"""
Endpoints zynd-bridge depends on (/me/whoami, /me/findability/declare-batch)
and the path-param user routes persona calls with Supabase UUIDs.

Unit tests: the DB pool and auth are stubbed, so no Postgres is needed.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as main
from app.main import app, current_user

INTERNAL_ID = "11111111-1111-1111-1111-111111111111"
SUPABASE_ID = "22222222-2222-2222-2222-222222222222"


class _Pool:
    def __init__(self, linked: bool = True):
        self.linked = linked

    async def fetchval(self, sql, *args):
        if "supabase_user_id = $2" in sql:
            return 1 if (self.linked and args == (INTERNAL_ID, SUPABASE_ID)) else None
        return None

    async def fetchrow(self, sql, *args):
        if "FROM users WHERE id" in sql and args[0] == INTERNAL_ID:
            return {"id": INTERNAL_ID, "email": "a@b.com", "display_name": "Ada",
                    "supabase_user_id": SUPABASE_ID}
        return None


def _client(monkeypatch, pool: _Pool) -> TestClient:
    monkeypatch.setattr(main, "get_pool", lambda: pool)
    app.dependency_overrides[current_user] = lambda: INTERNAL_ID
    return TestClient(app)


def teardown_function(_fn):
    app.dependency_overrides.clear()


# Every memory-layer route zynd-bridge calls (zynd-bridge/src/memory-client.ts
# and src/oauth.ts). Removing or renaming one breaks `zynd sync` / `zynd login`
# for every installed CLI — change the bridge first, then this list.
ZYND_BRIDGE_ROUTES = [
    ("POST", "/ingest"),
    ("GET", "/me/context"),
    ("GET", "/me/findability"),
    ("POST", "/me/findability/approve"),
    ("POST", "/me/findability/declare-batch"),
    ("GET", "/me/findability/suggestions"),
    ("GET", "/me/matches"),
    ("GET", "/me/whoami"),
    ("GET", "/oauth/authorize"),
    ("POST", "/oauth/register"),
    ("POST", "/oauth/token"),
]


def test_routes_zynd_bridge_calls_exist():
    paths = app.openapi()["paths"]
    missing = [f"{m} {p}" for m, p in ZYND_BRIDGE_ROUTES if m.lower() not in paths.get(p, {})]
    assert not missing, f"zynd-bridge calls routes that don't exist: {missing}"


def test_whoami_returns_the_token_owner(monkeypatch):
    client = _client(monkeypatch, _Pool())
    body = client.get("/me/whoami").json()
    assert body == {"user_id": INTERNAL_ID, "email": "a@b.com", "display_name": "Ada",
                    "supabase_user_id": SUPABASE_ID}


def test_declare_batch_writes_valid_and_skips_invalid(monkeypatch):
    client = _client(monkeypatch, _Pool())
    written = []

    async def fake_declare(pool, user_id, predicate, value):
        if predicate == "nope":
            raise ValueError("'nope' is not declarable")
        written.append((user_id, predicate, value))

    monkeypatch.setattr("app.services.findability.declare", fake_declare)
    resp = client.post("/me/findability/declare-batch", json={"declarations": [
        {"predicate": "is_building", "value": "pgvector tooling"},
        {"predicate": "nope", "value": "x"},
    ]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["declared"] == [{"predicate": "is_building", "value": "pgvector tooling"}]
    assert body["skipped"][0]["predicate"] == "nope" and "declarable" in body["skipped"][0]["reason"]
    assert written == [(INTERNAL_ID, "is_building", "pgvector tooling")]


def test_declare_batch_caps_at_50(monkeypatch):
    client = _client(monkeypatch, _Pool())
    items = [{"predicate": "is_building", "value": f"p{i}"} for i in range(51)]
    assert client.post("/me/findability/declare-batch", json={"declarations": items}).status_code == 422


def test_context_accepts_the_callers_supabase_id(monkeypatch):
    client = _client(monkeypatch, _Pool())
    seen = {}

    async def fake_slice(pool, user_id, topic, k):
        seen["user_id"] = user_id
        return []

    monkeypatch.setattr("app.services.export.context_slice", fake_slice)
    resp = client.post(f"/context/{SUPABASE_ID}", json={"topic": "work", "k": 5})

    assert resp.status_code == 200
    assert seen["user_id"] == INTERNAL_ID   # always the caller's namespace


def test_context_rejects_someone_elses_id(monkeypatch):
    client = _client(monkeypatch, _Pool(linked=False))
    other = "33333333-3333-3333-3333-333333333333"
    assert client.post(f"/context/{other}", json={"topic": "work", "k": 5}).status_code == 403
    assert client.get(f"/users/{other}/graph").status_code == 403
    assert client.get(f"/export/{other}").status_code == 403
