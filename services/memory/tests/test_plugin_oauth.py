"""Plugin grants use the existing MCP transport without broadening other clients."""
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi import HTTPException
from fastmcp import Client
from fastmcp.server.auth import AccessToken
from mcp.server.auth.middleware.auth_context import AuthenticatedUser, auth_context_var
from mcp.shared.exceptions import MCPError

from app import oauth
from app.config import settings
from app.services.mcp_scopes import PLUGIN_SCOPES, MEMORY_TOOLS, CARDS_READ_TOOLS, CARDS_APPROVE_TOOLS
from test_oauth_grants import grants, request, response_data, exchange, refresh, CHALLENGE, RESOURCE

CLIENT = "zynd-chatgpt-plugin"
CALLBACK = "https://chatgpt.com/connector_platform_oauth_redirect"
SCOPES = " ".join(PLUGIN_SCOPES)


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings, "plugin_oauth_client_id", CLIENT)
    monkeypatch.setattr(settings, "plugin_oauth_redirect_uris", CALLBACK)


async def authorize(**changes):
    args = dict(client_id=CLIENT, redirect_uri=CALLBACK, scope=SCOPES,
                code_challenge=CHALLENGE, code_challenge_method="S256")
    args.update(changes)
    response = await oauth.authorize(**args)
    return parse_qs(urlsplit(response.headers["location"]).query)["zynd_oauth"][0]


async def pair(redis):
    signed = await authorize()
    result = await oauth.complete(request(redis), oauth._CompleteRequest(
        req=signed, supabase_token="mock-session", decision="approve"))
    code = parse_qs(urlsplit(response_data(result)["redirect_url"]).query)["code"][0]
    return response_data(await exchange(redis, code, client_id=CLIENT, redirect_uri=CALLBACK, scope=SCOPES))


@pytest.mark.parametrize("changes", [
    {"scope": "user"}, {"scope": "people:message"},
    {"redirect_uri": CALLBACK + "/other"}, {"redirect_uri": CALLBACK + "?other=1"},
    {"code_challenge_method": "plain"}, {"code_challenge": ""},
])
async def test_plugin_rejects_broad_scopes_callbacks_and_missing_pkce(changes):
    with pytest.raises(HTTPException):
        await authorize(**changes)


async def test_unconfigured_plugin_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "plugin_oauth_redirect_uris", "")
    with pytest.raises(HTTPException) as error:
        await authorize()
    assert error.value.detail == "plugin OAuth client is not configured"


async def test_scope_bound_pair_refresh_and_revocation(grants):
    redis, pool = grants
    original = await pair(redis)
    for result in (original, response_data(await refresh(redis, original["refresh_token"], client_id=CLIENT))):
        assert result["scope"] == SCOPES
        claims = jwt.decode(result["access_token"], settings.jwt_secret, algorithms=["HS256"], audience=RESOURCE)
        assert claims["scp"] == list(PLUGIN_SCOPES)
        assert pool.connections[claims["jti"]]["scopes"] == list(PLUGIN_SCOPES)
    with pytest.raises(HTTPException):
        await refresh(redis, original["refresh_token"], client_id=CLIENT)


@pytest.mark.parametrize("changes", [{"scope": "user"}, {"scope": SCOPES + " people:message"}, {"client_id": "other-agent"}])
async def test_plugin_refresh_cannot_escalate_or_change_clients(grants, changes):
    redis, _ = grants
    original = await pair(redis)
    args = {"client_id": CLIENT, **changes}
    with pytest.raises(HTTPException):
        await refresh(redis, original["refresh_token"], **args)
    assert response_data(await refresh(redis, original["refresh_token"], client_id=CLIENT))["scope"] == SCOPES


async def test_plugin_denial_does_not_mint(grants):
    redis, pool = grants
    result = await oauth.complete(request(redis), oauth._CompleteRequest(
        req=await authorize(), supabase_token="mock-session", decision="deny"))
    assert "access_denied" in response_data(result)["redirect_url"]
    assert not pool.connections and not any(":code:" in key for key in redis.store)


async def test_plugin_scopes_advertised():
    metadata = await oauth.authorization_server_metadata()
    assert set(PLUGIN_SCOPES) <= set(metadata["scopes_supported"])


async def test_plugin_consent_discloses_actual_grant(grants):
    preview = response_data(await oauth.consent(oauth._CompleteRequest(
        req=await authorize(), supabase_token="mock-session")))
    assert preview["scope"] == SCOPES
    assert preview["client_name"] == "ZYND ChatGPT plugin"


async def test_plugin_requires_owner_tools_feature(monkeypatch):
    monkeypatch.setattr(settings, "feature_s09_mcp_clients", False)
    with pytest.raises(HTTPException):
        await authorize()


async def test_plugin_initialization_overrides_automatic_context_policy():
    from types import SimpleNamespace
    from app.services.mcp_gate import ScopeGate
    result = SimpleNamespace(instructions="call get_my_context at conversation start")
    with patch("app.services.mcp_gate.get_access_token", return_value=AccessToken(
            token="test", client_id="owner", scopes=list(PLUGIN_SCOPES))):
        updated = await ScopeGate().on_initialize(None, AsyncMock(return_value=result))
    assert "only after" in updated.instructions
    assert "never automatically" in updated.instructions
    with patch("app.services.mcp_gate.get_access_token", return_value=AccessToken(
            token="test", client_id="owner", scopes=list(PLUGIN_SCOPES))):
        modern = await ScopeGate().on_discover(None, AsyncMock(return_value={"instructions": "legacy"}))
    assert "never automatically" in modern["instructions"]
    with patch("app.services.mcp_gate.get_access_token", return_value=AccessToken(
            token="test", client_id="owner", scopes=["user"])):
        original = SimpleNamespace(instructions="legacy instructions")
        assert (await ScopeGate().on_initialize(None, AsyncMock(return_value=original))).instructions == "legacy instructions"


async def test_plugin_reserved_id_cannot_be_dynamically_registered():
    with patch("app.oauth.secrets.token_urlsafe", return_value=CLIENT):
        with pytest.raises(HTTPException) as error:
            await oauth.register_client(oauth._DCRRequest(redirect_uris=[CALLBACK]))
    assert error.value.detail == "reserved client identifier"


async def test_plugin_cannot_exchange_ordinary_clients_code(grants):
    from test_oauth_grants import approval
    redis, _ = grants
    code = await approval(redis)
    with pytest.raises(HTTPException):
        await exchange(redis, code, client_id=CLIENT, redirect_uri=CALLBACK, scope=SCOPES)


async def test_plugin_revoke_blocks_access_and_refresh(grants):
    from app.mcp_http import ZyndTokenVerifier
    from app.services.mcp_clients import revoke_client
    redis, pool = grants
    original = await pair(redis)
    claims = jwt.decode(original["access_token"], settings.jwt_secret, algorithms=["HS256"], audience=RESOURCE)
    verifier = ZyndTokenVerifier()
    assert await verifier.verify_token(original["access_token"]) is not None
    assert await revoke_client(pool, claims["sub"], claims["jti"])
    assert await verifier.verify_token(original["access_token"]) is None
    with pytest.raises(HTTPException):
        await refresh(redis, original["refresh_token"], client_id=CLIENT)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_plugin_transport_filters_calls_and_requires_fact_confirmation(mode):
    from app.mcp_http import mcp
    reset = auth_context_var.set(AuthenticatedUser(AccessToken(token="test", client_id="owner", scopes=list(PLUGIN_SCOPES))))
    try:
        with patch("app.mcp_owner.approve", AsyncMock()) as approve:
            async with Client(mcp, mode=mode) as client:
                assert "never automatically" in client.instructions
                assert client.server_info.icons[0].src.startswith("data:image/png;base64,")
                assert client.server_info.icons[0].mime_type == "image/png"
                tools = await client.list_tools()
                assert not await client.list_resources()
                with pytest.raises(MCPError):
                    await client.read_resource("skill://zynd-context/SKILL.md")
                assert {t.name for t in tools} == MEMORY_TOOLS | CARDS_READ_TOOLS | CARDS_APPROVE_TOOLS
                with pytest.raises(MCPError):
                    await client.call_tool("publish_page", {"content": "private"})
                unconfirmed = await client.call_tool("approve_fact", {"predicate": "has_skill", "object": "Rust"})
                assert unconfirmed.data["error"] == "confirmation_required"
                approve.assert_not_awaited()
    finally:
        auth_context_var.reset(reset)
