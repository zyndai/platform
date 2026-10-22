"""Claude plugin MCP. The ChatGPT plugin's six tools, Claude plugin tokens only.

Claude brings its own OAuth client (CIMD or DCR), so a token belongs here when its
audience is CLAUDE_PLUGIN_MCP_PUBLIC_BASE_URL + /mcp; memory mints that audience
only with exactly the plugin scopes. Run from services/memory:

    PYTHONPATH=../chatgpt-plugin:../claude-plugin uvicorn claude_server:app --app-dir ../claude-plugin --port 8092
"""
import base64
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from mcp.types import Icon
from pydantic import AnyHttpUrl

from app.config import settings
from app.db import close_pool, get_pool, init_pool
from app.mcp_http import ZyndTokenVerifier, _get_arq, _get_pool, _uid
from plugin_auth import ExactIssuerAuth
from plugin_mcp import PLUGIN_SCOPES, plugin_tool_visible, register

_INSTRUCTIONS = (
    "Recall private Zynd facts only when the user asks, never automatically. "
    "Propose one durable fact only after the user asks or agrees; a proposal does not "
    "save anything. The owner saves it, or confirms the exact public card wording, on "
    "the signed-in Zynd review page. Never send secrets or say a pending proposal is "
    "saved or public."
)

# Anthropic's directory requires a human-readable title on every tool.
TITLES = {
    "recall_memories": "Recall private facts",
    "propose_memory": "Propose a private fact",
    "get_proposal_status": "Check proposal status",
    "list_pending_facts": "List pending card facts",
    "propose_card_fact": "Propose a public card fact",
    "get_public_card": "Show public card",
}


def is_claude_plugin(token) -> bool:
    return bool(token and settings.feature_claude_plugin and
                (token.claims or {}).get("aud") == settings.claude_plugin_resource_url)


def _titled(tool):
    title = TITLES[tool.name]
    annotations = tool.annotations.model_copy(update={"title": title}) if tool.annotations else None
    return tool.model_copy(update={"title": title, "annotations": annotations})


class ClaudePluginOnly(Middleware):
    async def on_discover(self, context: MiddlewareContext, call_next: CallNext):
        return await self.on_initialize(context, call_next)

    async def on_initialize(self, context: MiddlewareContext, call_next: CallNext):
        result = await call_next(context)
        if result is not None and is_claude_plugin(get_access_token()):
            if isinstance(result, dict):
                result["instructions"] = _INSTRUCTIONS
            else:
                result.instructions = _INSTRUCTIONS
        return result

    async def on_list_tools(self, context: MiddlewareContext, call_next: CallNext):
        tools = await call_next(context)
        token = get_access_token()
        if not is_claude_plugin(token):
            return []
        scopes = list(token.scopes or [])
        return [_titled(tool) for tool in tools if plugin_tool_visible(tool.name, scopes)]

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext):
        token = get_access_token()
        name = getattr(context.message, "name", "") or ""
        scopes = list(token.scopes or []) if token else []
        if not is_claude_plugin(token) or not plugin_tool_visible(name, scopes):
            raise PermissionError("This Zynd plugin cannot call that tool.")
        return await call_next(context)


mcp = None


def build():
    auth = ExactIssuerAuth(
        issuer=settings.public_base_url.rstrip("/"),  # same expression as the issuer in /.well-known/oauth-authorization-server
        token_verifier=ZyndTokenVerifier(required_scopes=[], audiences=[settings.claude_plugin_resource_url]),
        base_url=AnyHttpUrl(settings.claude_plugin_mcp_origin),
        scopes_supported=list(PLUGIN_SCOPES),
        resource_name="ZYND Claude plugin",
    )
    global mcp
    logo = next((path for path in (
        Path("/app/app/assets/zynd.png"),
        Path(__file__).resolve().parents[1] / "memory" / "app" / "assets" / "zynd.png",
    ) if path.is_file()), None)
    icons = [Icon(src=f"data:image/png;base64,{base64.b64encode(logo.read_bytes()).decode('ascii')}",
                  mime_type="image/png", sizes=["400x400"])] if logo else []
    mcp = FastMCP("zynd", auth=auth, instructions=_INSTRUCTIONS, icons=icons)
    register(mcp, _get_pool, _get_arq, _uid)
    mcp.add_middleware(ClaudePluginOnly())
    hosts = [h for h in (urlsplit(settings.claude_plugin_mcp_public_base_url).hostname, "localhost", "127.0.0.1") if h]
    path = urlsplit(settings.claude_plugin_mcp_public_base_url).path.rstrip("/") + "/mcp"
    return mcp.http_app(path=path, stateless_http=True, allowed_hosts=hosts)


app = build()
_inner = app.router.lifespan_context


@asynccontextmanager
async def _lifespan(application):
    await init_pool()
    try:
        async with _inner(application):
            yield
    finally:
        await close_pool()


app.router.lifespan_context = _lifespan
get_pool = get_pool
