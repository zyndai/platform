"""The /claude/mcp transport: plugin tokens see six titled tools, everything else sees nothing."""
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastmcp import Client
from fastmcp.server.auth import AccessToken
from mcp.server.auth.middleware.auth_context import AuthenticatedUser, auth_context_var
from mcp.shared.exceptions import MCPError

from app import oauth
from app.config import settings
from plugin_mcp import PLUGIN_SCOPES, PLUGIN_TOOLS


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings, "feature_claude_plugin", True)
    monkeypatch.setattr(settings, "feature_plugin_consent", True)


def token(aud=None, scopes=PLUGIN_SCOPES):
    return AccessToken(token="test", client_id="owner", scopes=list(scopes),
                       claims={"aud": aud or settings.claude_plugin_resource_url,
                               "oauth_client_id": "https://claude.ai/oauth/mcp-oauth-client-metadata"})


async def tools_for(access_token):
    from claude_server import mcp
    reset = auth_context_var.set(AuthenticatedUser(access_token))
    try:
        async with Client(mcp) as client:
            return client.instructions, await client.list_tools()
    finally:
        auth_context_var.reset(reset)


async def test_plugin_token_sees_six_titled_annotated_tools():
    instructions, tools = await tools_for(token())
    assert "never automatically" in instructions
    assert {t.name for t in tools} == set(PLUGIN_TOOLS)
    for tool in tools:
        assert tool.title and tool.annotations.title == tool.title, tool.name
        hints = tool.annotations.model_dump(by_alias=True, exclude_none=True)
        for key in ("readOnlyHint", "destructiveHint", "openWorldHint"):
            assert isinstance(hints.get(key), bool), (tool.name, key)
        assert len(tool.name) <= 64


@pytest.mark.parametrize("other", [
    token(aud="http://localhost:8091/chatgpt/mcp"),
    token(aud="http://localhost:8090/mcp", scopes=["user"]),
])
async def test_other_surfaces_tokens_see_no_tools(other):
    assert (await tools_for(other))[1] == []


async def test_disabled_feature_hides_tools(monkeypatch):
    monkeypatch.setattr(settings, "feature_claude_plugin", False)
    assert (await tools_for(token()))[1] == []


async def test_calls_outside_the_plugin_are_refused():
    from claude_server import mcp
    reset = auth_context_var.set(AuthenticatedUser(token()))
    try:
        with patch("app.mcp_owner.approve", AsyncMock()) as approve:
            async with Client(mcp) as client:
                assert not await client.list_resources()
                for name, args in (("publish_page", {"content": "private"}),
                                   ("approve_fact", {"predicate": "has_skill", "object": "Rust", "confirm": True})):
                    with pytest.raises(MCPError):
                        await client.call_tool(name, args)
                approve.assert_not_awaited()
    finally:
        auth_context_var.reset(reset)


async def get(path, method="GET"):
    from claude_server import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        return await client.request(method, path)


async def test_resource_metadata_names_the_plugin_and_the_issuer_exactly():
    issuer = (await oauth.authorization_server_metadata())["issuer"]
    response = await get("/.well-known/oauth-protected-resource/claude/mcp")
    assert response.status_code == 200
    metadata = response.json()
    assert metadata["resource"] == settings.claude_plugin_resource_url
    assert metadata["authorization_servers"] == [issuer]
    assert metadata["scopes_supported"] == list(PLUGIN_SCOPES)


def test_unauthenticated_requests_get_a_401_that_points_at_the_metadata():
    from starlette.testclient import TestClient
    import claude_server
    with patch.object(claude_server, "init_pool", AsyncMock()) as init, \
         patch.object(claude_server, "close_pool", AsyncMock()) as close:
        with TestClient(claude_server.app, base_url="http://localhost") as client:
            response = client.post("/claude/mcp", json={})
            assert response.status_code == 401
            assert "/.well-known/oauth-protected-resource/claude/mcp" in response.headers["www-authenticate"]
        init.assert_awaited_once()
        close.assert_awaited_once()
