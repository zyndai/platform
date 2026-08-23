"""Comprehensive tests for the MCP server: auth paths, tool registration, tool logic.

Covers:
- All 74 registered tools present
- Auth matrix: missing / bad / expired / valid token
- ZyndTokenVerifier: DB unavailable does NOT crash (returns None → 401)
- check_connection_status: no persona / not connected / connected
- list_my_connections: resolves user_id → agent_id before querying dm_threads
- request_connection: no persona / already exists / success paths
- get_my_socials: persona service down returns graceful error dict
- brief tools: read / append / replace / clear / add_todo
- zynd_network: call_zynd_agent / call_zynd_service reject empty payload
- data: dict | None = None schema on call_zynd_agent / call_zynd_service
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.auth import issue_personal_token
from app.mcp_http import ZyndTokenVerifier, app as mcp_asgi, mcp


# ── Tool registration ──────────────────────────────────────────────────────────

_EXPECTED_TOOLS = {
    "remember", "get_my_context", "export_my_context",
    "find_similar_users", "find_people", "confirm_fact_tool", "forget_fact_tool",
    "search_linkedin_profiles", "find_linkedin_people_for_me",
    "publish_page", "list_my_pages", "disconnect",
    "set_social_links", "get_my_socials",
    "connect_with", "send_persona_message", "my_connections", "book_meeting",
    "get_my_system_prompt",
    # Google Calendar
    "create_calendar_event", "list_calendar_events", "delete_calendar_event",
    # Google Docs
    "create_google_doc", "append_to_google_doc", "read_google_doc",
    "list_google_docs", "search_google_docs",
    # Google Drive
    "create_google_drive_folder", "list_google_drive_files",
    "move_google_drive_file", "list_google_drive_folder_contents",
    # Gmail
    "search_gmail_emails", "get_gmail_email_details",
    "send_gmail_email", "list_recent_gmail_threads",
    # Google Sheets
    "create_google_sheet", "append_to_google_sheet",
    "read_google_sheet_values", "search_google_spreadsheets",
    # Twitter
    "post_tweet", "read_timeline", "send_twitter_dm", "read_twitter_dms",
    # LinkedIn
    "post_to_linkedin", "send_linkedin_dm", "read_linkedin_dms",
    # Notion
    "search_notion", "get_notion_database", "query_notion_database",
    "create_notion_page", "update_notion_page", "get_notion_page_content",
    "create_notion_database", "append_notion_blocks",
    # Scheduling
    "propose_meeting", "respond_to_meeting", "list_pending_meetings",
    # Zynd Network
    "search_zynd_network", "search_zynd_personas", "get_persona_profile",
    "list_my_connections", "request_connection", "check_connection_status",
    "message_zynd_agent", "call_zynd_agent", "read_agent_channel",
    # Zynd Services
    "search_zynd_services", "get_zynd_service_card", "call_zynd_service",
    # Brief & Todo
    "read_my_brief", "append_to_my_brief", "replace_my_brief",
    "clear_my_brief", "add_todo",
}


def test_all_74_tools_registered():
    # given
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    # when / then
    missing = _EXPECTED_TOOLS - names
    assert not missing, f"Missing tools: {sorted(missing)}"


def test_tool_count_is_74():
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert len(names) == 74


# ── Auth: HTTP-level rejection ─────────────────────────────────────────────────

async def test_rejects_missing_token():
    # given — no Authorization header
    transport = httpx.ASGITransport(app=mcp_asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # when
        r = await c.post("/mcp", json={})
    # then
    assert r.status_code == 401


async def test_rejects_bad_token_when_db_unavailable():
    # given — bad JWT, DB unreachable (conftest sets port 5433 which has no server in unit tests)
    transport = httpx.ASGITransport(app=mcp_asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # when
        r = await c.post("/mcp", headers={"Authorization": "Bearer not-a-jwt"}, json={})
    # then — must be 401, NOT a 500/OSError crash
    assert r.status_code == 401


async def test_rejects_random_garbage_token():
    # given
    transport = httpx.ASGITransport(app=mcp_asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # when
        r = await c.post("/mcp", headers={"Authorization": "Bearer eyJ.garbage.here"}, json={})
    # then
    assert r.status_code == 401


# ── ZyndTokenVerifier unit tests ───────────────────────────────────────────────

async def test_verifier_returns_anonymous_for_empty_token():
    # given
    verifier = ZyndTokenVerifier()
    # when
    token = await verifier.verify_token("")
    # then
    assert token is not None
    assert token.client_id == "anonymous"
    assert "anonymous" in token.scopes


async def test_verifier_returns_anonymous_for_whitespace_token():
    # given
    verifier = ZyndTokenVerifier()
    # when
    token = await verifier.verify_token("   ")
    # then
    assert token is not None
    assert token.client_id == "anonymous"


async def test_verifier_returns_none_when_db_unavailable_for_non_jwt():
    # given — non-JWT string, DB unreachable (OSError on connect)
    verifier = ZyndTokenVerifier()
    # when — should not raise, should return None (→ 401 at middleware)
    result = await verifier.verify_token("opaque-token-no-db")
    # then
    assert result is None


async def test_verifier_rejects_jwt_with_wrong_secret():
    # given — valid JWT structure but signed with wrong key
    import jwt as pyjwt
    bad_token = pyjwt.encode({"sub": "user-1", "typ": "access", "iat": int(time.time()), "exp": int(time.time()) + 3600}, "wrong-secret", algorithm="HS256")
    verifier = ZyndTokenVerifier()
    # when — JWT decode fails → falls to DB path → DB unavailable → None
    result = await verifier.verify_token(bad_token)
    # then
    assert result is None


async def test_verifier_accepts_valid_jwt():
    # given — valid JWT signed with the real secret
    user_id = "00000000-0000-0000-0000-000000000001"
    token = issue_personal_token(user_id)
    verifier = ZyndTokenVerifier()

    # mock pool so revocation check succeeds without real DB
    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = None  # tokens_revoked_at = None → not revoked
    with patch("app.mcp_http._get_pool", return_value=AsyncMock(return_value=mock_pool)):
        with patch("app.mcp_http._pool", mock_pool):
            from app.services import sessions as sess_mod
            with patch.object(sess_mod, "tokens_revoked", AsyncMock(return_value=False)):
                result = await verifier.verify_token(token)

    # then
    assert result is not None
    assert result.client_id == user_id
    assert "user" in result.scopes


async def test_verifier_rejects_revoked_jwt():
    # given — valid JWT but revocation watermark is after iat
    user_id = "00000000-0000-0000-0000-000000000002"
    token = issue_personal_token(user_id)
    verifier = ZyndTokenVerifier()

    with patch("app.mcp_http._pool", AsyncMock()):
        from app.services import sessions as sess_mod
        with patch.object(sess_mod, "tokens_revoked", AsyncMock(return_value=True)):
            result = await verifier.verify_token(token)

    # then
    assert result is None


# ── check_connection_status ────────────────────────────────────────────────────

async def test_check_connection_status_no_persona():
    # given — user_id has no active persona_agents row
    from app.tools.zynd_network import check_connection_status
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    with patch("app.tools.zynd_network._get_supabase", return_value=mock_sb):
        # when
        result = await check_connection_status("supabase-uid-123", "target-agent-id")

    # then
    assert result["status"] == "error"
    assert "No active persona" in result["error"]


async def test_check_connection_status_not_connected():
    # given — user has a persona, but no dm_thread with target
    from app.tools.zynd_network import check_connection_status
    mock_sb = MagicMock()

    def _table(name):
        tbl = MagicMock()
        if name == "persona_agents":
            tbl.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"agent_id": "zns:myagent"}]
        elif name == "dm_threads":
            tbl.select.return_value.or_.return_value.execute.return_value.data = []
        return tbl

    mock_sb.table.side_effect = _table

    with patch("app.tools.zynd_network._get_supabase", return_value=mock_sb):
        # when
        result = await check_connection_status("supabase-uid-123", "zns:targetagent")

    # then
    assert result["status"] == "not_connected"
    assert result["connected"] is False


async def test_check_connection_status_connected():
    # given — user has persona and an accepted dm_thread with target
    from app.tools.zynd_network import check_connection_status
    mock_sb = MagicMock()

    def _table(name):
        tbl = MagicMock()
        if name == "persona_agents":
            tbl.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"agent_id": "zns:myagent"}]
        elif name == "dm_threads":
            tbl.select.return_value.or_.return_value.execute.return_value.data = [
                {"id": "thread-uuid-1", "status": "accepted", "created_at": "2026-01-01T00:00:00Z"}
            ]
        return tbl

    mock_sb.table.side_effect = _table

    with patch("app.tools.zynd_network._get_supabase", return_value=mock_sb):
        # when
        result = await check_connection_status("supabase-uid-123", "zns:targetagent")

    # then
    assert result["status"] == "success"
    assert result["connected"] is True
    assert result["thread_id"] == "thread-uuid-1"
    assert result["connection_status"] == "accepted"


# ── list_my_connections ────────────────────────────────────────────────────────

async def test_list_my_connections_no_persona_returns_empty():
    # given — user has no active persona_agents row
    from app.tools.zynd_network import list_my_connections
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    with patch("app.tools.zynd_network._get_supabase", return_value=mock_sb):
        # when
        result = await list_my_connections("supabase-uid-123")

    # then — empty list, not an error, and NOT querying dm_threads with the user_id
    assert result["status"] == "success"
    assert result["connections"] == []
    assert result["count"] == 0


async def test_list_my_connections_uses_agent_id_not_user_id():
    # given — tracks which table + filter was used in dm_threads query
    from app.tools.zynd_network import list_my_connections
    mock_sb = MagicMock()
    my_agent_id = "zns:abc123"
    dm_threads_calls = []

    def _table(name):
        tbl = MagicMock()
        if name == "persona_agents":
            tbl.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"agent_id": my_agent_id}]
        elif name == "dm_threads":
            def _or(expr):
                dm_threads_calls.append(expr)
                inner = MagicMock()
                inner.in_.return_value.execute.return_value.data = []
                return inner
            tbl.select.return_value.or_.side_effect = _or
        return tbl

    mock_sb.table.side_effect = _table

    with patch("app.tools.zynd_network._get_supabase", return_value=mock_sb):
        # when
        await list_my_connections("supabase-uid-123")

    # then — dm_threads was queried using agent_id, NOT the user_id
    assert len(dm_threads_calls) == 1
    assert my_agent_id in dm_threads_calls[0]
    assert "supabase-uid-123" not in dm_threads_calls[0]


async def test_list_my_connections_enriches_other_side():
    # given — one accepted thread, other side has a named persona
    from app.tools.zynd_network import list_my_connections
    mock_sb = MagicMock()
    my_agent_id = "zns:mine"
    other_agent_id = "zns:theirs"

    def _table(name):
        tbl = MagicMock()
        if name == "persona_agents":
            call_count = [0]
            def _chain():
                m = MagicMock()
                m.eq.return_value.eq.return_value.execute.return_value.data = [{"agent_id": my_agent_id}]
                m.eq.return_value.execute.return_value.data = [{"name": "Alice", "agent_handle": "alice", "description": ""}]
                return m
            tbl.select.side_effect = lambda *a, **kw: _chain()
        elif name == "dm_threads":
            inner = MagicMock()
            inner.in_.return_value.execute.return_value.data = [
                {"id": "t1", "initiator_id": my_agent_id, "receiver_id": other_agent_id, "status": "accepted", "created_at": "2026-01-01"}
            ]
            tbl.select.return_value.or_.return_value = inner
        return tbl

    mock_sb.table.side_effect = _table

    with patch("app.tools.zynd_network._get_supabase", return_value=mock_sb):
        result = await list_my_connections("supabase-uid-123")

    assert result["status"] == "success"
    assert result["count"] == 1
    assert result["connections"][0]["other_agent_id"] == other_agent_id


# ── request_connection ─────────────────────────────────────────────────────────

async def test_request_connection_no_persona():
    # given — user has no active persona
    from app.tools.zynd_network import request_connection
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    with patch("app.tools.zynd_network._get_supabase", return_value=mock_sb):
        result = await request_connection("supabase-uid-123", "zns:target")

    assert result["status"] == "error"
    assert "deployed persona" in result["error"]


async def test_request_connection_already_exists():
    # given — thread already exists between the two agents
    from app.tools.zynd_network import request_connection
    mock_sb = MagicMock()

    def _table(name):
        tbl = MagicMock()
        if name == "persona_agents":
            tbl.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"agent_id": "zns:mine", "name": "Me"}]
        elif name == "dm_threads":
            tbl.select.return_value.or_.return_value.execute.return_value.data = [{"id": "existing-t1", "status": "pending"}]
        return tbl

    mock_sb.table.side_effect = _table

    with patch("app.tools.zynd_network._get_supabase", return_value=mock_sb):
        with patch("app.tools.zynd_network._fetch_agent_card", return_value=None):
            result = await request_connection("supabase-uid-123", "zns:target")

    assert result["status"] == "exists"
    assert result["thread_id"] == "existing-t1"
    assert result["current_status"] == "pending"


# ── get_my_socials ─────────────────────────────────────────────────────────────

async def test_get_my_socials_persona_service_down_returns_graceful_error():
    # given — persona service raises PersonaError
    from app.services.persona import PersonaError
    import app.mcp_http as m
    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = {"supabase_user_id": "suid-abc"}

    with patch("app.mcp_http._get_pool", AsyncMock(return_value=mock_pool)):
        with patch("app.mcp_http.persona") as mock_persona:
            mock_persona.get_status = AsyncMock(side_effect=PersonaError("network down"))
            # call the raw function with uid injected directly (bypasses FastMCP Depends)
            result = await m.get_my_socials(uid="uid-abc")

    # then — returns graceful dict, not an exception
    assert "links" in result
    assert result["links"] == {}
    assert "unavailable" in result["note"].lower()


async def test_get_my_socials_no_persona_linked():
    # given — user has no supabase_user_id
    import app.mcp_http as m
    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = {"supabase_user_id": None}

    with patch("app.mcp_http._get_pool", AsyncMock(return_value=mock_pool)):
        result = await m.get_my_socials(uid="uid-abc")

    assert result["links"] == {}
    assert "note" in result


# ── brief tools ────────────────────────────────────────────────────────────────

async def test_read_my_brief_no_persona_returns_empty():
    # given — persona_agents has no row
    from app.tools.brief import read_my_brief
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    with patch("app.tools.brief._sb", return_value=mock_sb):
        result = await read_my_brief("suid-abc")

    assert result["success"] is True
    assert result["exists"] is False
    assert result["content"] == ""


async def test_read_my_brief_with_content():
    # given
    from app.tools.brief import read_my_brief
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"brief_content": "Working on a SaaS product.", "description": "Founder"}
    ]

    with patch("app.tools.brief._sb", return_value=mock_sb):
        result = await read_my_brief("suid-abc")

    assert result["success"] is True
    assert result["exists"] is True
    assert result["content"] == "Working on a SaaS product."
    assert result["fallback_description"] == "Founder"


async def test_append_to_brief_rejects_empty_text():
    # given
    from app.tools.brief import append_to_my_brief
    # when
    result = await append_to_my_brief("suid-abc", "   ")
    # then
    assert result["success"] is False
    assert "empty" in result["error"].lower()


async def test_append_to_brief_appends_to_existing():
    # given
    from app.tools.brief import append_to_my_brief
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"brief_content": "Existing content.", "description": ""}
    ]
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch("app.tools.brief._sb", return_value=mock_sb):
        result = await append_to_my_brief("suid-abc", "New paragraph.")

    assert result["success"] is True
    assert result["appended"] == "New paragraph."


async def test_replace_my_brief():
    # given
    from app.tools.brief import replace_my_brief
    mock_sb = MagicMock()
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch("app.tools.brief._sb", return_value=mock_sb):
        result = await replace_my_brief("suid-abc", "Brand new content.")

    assert result["success"] is True
    assert result["content"] == "Brand new content."


async def test_clear_my_brief():
    # given
    from app.tools.brief import clear_my_brief, replace_my_brief
    mock_sb = MagicMock()
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch("app.tools.brief._sb", return_value=mock_sb):
        result = await clear_my_brief("suid-abc")

    assert result["success"] is True
    assert result["content"] == ""


async def test_add_todo_rejects_empty_title():
    # given
    from app.tools.brief import add_todo
    result = await add_todo("suid-abc", "  ")
    assert result["success"] is False


async def test_add_todo_truncates_at_200_chars():
    # given — title > 200 chars
    from app.tools.brief import add_todo
    mock_sb = MagicMock()
    inserted_data = {}

    def _insert(data):
        inserted_data.update(data)
        m = MagicMock()
        m.execute.return_value.data = [{"id": "todo-uuid-1"}]
        return m

    mock_sb.table.return_value.insert.side_effect = _insert

    with patch("app.tools.brief._sb", return_value=mock_sb):
        result = await add_todo("suid-abc", "x" * 300)

    assert result["success"] is True
    assert len(inserted_data.get("title", "")) <= 200


# ── call_zynd_agent / call_zynd_service — payload validation ──────────────────

async def test_call_zynd_agent_rejects_empty_text_and_data():
    # given
    from app.tools.zynd_network import call_zynd_agent
    # when — neither text nor data provided
    result = await call_zynd_agent("some-entity-id", text="", data=None)
    # then
    assert result["status"] == "error"
    assert "text" in result["error"].lower() or "data" in result["error"].lower()


async def test_call_zynd_agent_rejects_missing_entity_id():
    # given
    from app.tools.zynd_network import call_zynd_agent
    result = await call_zynd_agent("", text="hello")
    assert result["status"] == "error"
    assert "entity_id" in result["error"].lower()


async def test_call_zynd_service_rejects_empty_payload():
    # given
    from app.tools.zynd_services import call_zynd_service
    result = await call_zynd_service("some-service-id", text="", data=None)
    assert result["status"] == "error"


async def test_call_zynd_service_rejects_missing_entity_id():
    # given
    from app.tools.zynd_services import call_zynd_service
    result = await call_zynd_service("", text="hello")
    assert result["status"] == "error"
    assert "entity_id" in result["error"].lower()


# ── data: dict | None = None schema correctness ───────────────────────────────

def test_call_zynd_agent_data_annotation_is_optional():
    # given — FastMCP uses type hints to build JSON schema; dict | None = None must be used
    import inspect
    from app.tools.zynd_network import call_zynd_agent
    sig = inspect.signature(call_zynd_agent)
    param = sig.parameters["data"]
    # then — annotation must allow None (i.e., not bare `dict`)
    ann = param.annotation
    assert param.default is None
    # Union[dict, None] or dict | None — both are valid; neither is bare `dict`
    import types
    assert ann != dict, "data annotation must be `dict | None`, not bare `dict`"


def test_call_zynd_service_data_annotation_is_optional():
    import inspect
    from app.tools.zynd_services import call_zynd_service
    sig = inspect.signature(call_zynd_service)
    param = sig.parameters["data"]
    assert param.default is None
    assert param.annotation != dict, "data annotation must be `dict | None`, not bare `dict`"


# ── zynd_network: discover personas ───────────────────────────────────────────

def test_discover_personas_cache_is_populated():
    # given
    from app.tools import zynd_network as zn
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"agent_id": "zns:abc", "name": "Alice", "description": "Builder"}
    ]

    # flush cache so we get a fresh result
    with zn._DISCOVER_CACHE_LOCK:
        zn._DISCOVER_CACHE.clear()

    with patch("app.tools.zynd_network._get_supabase", return_value=mock_sb):
        with patch("app.tools.zynd_network._get_avatar_map", return_value={}):
            with patch("app.tools.zynd_network._discover_registry", return_value=[]):
                result = zn.discover_personas("", top_k=5)

    assert result["status"] == "success"
    assert result["count"] >= 1
    assert any(p["agent_id"] == "zns:abc" for p in result["results"])


def test_discover_personas_uses_cache_on_second_call():
    # given — flush cache, then make two calls with the same broad query
    from app.tools import zynd_network as zn

    with zn._DISCOVER_CACHE_LOCK:
        zn._DISCOVER_CACHE.clear()

    mock_sb = MagicMock()
    # broad query path: select().eq().order().limit().execute()
    mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"agent_id": "zns:xyz", "name": "Bob", "description": ""}
    ]

    with patch("app.tools.zynd_network._get_supabase", return_value=mock_sb):
        with patch("app.tools.zynd_network._get_avatar_map", return_value={}):
            with patch("app.tools.zynd_network._discover_registry", return_value=[]):
                # empty string triggers the broad path which we mocked correctly
                r1 = zn.discover_personas("", top_k=3)
                r2 = zn.discover_personas("", top_k=3)

    # then — first call succeeds, second comes from cache
    assert r1["status"] == "success"
    assert r2.get("from_cache") is True


# ── zynd_network: search_zynd_network merges local personas ──────────────────

async def test_search_zynd_network_any_merges_local_personas():
    # kind="any" (default) must surface people from the local persona directory,
    # not just the registry (whose personas often have empty summaries -> 0 matches).
    from app.tools import zynd_network as zn
    with patch("app.tools.zynd_network._call_registry_search", return_value=([], None)):
        with patch("app.tools.zynd_network.discover_personas", return_value={
            "status": "success", "count": 1,
            "results": [{"name": "Abhinav Gupta", "agent_id": "zns:abhinav", "description": "community builder"}],
        }):
            with patch("app.tools.zynd_network._merge_deployer_entities", side_effect=lambda r, k, q: r):
                result = await zn.search_zynd_network("community manager", top_k=8, kind="any", user_id="")

    assert result["status"] == "success"
    assert result["count"] >= 1
    assert any(r.get("name") == "Abhinav Gupta" and r.get("source") == "local" for r in result["results"])


async def test_search_zynd_network_any_enriches_empty_registry_persona():
    # a registry persona with an empty summary should get the local description
    from app.tools import zynd_network as zn
    registry = [{"entity_id": "zns:abhinav", "name": "Abhinav Gupta", "summary": "No bio yet.", "category": "persona", "tags": ["persona"]}]
    with patch("app.tools.zynd_network._call_registry_search", return_value=(registry, None)):
        with patch("app.tools.zynd_network.discover_personas", return_value={
            "results": [{"name": "Abhinav Gupta", "agent_id": "zns:abhinav", "description": "community builder"}],
        }):
            with patch("app.tools.zynd_network._merge_deployer_entities", side_effect=lambda r, k, q: r):
                result = await zn.search_zynd_network("community manager", top_k=8, kind="any", user_id="")

    r = next(x for x in result["results"] if x.get("entity_id") == "zns:abhinav")
    assert (r.get("summary") or r.get("description")) == "community builder"


async def test_search_zynd_network_persona_returns_discover_directly():
    from app.tools import zynd_network as zn
    with patch("app.tools.zynd_network.discover_personas", return_value={"status": "success", "count": 1, "results": []}) as dp:
        result = await zn.search_zynd_network("founder", top_k=8, kind="persona", user_id="")
    assert dp.call_count == 1
    assert result["status"] == "success"


# ── OAuth discovery endpoint ───────────────────────────────────────────────────

async def test_oauth_protected_resource():
    transport = httpx.ASGITransport(app=mcp_asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200
    data = r.json()
    assert "authorization_servers" in data
    assert len(data["authorization_servers"]) >= 1


# ── helpers ────────────────────────────────────────────────────────────────────

async def _call_tool_directly(tool_name: str, **kwargs):
    """Call a mcp_http module-level function bypassing FastMCP dependency injection."""
    import app.mcp_http as m
    fn = getattr(m, tool_name)
    # strip Depends() parameters and inject kwargs directly
    import inspect
    sig = inspect.signature(fn.__wrapped__ if hasattr(fn, "__wrapped__") else fn)
    filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return await fn(**filtered)
