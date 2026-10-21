"""OpenAI compares the issuer string exactly: the plugin's resource metadata must spell the
authorization server the way the authorization server metadata spells its `issuer`."""
import httpx

from app import oauth
from app.config import settings


async def get(path, method="GET"):
    from server import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        return await client.request(method, path)


async def test_resource_metadata_names_the_issuer_exactly():
    issuer = (await oauth.authorization_server_metadata())["issuer"]
    response = await get("/.well-known/oauth-protected-resource/chatgpt/mcp")
    assert response.status_code == 200
    metadata = response.json()
    assert metadata["authorization_servers"] == [issuer]
    assert metadata["resource"] == settings.plugin_resource_url
    assert metadata["scopes_supported"] == ["memory:recall", "memory:propose", "cards:review"]
    assert response.headers["cache-control"] == "public, max-age=3600"


async def test_cors_preflight_for_the_metadata_still_works():
    response = await get("/.well-known/oauth-protected-resource/chatgpt/mcp", method="OPTIONS")
    assert response.status_code in (200, 204)


def test_server_starts_and_stops_through_its_lifespan():
    """uvicorn runs the app's lifespan; a broken one aborts startup (seen on the box)."""
    from unittest.mock import AsyncMock, patch
    from starlette.testclient import TestClient
    import server
    with patch.object(server, "init_pool", AsyncMock()) as init, \
         patch.object(server, "close_pool", AsyncMock()) as close:
        with TestClient(server.app, base_url="http://localhost") as client:
            assert client.get("/.well-known/oauth-protected-resource/chatgpt/mcp").status_code == 200
            assert client.post("/chatgpt/mcp", json={}).status_code == 401
        init.assert_awaited_once()
        close.assert_awaited_once()
