"""Integration tests for the OAuth2 authorization-code flow + JWT-authed ingest."""
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import settings
from app.db import get_pool

pytestmark = pytest.mark.integration

REDIRECT = "http://localhost:8000/cb"  # allowed by the http://localhost prefix
CLIENT = {"client_id": settings.oauth_client_id, "client_secret": settings.oauth_client_secret}


async def test_authorize_renders_consent_page(client):
    r = await client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": settings.oauth_client_id,
        "redirect_uri": REDIRECT, "state": "s1",
    })
    assert r.status_code == 200
    assert "<form" in r.text
    assert 'name="password"' in r.text  # real login asks for a password now


async def test_authorize_rejects_unknown_client(client):
    r = await client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": "evil", "redirect_uri": REDIRECT,
    })
    assert r.status_code == 400


async def test_authorize_rejects_unlisted_redirect(client):
    r = await client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": settings.oauth_client_id,
        "redirect_uri": "https://evil.example.com/cb",
    })
    assert r.status_code == 400


async def test_redirect_uri_host_spoofing_rejected(client):
    # http://localhost.evil.com must NOT pass the http://localhost prefix.
    r = await client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": settings.oauth_client_id,
        "redirect_uri": "http://localhost.evil.com/cb",
    })
    assert r.status_code == 400


async def test_authorize_escapes_reflected_params_no_xss(client):
    r = await client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": settings.oauth_client_id,
        "redirect_uri": REDIRECT, "state": '"><script>alert(1)</script>',
    })
    assert r.status_code == 200
    assert "<script>alert(1)" not in r.text       # not reflected raw
    assert "&lt;script&gt;" in r.text             # escaped instead


async def _get_code(client, email="alice@example.com", password="supersecret") -> str:
    r = await client.post("/oauth/login", data={
        "email": email, "password": password, "redirect_uri": REDIRECT, "state": "s1",
    })
    assert r.status_code == 302
    query = parse_qs(urlparse(r.headers["location"]).query)
    assert query["state"] == ["s1"]
    return query["code"][0]


async def test_login_rejects_short_password(client):
    r = await client.post("/oauth/login", data={
        "email": "shorty@example.com", "password": "abc", "redirect_uri": REDIRECT, "state": "s1"})
    assert r.status_code == 400


async def test_login_rejects_wrong_password(client):
    await _get_code(client, email="carol@example.com", password="correct-horse")  # signup
    r = await client.post("/oauth/login", data={
        "email": "carol@example.com", "password": "WRONG-password", "redirect_uri": REDIRECT, "state": "s1"})
    assert r.status_code == 401


async def test_signup_then_login_same_password_works(client):
    await _get_code(client, email="dave@example.com", password="hunter2hunter2")   # creates account
    code = await _get_code(client, email="dave@example.com", password="hunter2hunter2")  # logs in
    assert code  # got a fresh auth code on the second (login) round


async def test_full_flow_code_to_token_to_ingest(client):
    code = await _get_code(client)

    tok = await client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, **CLIENT,
    })
    assert tok.status_code == 200
    body = tok.json()
    assert body["token_type"] == "bearer"
    access = body["access_token"]

    # The issued JWT authenticates a real ingest for alice (not the dev user).
    ingest = await client.post("/ingest", headers={"Authorization": f"Bearer {access}"}, json={
        "source_system": "chatgpt",
        "turns": [{"role": "user", "content": "I am learning Rust async runtimes for my new project."}],
    })
    assert ingest.status_code == 200
    assert ingest.json()["chunks_inserted"] == 1

    alice_id = await get_pool().fetchval("SELECT id FROM users WHERE email = 'alice@example.com'")
    chunk_owner = await get_pool().fetchval("SELECT user_id FROM trace_chunks LIMIT 1")
    assert str(chunk_owner) == str(alice_id)


async def test_authorization_code_is_single_use(client):
    code = await _get_code(client)
    first = await client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, **CLIENT,
    })
    assert first.status_code == 200
    second = await client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, **CLIENT,
    })
    assert second.status_code == 400  # invalid_grant


async def test_token_rejects_bad_client_secret(client):
    code = await _get_code(client)
    r = await client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
        "client_id": settings.oauth_client_id, "client_secret": "wrong",
    })
    assert r.status_code == 401


async def test_refresh_token_grant_issues_new_access(client):
    code = await _get_code(client)
    tok = (await client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, **CLIENT,
    })).json()

    refreshed = await client.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": tok["refresh_token"], **CLIENT,
    })
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]
