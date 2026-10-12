"""S09: per-assistant scopes, revoke gates, and the deterministic tool eval."""
import time
from unittest.mock import AsyncMock

import jwt

from app.auth import issue_client_token, verify_access_meta
from app.config import settings
from app.services.mcp_scopes import (
    DEFAULT_SCOPES,
    MEMORY_TOOLS,
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


def test_legacy_user_scope_sees_productivity_tools():
    assert tool_visible("search_gmail_emails", ["user"]) is True


def test_approve_needs_scope_and_confirmation():
    assert approve_gate(["memory:write"], True) == "missing_scope"
    assert approve_gate(["memory:write", "cards:approve"], False) == "confirmation_required"
    assert approve_gate(["cards:approve"], True) is None


def test_tool_log_has_no_secret_fields():
    row = tool_log_row("remember", ok=True, ms=12, error_class=None, jti="abc")
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
