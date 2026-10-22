"""Claude plugin grants: keyed on the /claude/mcp resource, plugin scopes only, isolated from /mcp and /chatgpt/mcp."""
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi import HTTPException

from app import oauth, oauth_ui
from app.config import settings
from app.mcp_http import ZyndTokenVerifier
from plugin_mcp import PLUGIN_SCOPES
from test_oauth_grants import CALLBACK, CHALLENGE, exchange, grants, refresh, request, response_data  # noqa: F401

SCOPES = " ".join(PLUGIN_SCOPES)
# Claude's hosted apps and Claude Code each sign in with their own Client ID Metadata Document.
CLAUDE_AI = "https://claude.ai/oauth/mcp-oauth-client-metadata"
CLAUDE_AI_CALLBACK = "https://claude.ai/api/mcp/auth_callback"
CLAUDE_CODE = "https://claude.ai/oauth/claude-code-client-metadata"
CLAUDE_CODE_CALLBACK = "http://127.0.0.1:53111/callback"
DOCUMENTS = {
    CLAUDE_AI: {"client_id": CLAUDE_AI, "client_name": "Claude", "redirect_uris": [CLAUDE_AI_CALLBACK]},
    CLAUDE_CODE: {"client_id": CLAUDE_CODE, "client_name": "Claude Code",
                  "redirect_uris": ["http://localhost/callback", "http://127.0.0.1/callback"]},
}


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    # Production layout: the plugin shares the general MCP's origin, so only the path tells them apart.
    monkeypatch.setattr(settings, "claude_plugin_mcp_public_base_url", settings.mcp_origin + "/claude")
    monkeypatch.setattr(settings, "feature_claude_plugin", True)
    monkeypatch.setattr(settings, "feature_plugin_consent", True)
    with patch("app.oauth._fetch_metadata_document", new_callable=AsyncMock,
               side_effect=lambda client_id: DOCUMENTS[client_id]):
        yield


def resource():
    return settings.claude_plugin_resource_url


async def authorize(client_id=CLAUDE_AI, redirect_uri=CLAUDE_AI_CALLBACK, **changes):
    args = dict(client_id=client_id, redirect_uri=redirect_uri, scope=SCOPES + " offline_access",
                code_challenge=CHALLENGE, code_challenge_method="S256", resource=resource())
    args.update(changes)
    response = await oauth.authorize(**args)
    return parse_qs(urlsplit(response.headers["location"]).query)["zynd_oauth"][0]


async def pair(redis, client_id=CLAUDE_AI, redirect_uri=CLAUDE_AI_CALLBACK):
    signed = await authorize(client_id, redirect_uri)
    result = await oauth.complete(request(redis), oauth._CompleteRequest(
        req=signed, supabase_token="mock-session", decision="approve"))
    code = parse_qs(urlsplit(response_data(result)["redirect_url"]).query)["code"][0]
    return response_data(await exchange(redis, code, client_id=client_id, redirect_uri=redirect_uri,
                                        scope="", resource=resource()))


def claims_of(result):
    return jwt.decode(result["access_token"], settings.jwt_secret, algorithms=["HS256"], audience=resource())


@pytest.mark.parametrize("client_id,redirect_uri", [(CLAUDE_AI, CLAUDE_AI_CALLBACK), (CLAUDE_CODE, CLAUDE_CODE_CALLBACK)])
async def test_claude_hosts_get_only_plugin_scopes_bound_to_the_plugin(grants, client_id, redirect_uri):
    redis, pool = grants
    original = await pair(redis, client_id, redirect_uri)
    rotated = response_data(await refresh(redis, original["refresh_token"], client_id=client_id))
    for result in (original, rotated):
        assert result["scope"] == SCOPES and result["resource"] == resource()
        claims = claims_of(result)
        assert claims["scp"] == list(PLUGIN_SCOPES) and claims["cid"] == client_id
        assert pool.connections[claims["jti"]]["label"] == "ZYND Claude plugin"
    with pytest.raises(HTTPException):
        await refresh(redis, original["refresh_token"], client_id=client_id)


async def test_dynamically_registered_client_can_use_the_plugin(grants):
    redis, _ = grants
    assert claims_of(await pair(redis, "public-agent", CALLBACK))["cid"] == "public-agent"


@pytest.mark.parametrize("changes", [
    {"scope": "user"}, {"scope": SCOPES + " people:message"}, {"scope": "memory:write"},
    {"code_challenge_method": "plain"}, {"code_challenge": ""},
    {"redirect_uri": "https://evil.example/callback"},
])
async def test_claude_plugin_rejects_broad_scopes_bad_callbacks_and_missing_pkce(changes):
    with pytest.raises(HTTPException):
        await authorize(**changes)


async def test_disabled_feature_fails_closed(grants, monkeypatch):
    redis, _ = grants
    original = await pair(redis)
    monkeypatch.setattr(settings, "feature_claude_plugin", False)
    with pytest.raises(HTTPException) as error:
        await authorize()
    assert error.value.detail == "unsupported resource indicator"
    assert await ZyndTokenVerifier(audiences=[resource()]).verify_token(original["access_token"]) is None
    with pytest.raises(HTTPException):
        await refresh(redis, original["refresh_token"], client_id=CLAUDE_AI)


async def test_origin_resource_still_means_the_general_connector(grants):
    redis, _ = grants
    signed = await authorize(resource=settings.mcp_origin, scope="user")
    result = await oauth.complete(request(redis), oauth._CompleteRequest(
        req=signed, supabase_token="mock-session", decision="approve"))
    code = parse_qs(urlsplit(response_data(result)["redirect_url"]).query)["code"][0]
    token = response_data(await exchange(redis, code, client_id=CLAUDE_AI, redirect_uri=CLAUDE_AI_CALLBACK,
                                         resource=settings.mcp_resource_url))
    assert token["scope"] == "user" and token["resource"] == settings.mcp_resource_url


@pytest.mark.parametrize("changes", [
    {"scope": "user"}, {"scope": SCOPES + " people:message"},
    {"resource": settings.mcp_resource_url}, {"client_id": CLAUDE_CODE},
])
async def test_refresh_cannot_escalate_or_move_to_another_surface(grants, changes):
    redis, _ = grants
    original = await pair(redis)
    with pytest.raises(HTTPException):
        await refresh(redis, original["refresh_token"], **{"client_id": CLAUDE_AI, **changes})
    assert response_data(await refresh(redis, original["refresh_token"], client_id=CLAUDE_AI))["scope"] == SCOPES


async def test_code_cannot_be_redeemed_for_the_general_resource(grants):
    redis, _ = grants
    signed = await authorize()
    result = await oauth.complete(request(redis), oauth._CompleteRequest(
        req=signed, supabase_token="mock-session", decision="approve"))
    code = parse_qs(urlsplit(response_data(result)["redirect_url"]).query)["code"][0]
    with pytest.raises(HTTPException):
        await exchange(redis, code, client_id=CLAUDE_AI, redirect_uri=CLAUDE_AI_CALLBACK,
                       scope="", resource=settings.mcp_resource_url)


async def test_tokens_only_verify_on_their_own_surface(grants):
    from test_oauth_grants import approval
    redis, _ = grants
    plugin_token = (await pair(redis))["access_token"]
    general_token = response_data(await exchange(redis, await approval(redis)))["access_token"]
    claude_verifier = ZyndTokenVerifier(audiences=[resource()])
    general_verifier = ZyndTokenVerifier()   # /mcp and /chatgpt/mcp
    accepted = await claude_verifier.verify_token(plugin_token)
    assert accepted is not None and accepted.resource == resource()
    assert await general_verifier.verify_token(plugin_token) is None
    assert await claude_verifier.verify_token(general_token) is None


async def test_rest_endpoints_reject_claude_plugin_tokens(grants):
    from app.main import current_user
    redis, _ = grants
    token = (await pair(redis))["access_token"]
    with pytest.raises(HTTPException) as error:
        await current_user(f"Bearer {token}")
    assert error.value.status_code == 401


async def test_consent_discloses_the_plugin_grant(grants):
    preview = response_data(await oauth.consent(oauth._CompleteRequest(
        req=await authorize(), supabase_token="mock-session")))
    assert preview == {**preview, "scope": SCOPES, "client_name": "ZYND Claude plugin", "resource": resource()}


async def test_reviewer_account_is_allowed_only_on_plugin_requests(grants, monkeypatch):
    from test_oauth_grants import signed_request
    monkeypatch.setattr(settings, "plugin_review_emails", "review@example.test")
    assert oauth._is_plugin_request(oauth._verify_oauth_request(await authorize()))
    assert not oauth._is_plugin_request(oauth._verify_oauth_request(await signed_request()))
    assert oauth_ui._reviewer_form_enabled(await authorize())
    assert not oauth_ui._reviewer_form_enabled(await signed_request())
