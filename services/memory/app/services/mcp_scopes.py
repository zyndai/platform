"""Which MCP tools a token's scopes may see.

A legacy token (scope ``user``, or no ``scp`` claim) sees the full server.
A new assistant token sees only the toolsets it was granted. The default
grant is ``memory:write``, which stays under 15 tools.
"""
from __future__ import annotations

ALLOWED_SCOPES = (
    "memory:write",
    "cards:read",
    "cards:approve",
    "people:message",
)
DEFAULT_SCOPES = ["memory:write"]

MEMORY_TOOLS = frozenset({
    "report_user_info",
    "get_my_context",
    "confirm_fact_tool",
    "forget_fact_tool",
})
CARDS_READ_TOOLS = frozenset({
    "list_pending_facts",
    "list_intros",
})
CARDS_APPROVE_TOOLS = frozenset({
    "approve_fact",
    "dismiss_fact",
    "set_looking_for",
    "update_headline",
})
PEOPLE_TOOLS = frozenset({
    "find_people",
    "connect_with",
    "send_persona_message",
    "message_zynd_agent",
})


def normalize_scopes(scopes: list[str] | None) -> list[str]:
    chosen = []
    for scope in scopes or []:
        if scope in ALLOWED_SCOPES and scope not in chosen:
            chosen.append(scope)
    if "memory:write" not in chosen:
        chosen.insert(0, "memory:write")
    return chosen


def tool_visible(name: str, scopes: list[str]) -> bool:
    """Legacy ``user`` tokens see every tool. Scoped tokens see their toolset."""
    if "user" in scopes:
        return True
    if name in MEMORY_TOOLS and "memory:write" in scopes:
        return True
    if name in CARDS_READ_TOOLS and "cards:read" in scopes:
        return True
    if name in CARDS_APPROVE_TOOLS and "cards:approve" in scopes:
        return True
    if name in PEOPLE_TOOLS and "people:message" in scopes:
        return True
    return False


def approve_gate(scopes: list[str], confirm: bool) -> str | None:
    """None when an AI may publish. Otherwise an error code, no fact text."""
    if "cards:approve" not in scopes and "user" not in scopes:
        return "missing_scope"
    if not confirm:
        return "confirmation_required"
    return None


def select_tool(prompt: str) -> str:
    """Deterministic stand-in for the model eval. Golden prompts map here."""
    text = (prompt or "").lower()
    if "approve" in text:
        return "approve_fact"
    if "dismiss" in text or "keep private" in text:
        return "dismiss_fact"
    if "looking for" in text or "seeking" in text:
        return "set_looking_for"
    if "pending" in text or "inbox" in text:
        return "list_pending_facts"
    if "headline" in text:
        return "update_headline"
    if "find people" in text or "who should i" in text:
        return "find_people"
    if "remember" in text or "i am building" in text or "i'm building" in text:
        return "report_user_info"
    return "get_my_context"


def tool_log_row(tool: str, *, ok: bool, ms: int, error_class: str | None, jti: str | None) -> dict:
    """The only fields written for a tool call. Arguments never enter this row."""
    return {
        "tool": (tool or "")[:80],
        "ok": bool(ok),
        "ms": int(ms),
        "error_class": (error_class or "")[:80] or None,
        "jti": jti,
    }
