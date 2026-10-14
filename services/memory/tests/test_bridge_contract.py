"""
Endpoints zynd-bridge depends on (/me/whoami, /me/findability/declare-batch)
and the path-param user routes persona calls with Supabase UUIDs.

Unit tests: the DB pool and auth are stubbed, so no Postgres is needed.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

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
                    "supabase_user_id": SUPABASE_ID, "socials": {}}
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


def test_me_context_preserves_existing_fields_and_adds_identity(monkeypatch):
    client = _client(monkeypatch, _Pool())
    facts = [{"statement": "You build tools", "predicate": "is_building", "object": "tools"}]
    profile = {"name": "Ada", "agent_id": "zns:abc", "profile": {"title": "Engineer"}}
    recall = AsyncMock(return_value=facts)
    persona_status = AsyncMock(return_value=profile)
    brief = AsyncMock(return_value={"success": True, "content": "Tool roadmap"})
    monkeypatch.setattr("app.services.export.active_context", recall)
    monkeypatch.setattr("app.services.persona.get_status", persona_status)
    monkeypatch.setattr("app.tools.brief.read_my_brief", brief)

    response = client.get("/me/context?k=5")

    assert response.status_code == 200
    assert response.json() == {"assertions": facts, "profile": profile, "brief": "Tool roadmap",
                               "identity": {"name": "Ada", "email": "a@b.com"}}
    recall.assert_awaited_once_with(main.get_pool(), INTERNAL_ID, 5)
    persona_status.assert_awaited_once_with(SUPABASE_ID)
    brief.assert_awaited_once_with(SUPABASE_ID)


def test_action_context_schema_is_additive_and_keeps_operation_mapping():
    from app.action_schema import build_action_schema

    schema = build_action_schema()
    assert schema["paths"]["/me/context"]["get"]["operationId"] == "getContextWithProfile"
    graph = schema["paths"]["/me/graph"]["get"]
    assert graph["operationId"] == "getMyContext"
    assert graph["responses"]["200"]["content"]["application/json"]["schema"]["type"] == "array"
    packet = schema["components"]["schemas"]["ContextPacket"]
    assert {"identity", "assertions", "profile", "brief"} <= packet["properties"].keys()
    assert "facts" not in packet["properties"]
    identity = packet["properties"]["identity"]
    assert identity["properties"]["name"]["minLength"] == 1
    assert identity["properties"]["email"]["type"] == ["string", "null"]
    checked_in = json.loads((Path(__file__).resolve().parents[1] / "openapi" / "action.prod.json").read_text())
    static_packet = checked_in["components"]["schemas"]["ContextPacket"]
    assert static_packet["properties"]["identity"]["properties"]["name"]["minLength"] == 1
    assert {"identity", "assertions", "profile", "brief"} <= static_packet["properties"].keys()


def test_me_context_optional_failures_preserve_local_memory(monkeypatch):
    from app.services.persona import PersonaError

    client = _client(monkeypatch, _Pool())
    facts = [{"statement": "You build tools"}]
    monkeypatch.setattr("app.services.export.active_context", AsyncMock(return_value=facts))
    monkeypatch.setattr("app.services.persona.get_status",
                        AsyncMock(side_effect=PersonaError("offline")))
    monkeypatch.setattr("app.tools.brief.read_my_brief",
                        AsyncMock(return_value={"success": False, "error": "offline"}))

    response = client.get("/me/context")

    assert response.status_code == 200
    assert response.json() == {"assertions": facts, "profile": None, "brief": None,
                               "identity": {"name": "Ada", "email": "a@b.com"}}


def test_me_context_unlinked_user_keeps_memory_uid_for_brief(monkeypatch):
    pool = _Pool()
    pool.fetchrow = AsyncMock(return_value={"display_name": "Ada", "email": "a@b.com",
                                            "supabase_user_id": None, "socials": "{}"})
    client = _client(monkeypatch, pool)
    monkeypatch.setattr("app.services.export.active_context", AsyncMock(return_value=[]))
    persona_status = AsyncMock()
    brief = AsyncMock(return_value={"success": True, "content": ""})
    monkeypatch.setattr("app.services.persona.get_status", persona_status)
    monkeypatch.setattr("app.tools.brief.read_my_brief", brief)

    response = client.get("/me/context")

    assert response.status_code == 200
    assert response.json()["brief"] is None
    assert response.json()["profile"] is None
    persona_status.assert_not_awaited()
    brief.assert_awaited_once_with(INTERNAL_ID)


def test_me_context_resolves_persona_name_and_conditionally_self_heals(monkeypatch):
    pool = _Pool()
    pool.fetchrow = AsyncMock(return_value={"display_name": " ", "email": "a@b.com",
                                            "supabase_user_id": SUPABASE_ID, "socials": "{}"})
    pool.execute = AsyncMock()
    client = _client(monkeypatch, pool)
    monkeypatch.setattr("app.services.export.active_context", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.persona.get_status", AsyncMock(return_value={"name": " Ada "}))
    monkeypatch.setattr("app.tools.brief.read_my_brief", AsyncMock(return_value={"success": True, "content": ""}))

    response = client.get("/me/context")

    assert response.status_code == 200
    assert response.json()["identity"] == {"name": "Ada", "email": "a@b.com"}
    pool.execute.assert_awaited_once()
    sql, *args = pool.execute.await_args.args
    assert "display_name IS NULL" in sql and "btrim(display_name) = ''" in sql
    assert set(args) == {"Ada", INTERNAL_ID}


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
