"""Hide tools the assistant was not granted, and log the call without arguments."""
from __future__ import annotations

import time

from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from app.services.mcp_scopes import tool_log_row, tool_visible


class ScopeGate(Middleware):
    async def on_list_tools(self, context: MiddlewareContext, call_next: CallNext):
        tools = await call_next(context)
        token = get_access_token()
        scopes = list(token.scopes) if token and token.scopes else []
        if token is None or not scopes or "user" in scopes:
            return tools
        return [tool for tool in tools if tool_visible(tool.name, scopes)]

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext):
        token = get_access_token()
        scopes = list(token.scopes) if token and token.scopes else ["user"]
        name = getattr(context.message, "name", "") or ""
        if token is not None and "user" not in scopes and name and not tool_visible(name, scopes):
            raise PermissionError("This assistant was not granted that tool.")
        started = time.perf_counter()
        try:
            result = await call_next(context)
        except Exception as exc:
            await _log(name, token, False, started, type(exc).__name__)
            raise
        await _log(name, token, True, started, None)
        return result


async def _log(name: str, token, ok: bool, started: float, error_class: str | None) -> None:
    claims = getattr(token, "claims", None) or {}
    row = tool_log_row(
        name,
        ok=ok,
        ms=int((time.perf_counter() - started) * 1000),
        error_class=error_class,
        jti=claims.get("jti"),
    )
    try:
        from app.mcp_http import _get_pool
        from app.services.mcp_clients import record_tool_call
        await record_tool_call(await _get_pool(), getattr(token, "client_id", None), row)
    except Exception:
        return
