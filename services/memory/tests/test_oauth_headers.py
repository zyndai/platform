"""Exercise OAuth error cache policy without starting database-backed lifespan."""
import httpx
import pytest

from app.main import app


@pytest.mark.parametrize("method,path,kwargs,status", [
    ("GET", "/oauth/authorize", {"params": {"response_type": "token"}}, 400),
    ("POST", "/oauth/token", {"data": {}}, 422),
    ("POST", "/oauth/consent", {"json": {"req": "invalid", "supabase_token": "invalid"}}, 400),
    ("POST", "/oauth/complete", {"json": {}}, 400),
])
async def test_oauth_errors_are_not_cacheable(method, path, kwargs, status, monkeypatch):
    monkeypatch.setattr(app.state, "arq", None, raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, path, **kwargs)
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


async def test_discovery_remains_public_without_database_access():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    assert response.json()["code_challenge_methods_supported"] == ["S256"]
