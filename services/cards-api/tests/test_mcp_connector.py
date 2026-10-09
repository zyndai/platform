"""Tests for api/mcp.py — the cards MCP connector routes.

Supabase JWT verification and the memory-layer HTTP calls are mocked; route
behaviour (auth gating, config shape, proxying, error mapping) is real.
Run: python -m pytest tests/test_mcp_connector.py -v
"""
import json

import pytest
from fastapi.testclient import TestClient

import config
from api.auth import Principal
import api.mcp as mcp_module
from main import app as cards_app

from services import zynd_mcp


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(config, "MEMORY_SERVICE_TOKEN", "svc-token")
    monkeypatch.setattr(config, "MEMORY_LAYER_URL", "https://api.zynd.ai")
    monkeypatch.setattr(config, "AAFO_ISSUER", "https://aafo.example/auth/v1")


PRINCIPAL = Principal(email="alice@example.com", sub="sub-1",
                      iss="https://xmfj.example/auth/v1")
AAFO_PRINCIPAL = Principal(email="alice@example.com", sub="sup-aafo",
                           iss="https://aafo.example/auth/v1")


@pytest.fixture
def client():
    return TestClient(cards_app)


def _auth(principal=PRINCIPAL, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setattr(mcp_module, "verify_supabase_jwt", lambda auth: principal)
    return {"Authorization": "Bearer anything"}


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


# ── connect ──────────────────────────────────────────────────────────────────

def test_connect_requires_auth(client, monkeypatch):
    r = client.post("/cards/mcp/connect")
    assert r.status_code == 401


def test_connect_disabled_without_service_token(client, monkeypatch):
    monkeypatch.setattr(mcp_module, "verify_supabase_jwt", lambda auth: PRINCIPAL)
    monkeypatch.setattr(config, "MEMORY_SERVICE_TOKEN", "")
    r = client.post("/cards/mcp/connect", headers=_auth(monkeypatch=monkeypatch))
    assert r.status_code == 503


def test_connect_returns_token_and_configs(client, monkeypatch):
    monkeypatch.setattr(mcp_module, "verify_supabase_jwt", lambda auth: PRINCIPAL)
    monkeypatch.setattr(
        zynd_mcp, "connect_mcp_sync",
        lambda email, name, sub: {"token": "tok-1", "mcp_url": "https://api.zynd.ai/cards-mcp"},
    )

    r = client.post("/cards/mcp/connect", headers=_auth(monkeypatch=monkeypatch))

    assert r.status_code == 200
    data = r.json()
    assert data["token"] == "tok-1"
    assert data["mcp_url"] == "https://api.zynd.ai/cards-mcp"
    # The paste-ready JSON parses and carries the bearer header.
    parsed = json.loads(data["config_json"])
    assert parsed["mcpServers"]["zynd-cards"]["url"] == data["mcp_url"]
    assert parsed["mcpServers"]["zynd-cards"]["headers"]["Authorization"] == "Bearer tok-1"
    assert data["config_http"]["mcpServers"]["zynd-cards"]["headers"]["Authorization"] == "Bearer tok-1"
    assert any("Claude Code" in i for i in data["instructions"])


def test_connect_forwards_email_and_sub(client, monkeypatch):
    seen = {}

    def fake(email, name, sub):
        seen["email"], seen["sub"] = email, sub
        return {"token": "tok", "mcp_url": "u"}

    monkeypatch.setattr(mcp_module, "verify_supabase_jwt", lambda auth: AAFO_PRINCIPAL)
    monkeypatch.setattr(zynd_mcp, "connect_mcp_sync", fake)

    r = client.post("/cards/mcp/connect", headers=_auth(principal=AAFO_PRINCIPAL, monkeypatch=monkeypatch))

    assert r.status_code == 200
    assert seen["email"] == "alice@example.com"
    assert seen["sub"] == "sup-aafo"  # aafo sub passed for linking; xmfj would be ""


def test_connect_maps_memory_outage_to_502(client, monkeypatch):
    monkeypatch.setattr(mcp_module, "verify_supabase_jwt", lambda auth: PRINCIPAL)
    monkeypatch.setattr(zynd_mcp, "connect_mcp_sync", lambda email, name, sub: None)
    r = client.post("/cards/mcp/connect", headers=_auth(monkeypatch=monkeypatch))
    assert r.status_code == 502


# ── suggestions / approve / revoke (proxy) ────────────────────────────────────

def test_suggestions_requires_auth(client, monkeypatch):
    r = client.get("/cards/mcp/suggestions")
    assert r.status_code == 401


def test_suggestions_proxies_verified_email(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(mcp_module, "verify_supabase_jwt", lambda auth: PRINCIPAL)

    async def fake_suggested(email):
        seen["email"] = email
        return [{"predicate": "is_building", "object": "micro-SaaS", "confidence": 0.8}]

    monkeypatch.setattr(zynd_mcp, "suggested_facts", fake_suggested)

    r = client.get("/cards/mcp/suggestions", headers=_auth(monkeypatch=monkeypatch))

    assert r.status_code == 200
    assert seen["email"] == "alice@example.com"
    assert r.json() == {"suggestions": [
        {"predicate": "is_building", "object": "micro-SaaS", "confidence": 0.8}
    ]}


def test_suggestions_no_memory_account_means_empty_list(client, monkeypatch):
    monkeypatch.setattr(mcp_module, "verify_supabase_jwt", lambda auth: PRINCIPAL)

    async def raise_no_account(email):
        raise zynd_mcp.MemoryUnavailable("no ZYND account for this email")

    monkeypatch.setattr(zynd_mcp, "suggested_facts", raise_no_account)

    r = client.get("/cards/mcp/suggestions", headers=_auth(monkeypatch=monkeypatch))
    assert r.status_code == 200
    assert r.json() == {"suggestions": []}


def test_suggestions_maps_outage_to_502(client, monkeypatch):
    monkeypatch.setattr(mcp_module, "verify_supabase_jwt", lambda auth: PRINCIPAL)

    async def raise_unavailable(email):
        raise zynd_mcp.MemoryUnavailable("memory layer unreachable")

    monkeypatch.setattr(zynd_mcp, "suggested_facts", raise_unavailable)

    r = client.get("/cards/mcp/suggestions", headers=_auth(monkeypatch=monkeypatch))
    assert r.status_code == 502


def test_approve_requires_auth(client, monkeypatch):
    r = client.post("/cards/mcp/approve", json={"predicate": "is_building", "value": "micro-SaaS"})
    assert r.status_code == 401


def test_approve_proxies_predicate_and_value(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(mcp_module, "verify_supabase_jwt", lambda auth: PRINCIPAL)

    async def fake_approve(email, predicate, value):
        seen.update(email=email, predicate=predicate, value=value)
        return {"status": "approved", "predicate": predicate, "value": value}

    monkeypatch.setattr(zynd_mcp, "approve_fact", fake_approve)
    monkeypatch.setattr("services.zynd_memory.refresh_owner_snapshot", lambda email: [])

    r = client.post("/cards/mcp/approve", json={"predicate": "is_building", "value": "micro-SaaS"},
                    headers=_auth(monkeypatch=monkeypatch))

    assert r.status_code == 200
    assert seen == {"email": "alice@example.com", "predicate": "is_building",
                    "value": "micro-SaaS"}
    assert r.json()["status"] == "approved"


def test_revoke_proxies_predicate_and_value(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(mcp_module, "verify_supabase_jwt", lambda auth: PRINCIPAL)

    async def fake_revoke(email, predicate, value):
        seen.update(email=email, predicate=predicate, value=value)
        return {"status": "revoked", "predicate": predicate, "value": value}

    monkeypatch.setattr(zynd_mcp, "revoke_fact", fake_revoke)
    monkeypatch.setattr("services.zynd_memory.refresh_owner_snapshot", lambda email: [])

    r = client.post("/cards/mcp/revoke", json={"predicate": "is_building", "value": "micro-SaaS"},
                    headers=_auth(monkeypatch=monkeypatch))

    assert r.status_code == 200
    assert seen["value"] == "micro-SaaS"
    assert r.json()["status"] == "revoked"


def test_disconnect_proxies_email(client, monkeypatch):
    monkeypatch.setattr(mcp_module, "verify_supabase_jwt", lambda auth: PRINCIPAL)

    async def fake_request(method, path, json_body=None, params=None):
        assert (method, path) == ("POST", "/v1/service/disconnect")
        assert json_body["email"] == "alice@example.com"
        return {"status": "signed_out"}

    monkeypatch.setattr(zynd_mcp, "_request", fake_request)

    r = client.post("/cards/mcp/disconnect", headers=_auth(monkeypatch=monkeypatch))
    assert r.status_code == 200
    assert r.json()["status"] == "signed_out"
