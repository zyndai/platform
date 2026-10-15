"""Isolated hosted consent page tests; no Postgres, Redis, or Supabase calls."""
import json
from pathlib import Path
import re
import shutil
import subprocess

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app import oauth_ui


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(oauth_ui, "_supabase_project", lambda: ("https://auth.example", "anon-key"))
    monkeypatch.setattr(oauth_ui.settings, "public_base_url", "https://api.example")
    api = FastAPI()
    api.include_router(oauth_ui.router)
    return api


@pytest.mark.parametrize("route", ["/oauth/login", "/oauth/login/callback"])
async def test_hosted_pages_are_not_cached(app, route):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(route, params={"zynd_oauth": "sealed-request"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert '"sealed-request"' in response.text


async def test_existing_session_previews_consent_without_completing(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = (await client.get("/oauth/login", params={"zynd_oauth": "sealed-request"})).text
    assert "getSession().then" in page
    assert "preview(r.data.session.access_token)" in page
    assert "post('/oauth/consent', {req: pending, supabase_token: token})" in page
    assert "post('/oauth/complete', {req: pending, supabase_token: token, decision: decision})" in page
    assert "decide('approve')" in page and "decide('deny')" in page
    assert page.index("post('/oauth/complete'") < page.index("decide('approve')")
    assert 'id="consent" hidden' in page
    assert "full access" in page.lower()
    for capability in ("memory and conversations", "profile card", "connected integrations", "disconnect"):
        assert capability in page


async def test_callback_returns_to_consent_with_sealed_request(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = (await client.get("/oauth/login/callback", params={"zynd_oauth": "sealed-request"})).text
    assert "%%REQ%%" not in page and "sessionStorage.getItem(key)" in page
    assert "encodeURIComponent(req)" in page
    assert "window.location.replace('/oauth/login?zynd_oauth='" in page
    assert "try { req = sessionStorage.getItem(key); } catch(e) {}" in page
    assert "window.history.replaceState(null, '', window.location.pathname + window.location.search)" in page
    assert "/oauth/complete" not in page


@pytest.mark.parametrize("route", ["/oauth/login", "/oauth/login/callback"])
async def test_sealed_request_cannot_escape_inline_script(app, route):
    injection = '</script><script>alert("oops")</script>\u2028&'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = (await client.get(route, params={"zynd_oauth": injection})).text
    assert injection not in page
    assert "\\u003c/script\\u003e" in page
    assert len(re.findall(r"</script>", page)) == 2


async def test_server_supplied_identity_and_client_are_rendered_as_text(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = (await client.get("/oauth/login", params={"zynd_oauth": "sealed-request"})).text
    for field in ("identity", "client", "resource"):
        assert f"document.getElementById('{field}').textContent = r.data." in page
    assert "client name is supplied" in page.lower()
    assert "card.innerHTML" not in page
    assert "document.body.innerHTML" not in page


async def test_error_region_stays_visible_after_signin_is_hidden(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = (await client.get("/oauth/login", params={"zynd_oauth": "sealed-request"})).text
    assert page.index('id="error"') < page.index('id="signin"')
    assert 'role="alert" aria-live="assertive" hidden' in page
    assert "document.getElementById('error')" in page
    assert "error.textContent = msg" in page
    assert "error.hidden = false" in page


async def test_browser_consent_desktop_and_mobile(app):
    if not shutil.which("node"):
        pytest.skip("Node is not installed")
    playwright = Path(__file__).resolve().parents[3] / "apps/cards-web/node_modules/playwright"
    if not playwright.exists():
        pytest.skip("Install cards-web browser test dependencies to run consent browser checks")
    probe = subprocess.run(
        ["node", "-e", "const fs=require('node:fs');const {chromium}=require(process.argv[1]);process.exit(fs.existsSync(chromium.executablePath())?0:1)", str(playwright)],
        capture_output=True, timeout=10, check=False,
    )
    if probe.returncode:
        pytest.skip("Install Playwright Chromium to run consent browser checks")
    script = Path(__file__).with_name("oauth_ui_browser.cjs")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login = (await client.get("/oauth/login", params={"zynd_oauth": "sealed-request"})).text
        callback = (await client.get("/oauth/login/callback", params={"zynd_oauth": "sealed-request"})).text
    result = subprocess.run(
        ["node", str(script)], input=json.dumps({"login": login, "callback": callback}),
        text=True, capture_output=True, timeout=45, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
