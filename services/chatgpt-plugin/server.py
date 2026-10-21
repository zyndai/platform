"""ChatGPT plugin MCP. Six tools, plugin tokens only.

Run from services/memory so the shared app package resolves:

    PYTHONPATH=../chatgpt-plugin uvicorn server:app --app-dir ../chatgpt-plugin --port 8091
"""
import base64
import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, RemoteAuthProvider
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_access_token
from mcp.types import Icon
from pydantic import AnyHttpUrl

from app.config import settings
from app.db import close_pool, get_pool, init_pool
from app.mcp_http import ZyndTokenVerifier, _get_arq, _get_pool, _uid
from plugin_mcp import PLUGIN_SCOPES, is_plugin, plugin_tool_visible, register

_INSTRUCTIONS = (
    "Read private facts only when the user requests recall, never automatically. "
    "Propose a single durable fact only after the user asks or agrees; a proposal "
    "does not save memory. The owner saves it on the signed-in ZYND review page. "
    "Card drafts stay private until the owner separately confirms the exact public "
    "wording on ZYND. Never send secrets or claim pending proposals are saved or public."
)


class PluginOnly(Middleware):
    async def on_discover(self, context: MiddlewareContext, call_next: CallNext):
        return await self.on_initialize(context, call_next)

    async def on_initialize(self, context: MiddlewareContext, call_next: CallNext):
        result = await call_next(context)
        token = get_access_token()
        if result is not None and is_plugin(token):
            if isinstance(result, dict):
                result["instructions"] = _INSTRUCTIONS
            else:
                result.instructions = _INSTRUCTIONS
        return result

    async def on_list_tools(self, context: MiddlewareContext, call_next: CallNext):
        tools = await call_next(context)
        token = get_access_token()
        if not is_plugin(token):
            return []
        scopes = list(token.scopes or [])
        return [tool for tool in tools if plugin_tool_visible(tool.name, scopes)]

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext):
        token = get_access_token()
        name = getattr(context.message, "name", "") or ""
        scopes = list(token.scopes or []) if token else []
        if not is_plugin(token) or not plugin_tool_visible(name, scopes):
            raise PermissionError("This ZYND plugin cannot call that tool.")
        return await call_next(context)


class ExactIssuerAuth(RemoteAuthProvider):
    """Advertise the authorization server exactly as its own metadata spells `issuer`.

    AnyHttpUrl appends "/" to a bare origin, and OpenAI compares the issuer in the resource
    metadata with the authorization server's `issuer` as exact strings, so the stock
    metadata (https://host/ against https://host) would not match."""

    def __init__(self, issuer: str, **kwargs):
        super().__init__(authorization_servers=[AnyHttpUrl(issuer)], **kwargs)
        self.issuer = issuer

    def get_routes(self, mcp_path: str | None = None):
        routes = super().get_routes(mcp_path)
        for route in routes:
            route.app = _with_issuer(route.app, self.issuer)
        return routes


def _with_issuer(app, issuer: str):
    """Wrap the metadata ASGI app so a GET response names `issuer` verbatim in authorization_servers.

    The body is a few hundred bytes of JSON; everything else (status, headers, CORS preflights) passes through."""
    async def wrapped(scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "GET":
            return await app(scope, receive, send)
        start, body = None, b""

        async def capture(message):
            nonlocal start, body
            if message["type"] == "http.response.start":
                start = message
            else:
                body += message.get("body", b"")

        await app(scope, receive, capture)
        document = json.loads(body)
        document["authorization_servers"] = [issuer]
        body = json.dumps(document, separators=(",", ":")).encode()
        headers = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"]
        headers.append((b"content-length", str(len(body)).encode()))
        await send({**start, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    return wrapped


mcp = None


def build():
    auth = ExactIssuerAuth(
        issuer=settings.public_base_url.rstrip("/"),  # same expression as the issuer in /.well-known/oauth-authorization-server
        token_verifier=ZyndTokenVerifier(required_scopes=[]),
        base_url=AnyHttpUrl(settings.plugin_mcp_origin),
        scopes_supported=list(PLUGIN_SCOPES),
        resource_name="ZYND ChatGPT plugin",
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
    mcp.add_middleware(PluginOnly())
    hosts = [h for h in (urlsplit(settings.plugin_mcp_public_base_url).hostname, "localhost", "127.0.0.1") if h]
    return mcp.http_app(path="/chatgpt/mcp", stateless_http=True, allowed_hosts=hosts)


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
