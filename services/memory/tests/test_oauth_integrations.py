"""Shared Calendar credentials, token storage, hosted pages and /connect."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import app.mcp_http as m


# ── Group 1: _suid resolution paths ─────────────────────────────────────────────

async def test_suid_resolves_memory_layer_uid_to_supabase_uid():
    # given — the user row carries a supabase_user_id (linked via Supabase OAuth)
    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = {"supabase_user_id": "supabase-uid-999"}

    # when — _suid is called with the memory-layer uid
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=mock_pool)):
        result = await m._suid(uid="memory-layer-uid-1")

    # then — it returns the Supabase user_id (what api_tokens is keyed by)
    assert result == "supabase-uid-999"
    mock_pool.fetchrow.assert_awaited_once()


async def test_suid_falls_back_to_uid_when_no_supabase_link():
    # given — user registered via /connect (password), so supabase_user_id is NULL
    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = {"supabase_user_id": None}

    # when — _suid is called
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=mock_pool)):
        result = await m._suid(uid="memory-layer-uid-2")

    # then — the memory-layer uid is returned unchanged
    assert result == "memory-layer-uid-2"


async def test_suid_falls_back_when_user_row_missing():
    # given — the user_id is not in the DB (deleted or never existed)
    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = None

    # when — _suid is called
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=mock_pool)):
        result = await m._suid(uid="ghost-uid")

    # then — it returns the uid unchanged and does NOT raise
    assert result == "ghost-uid"


# ── Group 2: Google tools — not connected ───────────────────────────────────────

async def test_google_calendar_not_connected_returns_error():
    # given — no Google token in api_tokens for this suid
    from app.tools.google import calendar as google_calendar

    # when — create_calendar_event is called
    with patch("app.tools.google.common.get_tokens", return_value=None):
        result = await google_calendar.create_calendar_event(
            "suid-x", summary="Sync", start_time="2026-09-01T10:00:00Z"
        )

    # then — a graceful error dict about Google not being connected (no exception)
    assert isinstance(result, dict)
    assert result["success"] is False
    assert "Google not connected" in result["error"]


# ── Group 6: token_store operations ─────────────────────────────────────────────

def test_get_tokens_returns_none_when_not_connected():
    # given — Supabase returns an empty/absent row
    from app.services import token_store

    mock_result = MagicMock()
    mock_result.data = None
    mock_sb = MagicMock()
    (mock_sb.table.return_value.select.return_value
        .eq.return_value.eq.return_value.maybe_single.return_value
        .execute.return_value) = mock_result

    # when — get_tokens is called for an unconnected provider
    with patch("app.services.token_store._sb", return_value=mock_sb):
        result = token_store.get_tokens("user-1", "google")

    # then — None (caller then surfaces "not connected")
    assert result is None


def test_save_tokens_upserts_correctly():
    # given — a fresh token dict with access, refresh, and expiry
    from app.services import token_store

    captured = {}
    mock_sb = MagicMock()

    def _upsert(payload, on_conflict=None):
        captured["payload"] = payload
        captured["on_conflict"] = on_conflict
        chain = MagicMock()
        chain.execute.return_value = MagicMock()
        return chain

    mock_sb.table.return_value.upsert.side_effect = _upsert

    # when — save_tokens is called
    with patch("app.services.token_store._sb", return_value=mock_sb):
        token_store.save_tokens(
            "user-1",
            "google",
            {
                "access_token": "at-abc",
                "refresh_token": "rt-xyz",
                "expires_in": 3600,
                "scope": "calendar gmail",
            },
        )

    # then — upsert targets the right conflict key and carries the right fields
    payload = captured["payload"]
    assert captured["on_conflict"] == "user_id,provider"
    assert payload["user_id"] == "user-1"
    assert payload["provider"] == "google"
    assert payload["access_token"] == "at-abc"
    assert payload["refresh_token"] == "rt-xyz"
    assert payload["scopes"] == "calendar gmail"
    assert payload["expires_at"] is not None  # derived from expires_in
    # raw_data preserves the full original token blob
    assert json.loads(payload["raw_data"])["access_token"] == "at-abc"


def test_list_connected_providers_returns_list():
    # given — two providers connected for this user
    from app.services import token_store

    mock_result = MagicMock()
    mock_result.data = [
        {"provider": "google", "scopes": "calendar"},
        {"provider": "twitter", "scopes": "tweet.read"},
    ]
    mock_sb = MagicMock()
    (mock_sb.table.return_value.select.return_value
        .eq.return_value.execute.return_value) = mock_result

    # when — list_connected_providers is called
    with patch("app.services.token_store._sb", return_value=mock_sb):
        result = token_store.list_connected_providers("user-1")

    # then — a list with both providers
    assert isinstance(result, list)
    assert len(result) == 2
    assert {p["provider"] for p in result} == {"google", "twitter"}


# ── Group 7: publish_page — authenticated vs anonymous ──────────────────────────

async def test_publish_page_authenticated_user_gets_permanent_page():
    # given — an authenticated uid with a linked supabase_user_id
    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = {"supabase_user_id": "supabase-uid-42"}

    captured = {}

    async def _create_page(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"success": True, "url": "http://test/pages/abc", "slug": "abc", "title": "T"}

    with patch("app.mcp_http._get_pool", AsyncMock(return_value=mock_pool)):
        with patch("app.services.pages_agent.create_page", side_effect=_create_page):
            # when — publish_page is called for the authenticated user
            result = await m.publish_page("<h1>Hi</h1>", title="T", uid="mem-uid-42")

    # then — the page is created for the Supabase uid WITHOUT an expiry (permanent)
    assert result["success"] is True
    assert captured["args"][0] == "supabase-uid-42"
    assert "expires_in_hours" not in captured["kwargs"]


async def test_publish_page_with_markdown_format():
    # given — content is Markdown and the user is authenticated
    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = {"supabase_user_id": "supabase-uid-7"}

    captured = {}

    async def _create_page(user_id, content, title, fmt, visibility, **kwargs):
        captured["format"] = fmt
        return {"success": True, "url": "http://test/pages/md", "slug": "md", "title": title}

    with patch("app.mcp_http._get_pool", AsyncMock(return_value=mock_pool)):
        with patch("app.services.pages_agent.create_page", side_effect=_create_page):
            # when — publish_page is called with format="markdown"
            result = await m.publish_page("# Title", title="Doc", format="markdown", uid="mem-uid-7")

    # then — success, and the markdown format is threaded through
    assert result["success"] is True
    assert captured["format"] == "markdown"


async def test_list_my_pages_empty_for_new_user():
    # given — an authenticated user who has published nothing
    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = {"supabase_user_id": "supabase-uid-new"}

    with patch("app.mcp_http._get_pool", AsyncMock(return_value=mock_pool)):
        with patch("app.services.pages_agent.list_pages", AsyncMock(return_value=[])):
            # when — list_my_pages is called
            result = await m.list_my_pages(uid="mem-uid-new")

    # then — an empty list
    assert result == []


# ── Group 8: Connect flow (URL-only OAuth setup) ────────────────────────────────

def _connect_client():
    """Exercise public setup without a lifespan or live Postgres."""
    from app.main import app
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_connect_get_shows_oauth_setup_without_credential():
    with patch("app.docs.settings.mcp_public_base_url", "https://preview.example.test"):
        async with _connect_client() as c:
            r = await c.get("/connect")
    assert r.status_code == 200
    assert "https://preview.example.test/mcp" in r.text
    assert "existing Zynd account" in r.text
    assert "Authorization: Bearer" not in r.text


async def test_connect_new_user_post_retired():
    async with _connect_client() as c:
        r = await c.post("/connect", data={"email": "newuser@example.com", "password": "strongpass1"})
    assert r.status_code == 410
    assert "No account or token was created" in r.text


async def test_connect_existing_user_post_retired():
    async with _connect_client() as c:
        r = await c.post("/connect", data={"email": "known@example.com", "password": "correcthorse"})
    assert r.status_code == 410
    assert "/install" in r.text


async def test_connect_wrong_password_post_retired():
    async with _connect_client() as c:
        r = await c.post("/connect", data={"email": "known@example.com", "password": "wrongpass99"})
    assert r.status_code == 410
    assert "No account or token was created" in r.text


async def test_connect_short_password_post_retired():
    async with _connect_client() as c:
        r = await c.post("/connect", data={"email": "x@example.com", "password": "ab"})
    assert r.status_code == 410
    assert "No account or token was created" in r.text
