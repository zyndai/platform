"""Unit tests for the persona client (mocked HTTP — no network/DB)."""
import pytest
import app.services.persona as P


class FakeResp:
    def __init__(self, status, data): self.status_code = status; self._d = data; self.text = str(data)
    def json(self): return self._d


def test_svc_headers(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "supabase_service_key", "svc123")
    h = P._svc_headers()
    assert h["Authorization"] == "Bearer svc123" and h["apikey"] == "svc123"


async def test_get_agent_id(monkeypatch):
    async def fake(method, path, **kw): return FakeResp(200, {"agent_id": "zns:abc", "name": "X"})
    monkeypatch.setattr(P, "_persona", fake)
    assert await P.get_agent_id("u1") == "zns:abc"


async def test_ensure_persona_returns_existing(monkeypatch):
    async def fake(method, path, **kw): return FakeResp(200, {"agent_id": "zns:exist"})
    monkeypatch.setattr(P, "_persona", fake)
    assert await P.ensure_persona("u1") == "zns:exist"


async def test_ensure_persona_registers_when_missing(monkeypatch):
    seen = []
    async def fake(method, path, **kw):
        seen.append(path)
        if path.endswith("/status"): return FakeResp(404, {})
        if "register" in path: return FakeResp(200, {"agent_id": "zns:new"})
        return FakeResp(500, {})
    monkeypatch.setattr(P, "_persona", fake)
    assert await P.ensure_persona("u1", email="a@b.com") == "zns:new"
    assert any("register" in p for p in seen)


async def test_list_connections_rejects_injection():
    import pytest as _pt
    with _pt.raises(P.PersonaError):
        await P.list_connections("zns:abc,evil.eq.x)")   # malformed -> refused (no PostgREST injection)
    with _pt.raises(P.PersonaError):
        await P.list_connections("")
