"""S09: per-assistant scopes, revoke gates, and the deterministic tool eval."""
import time
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken
from mcp.server.auth.middleware.auth_context import AuthenticatedUser, auth_context_var
from mcp.shared.exceptions import MCPError

import app.mcp_http as m
from app.auth import issue_client_token, verify_access_meta
from app.config import settings
from app.services.mcp_scopes import (
    DEFAULT_SCOPES,
    CARDS_READ_TOOLS,
    MEMORY_TOOLS,
    PEOPLE_TOOLS,
    approve_gate,
    normalize_scopes,
    select_tool,
    tool_log_row,
    tool_visible,
)


def test_default_profile_stays_under_fifteen_tools():
    visible = [name for name in MEMORY_TOOLS if tool_visible(name, DEFAULT_SCOPES)]
    assert len(visible) <= 15
    assert len(visible) == len(set(visible))
    assert "search_gmail_emails" not in {n for n in ("search_gmail_emails",) if tool_visible(n, DEFAULT_SCOPES)}
    assert tool_visible("search_gmail_emails", DEFAULT_SCOPES) is False
    assert tool_visible("report_user_info", DEFAULT_SCOPES) is True
    assert MEMORY_TOOLS == {
        "get_my_context", "report_user_info", "confirm_fact_tool", "forget_fact_tool",
    }
    assert CARDS_READ_TOOLS == {"list_pending_facts", "list_intros"}


def test_legacy_user_scope_still_allows_registered_tools():
    assert tool_visible("export_my_context", ["user"]) is True


def test_approve_needs_scope_and_confirmation():
    assert approve_gate(["memory:write"], True) == "missing_scope"
    assert approve_gate(["memory:write", "cards:approve"], False) == "confirmation_required"
    assert approve_gate(["cards:approve"], True) is None


def test_tool_log_has_no_secret_fields():
    row = tool_log_row("report_user_info", ok=True, ms=12, error_class=None, jti="abc")
    assert set(row) == {"tool", "ok", "ms", "error_class", "jti"}
    assert "token" not in row
    assert "email" not in row


def test_eval_golden_prompts():
    assert select_tool("Remember that I am building SendPilot") == "report_user_info"
    assert select_tool("What is pending in my inbox?") == "list_pending_facts"
    assert select_tool("Approve the rust fact") == "approve_fact"
    assert select_tool("I am looking for a cofounder") == "set_looking_for"
    assert select_tool("Find people who do compliance") == "find_people"


def test_normalize_scopes_always_includes_memory_write():
    assert normalize_scopes(["people:message", "nope"]) == ["memory:write", "people:message"]


async def test_client_token_does_not_bump_version_and_embeds_jti():
    pool = AsyncMock()
    pool.fetchval = AsyncMock(side_effect=[4, "client-1"])
    token, client_id = await issue_client_token(
        pool, "user-1", label="Claude", scopes=["cards:read"],
    )
    assert client_id == "client-1"
    meta = verify_access_meta(token)
    assert meta["ver"] == 4
    assert meta["jti"]
    assert meta["scopes"] == ["memory:write", "cards:read"]
    sql = pool.fetchval.await_args_list[0].args[0]
    assert "token_version = token_version + 1" not in sql
    payload = jwt.decode(
        token, settings.jwt_secret, algorithms=["HS256"],
        issuer=settings.jwt_issuer, options={"verify_aud": False},
    )
    assert payload["exp"] > int(time.time())


@pytest.mark.parametrize("scopes,expected", [
    (["memory:write"], {"get_my_context", "report_user_info", "confirm_fact_tool", "forget_fact_tool"}),
    (["memory:write", "cards:read"], {
        "get_my_context", "report_user_info", "confirm_fact_tool", "forget_fact_tool",
        "list_pending_facts", "list_intros",
    }),
    (["memory:write", "cards:approve"], {
        "get_my_context", "report_user_info", "confirm_fact_tool", "forget_fact_tool",
        "approve_fact", "dismiss_fact", "set_looking_for",
    }),
    (["memory:write", "people:message"], { *MEMORY_TOOLS, *PEOPLE_TOOLS }),
])
async def test_transport_discovery_hides_removed_tools_and_injected_parameters(scopes, expected):
    access = AccessToken(token="test", client_id="alice", subject="alice", scopes=scopes)
    reset = auth_context_var.set(AuthenticatedUser(access))
    try:
        async with Client(m.mcp) as client:
            tools = await client.list_tools()
    finally:
        auth_context_var.reset(reset)
    assert {tool.name for tool in tools} == expected
    context = next(tool for tool in tools if tool.name == "get_my_context")
    assert set(context.input_schema["properties"]) == {"topic", "k"}
    assert context.annotations.read_only_hint is False
    for tool in tools:
        assert "uid" not in tool.input_schema.get("properties", {})
        assert "token" not in tool.input_schema.get("properties", {})


@pytest.mark.parametrize("supplied", [{"k": 7}, {"k": 7, "uid": "bob", "token": {"scopes": ["user"]}}])
async def test_transport_call_injects_caller_and_token_without_model_inputs(supplied):
    access = AccessToken(token="test", client_id="alice", subject="alice", scopes=["memory:write"])
    pool = AsyncMock()
    pool.fetchrow.return_value = {
        "display_name": "Alice", "email": "alice@example.com",
        "supabase_user_id": None, "socials": {},
    }
    reset = auth_context_var.set(AuthenticatedUser(access))
    try:
        with patch.object(m, "_get_pool", AsyncMock(return_value=pool)), \
             patch.object(m, "active_context", AsyncMock(return_value=[])) as facts, \
             patch.object(m, "get_card", AsyncMock(return_value=[])) as card, \
             patch.object(m.brief_tools, "read_my_brief", AsyncMock(return_value={"success": True, "content": ""})), \
             patch("app.tools.card_status.get_owner_status", AsyncMock()) as owner:
            async with Client(m.mcp) as client:
                result = await client.call_tool("get_my_context", supplied, raise_on_error=False)
    finally:
        auth_context_var.reset(reset)
    if result.is_error:
        assert "uid" in supplied
        facts.assert_not_awaited()
        card.assert_not_awaited()
        owner.assert_not_awaited()
        return
    assert result.data["identity"]["name"] == "Alice"
    assert "status" not in result.data and "activity" not in result.data
    facts.assert_awaited_once_with(pool, "alice", 7)
    card.assert_awaited_once_with(pool, "alice")
    owner.assert_not_awaited()


async def test_transport_scoped_token_cannot_call_hidden_owner_write():
    reset = auth_context_var.set(AuthenticatedUser(AccessToken(token="test", client_id="alice", scopes=["memory:write"])))
    try:
        with patch("app.mcp_owner.approve", AsyncMock()) as approve:
            async with Client(m.mcp) as client:
                with pytest.raises(MCPError):
                    await client.call_tool("approve_fact", {"predicate": "has_skill", "object": "Rust", "confirm": True})
    finally:
        auth_context_var.reset(reset)
    approve.assert_not_awaited()


async def test_legacy_transport_excludes_unregistered_tools():
    reset = auth_context_var.set(AuthenticatedUser(AccessToken(token="test", client_id="alice", scopes=["user"])))
    try:
        with patch.object(m, "_get_pool", AsyncMock()):
            async with Client(m.mcp) as client:
                tools = await client.list_tools()
                for removed in ("remember", "update_headline", "search_gmail_emails",
                                "search_linkedin_profiles", "find_linkedin_people_for_me"):
                    with pytest.raises((MCPError, ToolError), match="Unknown tool"):
                        await client.call_tool(removed, {})
    finally:
        auth_context_var.reset(reset)
    names = {tool.name for tool in tools}
    assert len(names) == 29  # Cards-native network tools; ChatGPT plugin tools stay off this server.
    assert {"export_my_context", "publish_page", "find_people", "request_card_connection", "create_card_group"} <= names
    assert names.isdisjoint({
        "remember", "get_my_card", "get_my_socials", "read_my_brief",
        "get_my_system_prompt", "get_card_status", "get_card_activity",
        "update_headline", "search_gmail_emails",
    })


@pytest.mark.parametrize("removed", ["search_gmail_emails", "update_headline"])
async def test_scoped_clients_cannot_call_removed_tools(removed):
    reset = auth_context_var.set(AuthenticatedUser(AccessToken(
        token="test", client_id="alice", scopes=["memory:write", "people:message", "cards:approve"],
    )))
    try:
        with patch.object(m, "_get_pool", AsyncMock()):
            async with Client(m.mcp) as client:
                with pytest.raises((PermissionError, ToolError, MCPError)):
                    await client.call_tool(removed, {})
    finally:
        auth_context_var.reset(reset)
