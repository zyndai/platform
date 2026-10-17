"""Hide tools the assistant was not granted, and log the call without arguments."""
from __future__ import annotations

import time

from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from app.config import settings
from app.services.mcp_scopes import PLUGIN_SCOPES, plugin_tool_visible, tool_log_row, tool_visible


def _plugin(token) -> bool:
    return bool(token and (token.claims or {}).get("oauth_client_id") == settings.plugin_oauth_client_id)


class ScopeGate(Middleware):
    async def on_initialize(self, context: MiddlewareContext, call_next: CallNext):
        result = await call_next(context)
        token = get_access_token()
        if result is not None and _plugin(token):
            instructions = (
                "Read private facts only when the user requests recall, never automatically. "
                "Propose a single durable fact only after the user asks or agrees; a proposal "
                "does not save memory. The owner saves it on the signed-in ZYND review page. "
                "Card drafts stay private until the owner separately confirms the exact public "
                "wording on ZYND. Never send secrets or claim pending proposals are saved or public."
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
        if _plugin(token):
            return [resource for resource in resources if not str(resource.uri).startswith("skill://")]
        return resources

    async def on_list_resource_templates(self, context: MiddlewareContext, call_next: CallNext):
        templates = await call_next(context)
        token = get_access_token()
        if _plugin(token):
            return [template for template in templates if not str(template.uri_template).startswith("skill://")]
        return templates

    async def on_read_resource(self, context: MiddlewareContext, call_next: CallNext):
        token = get_access_token()
        if (_plugin(token) and
                str(context.message.uri).startswith("skill://")):
            raise PermissionError("This plugin uses its packaged skills, not connector skill resources.")
        return await call_next(context)

    async def on_list_tools(self, context: MiddlewareContext, call_next: CallNext):
        tools = await call_next(context)
        token = get_access_token()
        scopes = list(token.scopes) if token and token.scopes else []
        if _plugin(token):
            return [tool for tool in tools if plugin_tool_visible(tool.name, scopes)]
        if token is None or not scopes or "user" in scopes:
            return tools
        return [tool for tool in tools if tool_visible(tool.name, scopes)]

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext):
        token = get_access_token()
        scopes = list(token.scopes) if token and token.scopes else ["user"]
        name = getattr(context.message, "name", "") or ""
        if _plugin(token) and not plugin_tool_visible(name, scopes):
            raise PermissionError("This ZYND plugin cannot call that tool.")
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
