"""Integration tests for the OAuth2 flow (Google handoff) + JWT-authed ingest."""
import secrets
from urllib.parse import parse_qs, urlparse

import jwt
import pytest

from app.config import settings
from app.db import get_pool

pytestmark = pytest.mark.integration

REDIRECT = "http://localhost:8000/cb"  # allowed by the http://localhost prefix
CLIENT = {"client_id": settings.oauth_client_id, "client_secret": settings.oauth_client_secret}
AUTHORIZE_PARAMS = {
    "response_type": "code", "client_id": settings.oauth_client_id,
    "redirect_uri": REDIRECT, "state": "s1",
}


async def _make_user(email="alice@example.com") -> str:
    return await get_pool().fetchval(
        """INSERT INTO users (email, display_name) VALUES ($1, $1)
           ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email RETURNING id""",
        email,
    )


async def _make_code(user_id) -> str:
    """Mint an authorization code the way /oauth/complete does (the Google handoff
    is exercised at the HTTP boundary in test_complete_*; here we just need a code)."""
    from app.main import app
    code = secrets.token_urlsafe(16)
    await app.state.arq.set(f"oauth:code:{code}", str(user_id), ex=600)
    return code


async def test_authorize_redirects_to_dashboard_google(client):
    r = await client.get("/oauth/authorize", params=AUTHORIZE_PARAMS)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith(settings.dashboard_url.rstrip("/") + "/authorize?")
    req = parse_qs(urlparse(loc).query)["req"][0]
    payload = jwt.decode(req, settings.jwt_secret, algorithms=["HS256"])
    assert payload["typ"] == "oauth_req"
    assert payload["redirect_uri"] == REDIRECT and payload["state"] == "s1"


async def test_authorize_rejects_unknown_client(client):
    r = await client.get("/oauth/authorize", params={**AUTHORIZE_PARAMS, "client_id": "evil"})
    assert r.status_code == 400


async def test_authorize_rejects_unlisted_redirect(client):
    r = await client.get("/oauth/authorize", params={
        **AUTHORIZE_PARAMS, "redirect_uri": "https://evil.example.com/cb"})
    assert r.status_code == 400


async def test_redirect_uri_host_spoofing_rejected(client):
    # http://localhost.evil.com must NOT pass the http://localhost prefix.
    r = await client.get("/oauth/authorize", params={
        **AUTHORIZE_PARAMS, "redirect_uri": "http://localhost.evil.com/cb"})
    assert r.status_code == 400


async def test_complete_rejects_tampered_req(client):
    r = await client.post("/oauth/complete", json={"req": "not-a-jwt", "supabase_token": "x"})
    assert r.status_code == 400


async def test_complete_rejects_unverified_google_session(client):
    # Valid signed req, but Supabase is not configured in tests -> token can't verify -> 401.
    authorize = await client.get("/oauth/authorize", params=AUTHORIZE_PARAMS)
    req = parse_qs(urlparse(authorize.headers["location"]).query)["req"][0]
    r = await client.post("/oauth/complete", json={"req": req, "supabase_token": "bogus"})
    assert r.status_code == 401


async def test_full_flow_code_to_token_to_ingest(client):
    alice_id = await _make_user("alice@example.com")
    code = await _make_code(alice_id)

    tok = await client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, **CLIENT})
    assert tok.status_code == 200
    body = tok.json()
    assert body["token_type"] == "bearer"
    access = body["access_token"]

    ingest = await client.post("/ingest", headers={"Authorization": f"Bearer {access}"}, json={
        "source_system": "chatgpt",
        "turns": [{"role": "user", "content": "I am learning Rust async runtimes for my new project."}],
    })
    assert ingest.status_code == 200
    assert ingest.json()["chunks_inserted"] == 1

    chunk_owner = await get_pool().fetchval("SELECT user_id FROM trace_chunks LIMIT 1")
    assert str(chunk_owner) == str(alice_id)


async def test_authorization_code_is_single_use(client):
    code = await _make_code(await _make_user("single@example.com"))
    first = await client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, **CLIENT})
    assert first.status_code == 200
    second = await client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, **CLIENT})
    assert second.status_code == 400  # invalid_grant


async def test_token_rejects_bad_client_secret(client):
    code = await _make_code(await _make_user("badsecret@example.com"))
    r = await client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
        "client_id": settings.oauth_client_id, "client_secret": "wrong"})
    assert r.status_code == 401


async def test_refresh_token_grant_issues_new_access(client):
    code = await _make_code(await _make_user("refresh@example.com"))
    tok = (await client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, **CLIENT})).json()
    refreshed = await client.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": tok["refresh_token"], **CLIENT})
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]
