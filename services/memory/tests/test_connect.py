"""Public MCP setup routes and the separately retained internal exchange."""
from unittest.mock import patch

import httpx
import pytest


@pytest.fixture
async def setup_client():
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.parametrize("path", ["/connect", "/install"])
async def test_setup_is_url_only_and_environment_correct(setup_client, path):
    with patch("app.docs.settings.mcp_public_base_url", "https://dev.example.test/mcp"), \
         patch("app.docs.settings.cards_site_base_url", "https://cards.dev.example.test"):
        r = await setup_client.get(path)
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"
    assert "https://dev.example.test/mcp" in r.text
    assert "https://dev.example.test/mcp/mcp" not in r.text
    assert 'href="https://cards.dev.example.test"' in r.text
    assert "https://api.zynd.ai/mcp" not in r.text
    assert "claude mcp add --transport http" in r.text
    assert "codex mcp login zynd" in r.text
    assert "kilo mcp auth zynd" in r.text
    assert "opencode mcp auth zynd" in r.text
    assert "opencode mcp add zynd --url" in r.text
    assert "OpenCode v2" in r.text
    assert "full" in r.text and "30 days" in r.text and "one hour" in r.text
    assert 'name="password"' not in r.text
    assert "Authorization: Bearer" not in r.text
    assert "mcp-remote" not in r.text
    assert "font-size:32px" in r.text
    assert "section{border-top:1px solid" in r.text


@pytest.mark.parametrize("data", [
    {"email": "new@example.com", "password": "strongpass1"},
    {"email": "known@example.com", "password": "wrongpass99"},
    {"email": "x@example.com", "password": "ab"},
    {},
])
async def test_connect_post_is_gone_without_issuing_anything(setup_client, data):
    r = await setup_client.post("/connect", data=data)
    assert r.status_code == 410
    assert r.headers["Cache-Control"] == "no-store"
    assert "/install" in r.text
    assert "No account or token was created" in r.text
    assert "Authorization: Bearer" not in r.text


@pytest.mark.integration
async def test_token_exchange_rejects_invalid_session(client):
    # No Supabase configured in tests -> any token is rejected (401), never issues.
    r = await client.post("/token/exchange", headers={"Authorization": "Bearer whatever"})
    assert r.status_code == 401
