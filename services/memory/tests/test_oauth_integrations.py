"""End-to-end integration tests for how REAL USERS experience their connected
OAuth accounts (Google, Twitter, LinkedIn, Notion) on the ZYND MCP platform.

Covers the paths a user actually hits:
  - account never connected  → tool degrades to an error DICT (never raises)
  - _suid resolution (memory-layer uid → Supabase uid) across all three branches
  - token_store CRUD against the Supabase `api_tokens` table
  - publish_page / list_my_pages for authenticated users
  - /connect password signup + sign-in flow

Design notes / findings:
  - Every "not connected" tool degrades GRACEFULLY: the credential helpers
    (get_google_creds / twitter._get_client / linkedin._get_headers /
    notion._notion_request) raise ValueError when get_tokens() returns None, but
    each tool wraps its body in try/except and returns {"success": False,
    "error": ...}. So the observable contract is a DICT, not an exception. These
    tests assert that contract. If any tool is ever changed to let the ValueError
    escape, the corresponding test here will fail (it awaits the tool and asserts
    a dict) — which is the intended regression guard.
  - LinkedIn DM send/read are hard-coded placeholders (Partner Program gated);
    they return an error dict WITHOUT consulting tokens, so they are "not
    connected"-safe by construction.
  - Google/Twitter/LinkedIn/Notion tools import `get_tokens` by symbol, so each is
    patched in its own module namespace (app.tools.<mod>.get_tokens), not in
    app.services.token_store.
"""
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


async def test_gmail_search_not_connected_returns_error():
    # given — no Google token
    from app.tools.google import gmail as google_gmail

    # when — search_gmail_emails is called
    with patch("app.tools.google.common.get_tokens", return_value=None):
        result = await google_gmail.search_gmail_emails("suid-x", query="from:boss")

    # then — error dict, not an exception
    assert isinstance(result, dict)
    assert result["success"] is False
    assert "Google not connected" in result["error"]


async def test_google_drive_not_connected_returns_error():
    # given — no token
    from app.tools.google import drive as google_drive

    # when — list_google_drive_files is called
    with patch("app.tools.google.common.get_tokens", return_value=None):
        result = await google_drive.list_google_drive_files("suid-x")

    # then — graceful error dict
    assert isinstance(result, dict)
    assert result["success"] is False
    assert "Google not connected" in result["error"]


# ── Group 3: Twitter — not connected ────────────────────────────────────────────

async def test_post_tweet_not_connected_returns_error():
    # given — no Twitter token
    from app.tools import twitter as twitter_tools

    # when — post_tweet is called
    with patch("app.tools.twitter.get_tokens", return_value=None):
        result = await twitter_tools.post_tweet("suid-x", text="hello world")

    # then — error dict, not an exception
    assert isinstance(result, dict)
    assert result["success"] is False
    assert "Twitter not connected" in result["error"]


async def test_read_timeline_not_connected_returns_error():
    # given — no Twitter token
    from app.tools import twitter as twitter_tools

    # when — read_timeline is called
    with patch("app.tools.twitter.get_tokens", return_value=None):
        result = await twitter_tools.read_timeline("suid-x")

    # then — error dict
    assert isinstance(result, dict)
    assert result["success"] is False
    assert "Twitter not connected" in result["error"]


async def test_send_twitter_dm_not_connected_returns_error():
    # given — no Twitter token
    from app.tools import twitter as twitter_tools

    # when — send_twitter_dm is called
    with patch("app.tools.twitter.get_tokens", return_value=None):
        result = await twitter_tools.send_twitter_dm("suid-x", "someuser", "hi")

    # then — error dict
    assert isinstance(result, dict)
    assert result["success"] is False
    assert "Twitter not connected" in result["error"]


# ── Group 4: LinkedIn — not connected ───────────────────────────────────────────

async def test_post_to_linkedin_not_connected_returns_error():
    # given — no LinkedIn token
    from app.tools import linkedin as linkedin_tools

    # when — post_to_linkedin is called
    with patch("app.tools.linkedin.get_tokens", return_value=None):
        result = await linkedin_tools.post_to_linkedin("suid-x", text="posting")

    # then — error dict, not an exception
    assert isinstance(result, dict)
    assert result["success"] is False
    assert "LinkedIn not connected" in result["error"]


async def test_send_linkedin_dm_not_connected_returns_error():
    # given — LinkedIn DM send is a Partner-Program-gated placeholder; it never
    # consults tokens, so it is "not connected"-safe by construction
    from app.tools import linkedin as linkedin_tools

    # when — send_linkedin_dm is called with no token
    with patch("app.tools.linkedin.get_tokens", return_value=None):
        result = await linkedin_tools.send_linkedin_dm("suid-x", "someone", "hi")

    # then — error dict (placeholder), not an exception
    assert isinstance(result, dict)
    assert result["success"] is False
    assert result.get("placeholder") is True


async def test_read_linkedin_dms_not_connected_returns_error():
    # given — LinkedIn DM read is also a placeholder
    from app.tools import linkedin as linkedin_tools

    # when — read_linkedin_dms is called
    with patch("app.tools.linkedin.get_tokens", return_value=None):
        result = await linkedin_tools.read_linkedin_dms("suid-x")

    # then — error dict (placeholder)
    assert isinstance(result, dict)
    assert result["success"] is False
    assert result.get("placeholder") is True


# ── Group 5: Notion — not connected ─────────────────────────────────────────────

async def test_search_notion_not_connected_returns_error():
    # given — no Notion token
    from app.tools import notion as notion_tools

    # when — search_notion is called
    with patch("app.tools.notion.get_tokens", return_value=None):
        result = await notion_tools.search_notion("suid-x", query="roadmap")

    # then — error dict, not an exception
    assert isinstance(result, dict)
    assert result["success"] is False
    assert "Notion not connected" in result["error"]


async def test_create_notion_page_not_connected_returns_error():
    # given — no Notion token
    from app.tools import notion as notion_tools

    # when — create_notion_page is called (get_notion_database + pages insert
    # both route through _notion_request, which raises → caught → error dict)
    with patch("app.tools.notion.get_tokens", return_value=None):
        result = await notion_tools.create_notion_page(
            "suid-x", parent_id="parent-123", title="New Page"
        )

    # then — error dict
    assert isinstance(result, dict)
    assert result["success"] is False
    assert "Notion not connected" in result["error"]


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


# ── Group 8: Connect flow (password auth) ───────────────────────────────────────

def _connect_client(mock_pool):
    """ASGI client over app.main with app.db.get_pool patched to a mock pool.
    Group 8 exercises the /connect HTTP surface without a live Postgres."""
    with patch("app.connect.get_pool", return_value=mock_pool):
        from app.main import app
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_connect_creates_new_user_and_issues_token():
    # given — a brand-new email (no existing user row)
    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = None  # user does not exist yet
    mock_pool.fetchval.return_value = "00000000-0000-0000-0000-000000000abc"  # new id

    # when — POST /connect with valid form data
    async with _connect_client(mock_pool) as c:
        r = await c.post("/connect", data={"email": "newuser@example.com", "password": "strongpass1"})

    # then — 200 with a ready-to-paste MCP config carrying a bearer token
    assert r.status_code == 200
    assert "mcpServers" in r.text
    assert "Authorization: Bearer" in r.text
    mock_pool.fetchval.assert_awaited_once()  # a new user was inserted


async def test_connect_existing_user_correct_password_issues_token():
    # given — an existing user with a real password hash
    from app.passwords import hash_password

    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = {
        "id": "00000000-0000-0000-0000-000000000def",
        "password_hash": hash_password("correcthorse"),
    }

    # when — POST /connect with the correct password
    async with _connect_client(mock_pool) as c:
        r = await c.post("/connect", data={"email": "known@example.com", "password": "correcthorse"})

    # then — 200, token issued, and NO new user inserted
    assert r.status_code == 200
    assert "Authorization: Bearer" in r.text
    mock_pool.fetchval.assert_not_awaited()


async def test_connect_existing_user_wrong_password_rejected():
    # given — an existing user with a known hash
    from app.passwords import hash_password

    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = {
        "id": "00000000-0000-0000-0000-000000000fed",
        "password_hash": hash_password("correcthorse"),
    }

    # when — POST /connect with the WRONG password
    async with _connect_client(mock_pool) as c:
        r = await c.post("/connect", data={"email": "known@example.com", "password": "wrongpass99"})

    # then — 401, and the account is never mutated (no takeover)
    assert r.status_code == 401
    mock_pool.fetchval.assert_not_awaited()


async def test_connect_short_password_rejected():
    # given — a password shorter than MIN_PASSWORD_LENGTH (8)
    mock_pool = AsyncMock()

    # when — POST /connect with a too-short password
    async with _connect_client(mock_pool) as c:
        r = await c.post("/connect", data={"email": "x@example.com", "password": "ab"})

    # then — 400, and the DB is never even touched
    assert r.status_code == 400
    mock_pool.fetchrow.assert_not_awaited()
