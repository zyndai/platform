"""Unit tests for the MCP connector OAuth flow (no DB/Redis needed).

Covers the RFC 8707 resource indicator, the self-hosted auth page routing, the
lookup-only (never-create) user resolution for connectors, token audience/iss
binding + resource echo, refresh-token rotation, RFC 9207 iss echo, and the
skills shipped with the connector.
"""
import asyncio
import base64
import hashlib
import json
from unittest.mock import AsyncMock, patch

import httpx
import jwt
import pytest
from fastapi import HTTPException

from app import oauth
from app.auth import issue_rotating_refresh_token
from app.config import settings
from app.mcp_http import ZyndTokenVerifier
from app.mcp_http import app as mcp_asgi
from app.mcp_http import mcp

# The canonical RFC 8707 resource indicator comes from settings so the tests
# hold regardless of how the suite configures MCP_PUBLIC_BASE_URL.
RESOURCE = settings.mcp_resource_url
CALLBACK = "https://chatgpt.com/connector/oauth/abc123"


class FakeRedis:
    """Minimal arq-shaped Redis stand-in: get/set/delete keyed by str."""

    def __init__(self):
        self.store: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value.encode()
        return True

    async def getdel(self, key: str) -> bytes | None:
        return self.store.pop(key, None)

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


def _req(fake_redis):
    return type("Req", (), {"app": type("App", (), {"state": type("State", (), {"arq": fake_redis})()})()})


def _pool(rows_by_query: dict[str, list] | None = None) -> AsyncMock:
    rows_by_query = rows_by_query or {}
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(side_effect=lambda q, *a: rows_by_query.get(q, [{"id": 1}])[0])
    return pool


def _sealed(req_jwt: str) -> dict:
    return jwt.decode(req_jwt, settings.jwt_secret, algorithms=["HS256"], audience=RESOURCE)


VERIFIER = "v" * 43
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()


# ── Authorize: resource validation + connector vs legacy routing ───────────────

@patch("app.oauth.get_pool")
async def test_authorize_connector_client_goes_to_self_hosted_auth_page(pool_mock):
    pool = _pool({"SELECT allowed_redirect_uris FROM oauth_clients WHERE client_id = $1": [
        {"allowed_redirect_uris": [CALLBACK]}]})
    pool_mock.return_value = pool
    resp = await oauth.authorize(
        client_id="dcr-client-1", redirect_uri=CALLBACK, state="s1",
        code_challenge=CHALLENGE, code_challenge_method="S256", resource=RESOURCE,
    )
    assert resp.status_code == 302
    assert resp.headers["location"].startswith(f"{settings.public_base_url.rstrip('/')}/oauth/login?zynd_oauth=")
    req = _sealed(resp.headers["location"].split("zynd_oauth=", 1)[1])
    assert req["resource"] == RESOURCE
    assert req["create_user"] is False


@patch("app.oauth._fetch_metadata_document")
async def test_authorize_cimd_client_goes_to_auth_page(meta_mock):
    meta_mock.return_value = {
        "client_id": "https://chatgpt.com/connector-client",
        "redirect_uris": ["https://chatgpt.com/connector_platform_oauth_redirect"],
    }
    resp = await oauth.authorize(
        client_id="https://chatgpt.com/connector-client",
        redirect_uri="https://chatgpt.com/connector_platform_oauth_redirect",
        code_challenge=CHALLENGE, code_challenge_method="S256", resource=RESOURCE,
    )
    assert resp.status_code == 302
    assert "/oauth/login?" in resp.headers["location"]


@patch("app.oauth._fetch_metadata_document")
async def test_authorize_claude_accepts_advertised_scopes(meta_mock):
    client_id = "https://claude.ai/oauth/mcp-oauth-client-metadata"
    callback = "https://claude.ai/api/mcp/auth_callback"
    meta_mock.return_value = {"client_id": client_id, "redirect_uris": [callback]}
    metadata = await oauth.authorization_server_metadata()
    resp = await oauth.authorize(
        client_id=client_id, redirect_uri=callback,
        scope=" ".join(metadata["scopes_supported"]),
        code_challenge=CHALLENGE, code_challenge_method="S256", resource=RESOURCE,
    )
    assert resp.status_code == 302
    req = _sealed(resp.headers["location"].split("zynd_oauth=", 1)[1])
    assert req["scope"] == "user"
    assert req["create_user"] is False
    assert req["resource"] == RESOURCE
    meta_mock.assert_awaited_once_with(client_id)


async def test_authorize_connector_rejects_unadvertised_scope():
    with pytest.raises(HTTPException) as exc:
        await oauth.authorize(
            client_id="https://claude.ai/oauth/mcp-oauth-client-metadata",
            redirect_uri="https://claude.ai/api/mcp/auth_callback",
            scope="user people:message",
            code_challenge=CHALLENGE, code_challenge_method="S256", resource=RESOURCE,
        )
    assert exc.value.detail == "unsupported scope"


@patch("app.oauth.get_pool")
async def test_authorize_known_client_uses_auth_page_with_create(pool_mock):
    pool_mock.return_value = AsyncMock()
    resp = await oauth.authorize(
        client_id=settings.oauth_client_id,
        redirect_uri="https://chatgpt.com/aip/plugin-xyz/oauth/callback",
        state="s1", resource=RESOURCE,
    )
    assert resp.status_code == 302
    assert resp.headers["location"].startswith(f"{settings.public_base_url.rstrip('/')}/oauth/login?zynd_oauth=")
    req = _sealed(resp.headers["location"].split("zynd_oauth=", 1)[1])
    assert req["create_user"] is True


async def test_authorize_rejects_unknown_resource():
    with pytest.raises(HTTPException) as exc:
        await oauth.authorize(
            client_id=settings.oauth_client_id,
            redirect_uri="https://chatgpt.com/aip/plugin-xyz/oauth/callback",
            resource="https://evil.example/mcp",
        )
    assert exc.value.status_code == 400


def test_chatgpt_stable_redirect_allowlisted():
    oauth._check_redirect_uri("https://chatgpt.com/connector_platform_oauth_redirect")


# ── Complete: lookup-only for connectors, RFC 9207 iss echo ───────────────────

@patch("app.oauth.get_pool")
@patch("app.services.persona.link_user", new_callable=AsyncMock, return_value=None)
@patch("app.services.users.find_user", new_callable=AsyncMock, return_value=None)
@patch("app.oauth.supabase_identity", new_callable=AsyncMock, return_value=("u@example.com", "U", "sub-1"))
async def test_complete_connector_unknown_user_rejected(identity_mock, find_mock, link_mock, pool_mock):
    pool_mock.return_value = AsyncMock()
    req = oauth._sign_oauth_request(
        CALLBACK, "s1", "ingest", "ch", "S256",
        resource=RESOURCE, create_user=False, iss_supported=True,
    )
    body = oauth._CompleteRequest(req=req, supabase_token="t", decision="approve")
    with pytest.raises(HTTPException) as exc:
        await oauth.complete(_req(FakeRedis()), body)
    assert exc.value.status_code == 401
    assert "No ZYND account found" in exc.value.detail


@patch("app.oauth.get_pool")
@patch("app.services.persona.link_user", new_callable=AsyncMock, return_value=None)
@patch("app.services.users.find_user", new_callable=AsyncMock, return_value="u-1")
@patch("app.oauth.supabase_identity", new_callable=AsyncMock, return_value=("u@example.com", "U", "sub-1"))
async def test_complete_connector_known_user_mints_bound_code_with_iss(identity_mock, find_mock, link_mock, pool_mock):
    pool_mock.return_value = AsyncMock()
    redis = FakeRedis()
    req = oauth._sign_oauth_request(
        CALLBACK, "s1", "ingest", "ch", "S256",
        resource=RESOURCE, create_user=False, iss_supported=True,
    )
    body = oauth._CompleteRequest(req=req, supabase_token="t", decision="approve")
    resp = await oauth.complete(_req(redis), body)
    url = json.loads(resp.body)["redirect_url"]
    assert url.startswith(CALLBACK)
    assert "iss=" in url  # RFC 9207 echo (URL-encoded in the query string)
    assert "code=" in url and "state=s1" in url
    code = url.split("code=", 1)[1].split("&", 1)[0]
    stored = json.loads(redis.store[oauth._grant_key("code", code)].decode())
    assert stored["resource"] == RESOURCE
    assert stored["user_id"] == "u-1"


# ── Token: resource echo + audience binding + refresh rotation ────────────────

def _store_connector_code(redis: FakeRedis, code: str) -> None:
    redis.store[oauth._grant_key("code", code)] = json.dumps({
        "user_id": "u-1", "redirect_uri": CALLBACK, "resource": RESOURCE,
        "client_id": "dcr-client-1", "client_type": "public", "scope": "user",
        "challenge": CHALLENGE, "method": "S256", "client_name": "Agent",
    }).encode()


async def test_token_connector_code_echoes_resource_and_binds_audience():
    redis = FakeRedis()
    _store_connector_code(redis, "c1")
    with patch("app.oauth.get_pool", return_value=_pool({})):
        resp = await oauth.token(
            _req(redis), grant_type="authorization_code", client_id="dcr-client-1",
            client_secret="", code="c1", redirect_uri=CALLBACK, code_verifier=VERIFIER,
            resource=RESOURCE, scope="",
        )
    assert resp.body  # JSONResponse
    data = json.loads(resp.body)
    assert data["resource"] == RESOURCE
    assert data["token_type"] == "Bearer"
    claims = jwt.decode(data["access_token"], settings.jwt_secret, algorithms=["HS256"],
                        options={"verify_aud": False, "verify_iss": False})
    assert claims["iss"] == settings.public_base_url.rstrip("/")
    assert claims["aud"] == RESOURCE
    assert claims["scp"] == ["user"]
    refresh_jti = jwt.decode(data["refresh_token"], settings.jwt_secret, algorithms=["HS256"],
                             options={"verify_aud": False, "verify_iss": False})["jti"]
    assert oauth._grant_key("refresh", refresh_jti) in redis.store


async def test_token_connector_code_rejects_wrong_resource():
    redis = FakeRedis()
    _store_connector_code(redis, "c1")
    with patch("app.oauth.get_pool", return_value=_pool({})):
        with pytest.raises(HTTPException) as exc:
            await oauth.token(
                _req(redis), grant_type="authorization_code", client_id="dcr-client-1",
                client_secret="", code="c1", redirect_uri=CALLBACK, code_verifier=VERIFIER,
                resource="https://other.example/mcp", scope="",
            )
    assert exc.value.status_code == 400


@pytest.mark.parametrize("changes", [
    {"client_id": "dcr-other"}, {"redirect_uri": CALLBACK + "/extra"},
    {"code_verifier": "x" * 43}, {"scope": "ingest user"},
])
async def test_public_code_binding_rejects_substitution(changes):
    redis = FakeRedis()
    _store_connector_code(redis, "bound")
    kwargs = dict(grant_type="authorization_code", client_id="dcr-client-1", client_secret="",
                  code="bound", redirect_uri=CALLBACK, code_verifier=VERIFIER, resource="", scope="")
    kwargs.update(changes)
    with patch("app.oauth.get_pool", return_value=_pool({})):
        with pytest.raises(HTTPException) as exc:
            await oauth.token(_req(redis), **kwargs)
    assert exc.value.detail == "invalid_grant"
    assert oauth._grant_key("code", "bound") in redis.store


async def test_public_code_concurrent_exchange_is_single_use():
    redis = FakeRedis()
    _store_connector_code(redis, "bound")
    kwargs = dict(grant_type="authorization_code", client_id="dcr-client-1", client_secret="",
                  code="bound", redirect_uri=CALLBACK, code_verifier=VERIFIER, resource="", scope="")
    with patch("app.oauth.get_pool", return_value=_pool({})):
        results = await asyncio.gather(*(oauth.token(_req(redis), **kwargs) for _ in range(2)), return_exceptions=True)
    assert sum(isinstance(r, HTTPException) and r.detail == "invalid_grant" for r in results) == 1
    assert sum(isinstance(r, httpx.Response) for r in results) == 0
    assert sum(hasattr(r, "body") for r in results) == 1


def test_registered_redirect_matches_only_host_path_query_and_ephemeral_port():
    registered = ["http://127.0.0.1:3911/callback?mode=oauth"]
    assert oauth._check_dcr_redirect_uri("http://127.0.0.1:9288/callback?mode=oauth", registered)
    for uri in ("http://localhost:9288/callback?mode=oauth", "http://127.0.0.1:9288/callback/extra?mode=oauth",
                "http://127.0.0.1:9288/callback?mode=other", "http://127.0.0.1:9288/callback?mode=oauth#fragment",
                "http://evil@127.0.0.1:9288/callback?mode=oauth"):
        assert not oauth._check_dcr_redirect_uri(uri, registered)


@patch("app.oauth.get_pool")
async def test_public_authorize_requires_pkce_and_defaults_resource(pool_mock):
    pool_mock.return_value = _pool({"SELECT allowed_redirect_uris FROM oauth_clients WHERE client_id = $1": [
        {"allowed_redirect_uris": [CALLBACK]}]})
    with pytest.raises(HTTPException):
        await oauth.authorize(client_id="dcr-client-1", redirect_uri=CALLBACK)
    resp = await oauth.authorize(client_id="dcr-client-1", redirect_uri=CALLBACK,
                                 code_challenge=CHALLENGE, code_challenge_method="S256")
    assert _sealed(resp.headers["location"].split("zynd_oauth=", 1)[1])["resource"] == RESOURCE


@patch("app.oauth.get_pool")
@patch("app.services.users.find_user", new_callable=AsyncMock, return_value="u-1")
@patch("app.oauth.supabase_identity", new_callable=AsyncMock, return_value=("u@example.com", "U", "sub-1"))
async def test_consent_preview_and_denial_do_not_mint(identity_mock, find_mock, pool_mock):
    pool_mock.return_value = AsyncMock()
    req = oauth._sign_oauth_request(CALLBACK, "original", "user", CHALLENGE, "S256",
                                    resource=RESOURCE, create_user=False, client_id="dcr-client-1")
    redis = FakeRedis()
    preview = await oauth.consent(oauth._CompleteRequest(req=req, supabase_token="t"))
    assert json.loads(preview.body)["email"] == "u@example.com"
    assert not redis.store
    with pytest.raises(HTTPException):
        await oauth.complete(_req(redis), oauth._CompleteRequest(req=req, supabase_token="t"))
    denial = await oauth.complete(_req(redis), oauth._CompleteRequest(req=req, supabase_token="t", decision="deny"))
    assert "error=access_denied" in json.loads(denial.body)["redirect_url"]
    assert "state=original" in json.loads(denial.body)["redirect_url"]
    assert not any(":code:" in k for k in redis.store)
    with pytest.raises(HTTPException):
        await oauth.complete(_req(redis), oauth._CompleteRequest(req=req, supabase_token="t", decision="approve"))


async def test_sealed_request_rejects_foreign_issuer():
    req = oauth._sign_oauth_request(CALLBACK, "state", "user", CHALLENGE, "S256",
                                    resource=RESOURCE, create_user=False, client_id="dcr-client-1")
    with patch.object(settings, "public_base_url", "https://other-environment.example"):
        with pytest.raises(HTTPException):
            oauth._verify_oauth_request(req)


async def test_old_public_rotating_refresh_cannot_be_redeemed_by_confidential_client():
    redis = FakeRedis()
    refresh_tok, jti = issue_rotating_refresh_token("u-1")
    redis.store[f"oauth:refresh:{jti}"] = RESOURCE.encode()
    with patch("app.oauth.get_pool", return_value=_pool({})):
        with pytest.raises(HTTPException) as exc:
            await oauth.token(_req(redis), grant_type="refresh_token",
                              client_id=settings.oauth_client_id, client_secret=settings.oauth_client_secret,
                              code="", redirect_uri="", code_verifier="", refresh_token=refresh_tok,
                              resource="", scope="")
    assert exc.value.detail == "invalid_grant"
    assert redis.store[f"oauth:refresh:{jti}"] == RESOURCE.encode()


@patch("app.services.sessions.tokens_revoked", new_callable=AsyncMock, return_value=False)
async def test_confidential_resource_refresh_remains_rotating(revoked_mock):
    redis = FakeRedis()
    redis.store["oauth:code:confidential-code"] = json.dumps({
        "user_id": "u-1", "redirect_uri": CALLBACK, "client_id": settings.oauth_client_id,
        "client_type": "confidential", "resource": RESOURCE, "scope": "ingest",
    }).encode()
    params = dict(client_id=settings.oauth_client_id, client_secret=settings.oauth_client_secret,
                  code_verifier="", redirect_uri=CALLBACK, resource=RESOURCE, scope="")
    with patch("app.oauth.get_pool", return_value=_pool({})):
        code_resp = await oauth.token(_req(redis), grant_type="authorization_code", code="confidential-code",
                                      refresh_token="", **params)
        first = json.loads(code_resp.body)
        assert first["scope"] == "ingest"
        refresh_resp = await oauth.token(_req(redis), grant_type="refresh_token", code="",
                                         refresh_token=first["refresh_token"], **params)
        replacement = json.loads(refresh_resp.body)
        assert replacement["scope"] == "ingest"
        assert replacement["refresh_token"] != first["refresh_token"]
        with pytest.raises(HTTPException) as exc:
            await oauth.token(_req(redis), grant_type="refresh_token", code="",
                              refresh_token=first["refresh_token"], **params)
    assert exc.value.detail == "invalid_grant"


@patch("app.oauth.get_pool")
async def test_authorize_accepts_advertised_scopes_and_registered_ephemeral_loopback(pool_mock):
    pool_mock.return_value = _pool({"SELECT allowed_redirect_uris FROM oauth_clients WHERE client_id = $1": [
        {"allowed_redirect_uris": ["http://localhost:3377/callback"]}]})
    resp = await oauth.authorize(client_id="dcr-client-1", redirect_uri="http://localhost:9922/callback",
                                 scope="user ingest offline_access", code_challenge=CHALLENGE,
                                 code_challenge_method="S256")
    sealed = _sealed(resp.headers["location"].split("zynd_oauth=", 1)[1])
    assert sealed["scope"] == "user" and sealed["resource"] == RESOURCE


async def test_user_lookup_does_not_select_another_subject():
    from app.services.users import find_user
    pool = AsyncMock()
    pool.fetchrow.side_effect = [None, {"id": "victim", "supabase_user_id": "different-sub"}]
    assert await find_user(pool, "a@example.com", "current-sub") is None


@patch("app.services.sessions.tokens_revoked", new_callable=AsyncMock, return_value=False)
async def test_token_refresh_rotates_and_rejects_replay(revoked_mock):
    redis = FakeRedis()
    refresh_tok, jti = issue_rotating_refresh_token("u-1", bound=True)
    redis.store[oauth._grant_key("refresh", jti)] = json.dumps({
        "v": 2, "sub": "u-1", "client_id": "dcr-client-1", "scope": "user",
        "resource": RESOURCE, "connection_jti": "53fdc822-2985-4e23-ad83-e38229822ce1",
    }).encode()
    with patch("app.oauth.get_pool", return_value=_pool({})), patch("app.services.mcp_clients.client_revoked", new_callable=AsyncMock, return_value=False):
        resp = await oauth.token(
            _req(redis), grant_type="refresh_token", client_id="dcr-client-1",
            client_secret="", code="", redirect_uri="", code_verifier="",
            refresh_token=refresh_tok, resource="", scope="",
        )
        data = json.loads(resp.body)
        assert data["resource"] == RESOURCE
        # Original refresh jti is consumed; a replay must fail.
        with pytest.raises(HTTPException) as exc:
            await oauth.token(
                _req(redis), grant_type="refresh_token", client_id="dcr-client-1",
                client_secret="", code="", redirect_uri="", code_verifier="",
                refresh_token=refresh_tok, resource="", scope="",
            )
    assert exc.value.status_code == 400


# ── MCP server: PRM scopes, connector-token acceptance, skills ────────────────

async def test_prm_advertises_user_scope():
    transport = httpx.ASGITransport(app=mcp_asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200
    assert r.json()["scopes_supported"] == ["user", "memory:write", "cards:read", "cards:approve"]


@patch("app.services.sessions.token_rejected", new_callable=AsyncMock, return_value=False)
async def test_verifier_accepts_connector_token(rejected_mock):
    from app.auth import issue_connector_access_token
    pool = AsyncMock()
    token, _ = issue_connector_access_token("u-1", settings.mcp_resource_url)
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)):
        result = await ZyndTokenVerifier().verify_token(token)
    assert result is not None
    assert result.client_id == "u-1"
    # RFC 8707 binding: newer FastMCP releases reject tokens whose `resource`
    # doesn't match the resource-server URL.
    assert result.resource == settings.mcp_resource_url
    assert result.expires_at is not None


@patch("app.services.sessions.token_rejected", new_callable=AsyncMock, return_value=False)
async def test_verifier_rejects_connector_token_for_wrong_resource(rejected_mock):
    from app.auth import issue_connector_access_token
    token, _ = issue_connector_access_token("u-1", "https://evil.example/mcp")
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value=None)
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)):
        result = await ZyndTokenVerifier().verify_token(token)
    assert result is None


def test_connector_ships_skills():
    resources = asyncio.run(mcp.list_resources())
    uris = {str(r.uri) for r in resources}
    assert "skill://zynd-memory/SKILL.md" in uris
    assert "skill://zynd-context/SKILL.md" in uris
    assert "skill://zynd-card/SKILL.md" in uris
