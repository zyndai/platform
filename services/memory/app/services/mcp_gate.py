"""Hide tools the assistant was not granted, and log the call without arguments."""
from __future__ import annotations

import time

from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from app.services.mcp_scopes import PLUGIN_SCOPES, tool_log_row, tool_visible


class ScopeGate(Middleware):
    async def on_initialize(self, context: MiddlewareContext, call_next: CallNext):
        result = await call_next(context)
        token = get_access_token()
        if result is not None and token and set(token.scopes or []) == set(PLUGIN_SCOPES):
            instructions = (
                "ZYND provides private memory and public card review. Read get_my_context only "
                "when relevant to the user's request, never automatically at conversation start. "
                "Proactively offer to save durable facts, but call report_user_info only after "
                "the user asks or agrees to save them. Never save secrets. Facts stay private "
                "until explicitly approved for publication. Review list_pending_facts before "
                "approve_fact; obtain explicit confirmation of the exact fact to make public. "
                "Use only available tools and never claim a failed write succeeded. "
                "update_headline directs users to the card editor; it does not edit the headline."
            )
            if isinstance(result, dict):
                result["instructions"] = instructions
            else:
                result.instructions = instructions
        return result

    async def on_discover(self, context: MiddlewareContext, call_next: CallNext):
        return await self.on_initialize(context, call_next)

    async def on_list_resources(self, context: MiddlewareContext, call_next: CallNext):
        resources = await call_next(context)
        token = get_access_token()
        if token and set(token.scopes or []) == set(PLUGIN_SCOPES):
            return [resource for resource in resources if not str(resource.uri).startswith("skill://")]
        return resources

    async def on_list_resource_templates(self, context: MiddlewareContext, call_next: CallNext):
        templates = await call_next(context)
        token = get_access_token()
        if token and set(token.scopes or []) == set(PLUGIN_SCOPES):
            return [template for template in templates if not str(template.uri_template).startswith("skill://")]
        return templates

    async def on_read_resource(self, context: MiddlewareContext, call_next: CallNext):
        token = get_access_token()
        if (token and set(token.scopes or []) == set(PLUGIN_SCOPES) and
                str(context.message.uri).startswith("skill://")):
            raise PermissionError("This plugin uses its packaged skills, not connector skill resources.")
        return await call_next(context)

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
