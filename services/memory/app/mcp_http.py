"""Hosted, authenticated ZYND MCP server (streamable-HTTP transport).

Remote version of app/mcp_server.py: any MCP client (Claude Desktop, Cursor, …)
connects to https://<host>/mcp with a ZYND bearer token. The token is verified per
request and the tools are scoped to that authenticated user — there is no trusted
user_id parameter, so one user can never read or change another's data.

Run:  uvicorn app.mcp_http:app --host 0.0.0.0 --port 8090
"""
import contextvars

import asyncpg
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.auth import verify_access_token
from app.config import settings
from app.services.control import confirm_fact, forget_fact
from app.services.export import build_jsonld_export, context_slice
from app.services.matching import match_users

# Set by the auth ASGI wrapper per request; read by the tools.
_current_user: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_user", default=None)

# Process-lifetime pool, independent of the MCP session lifespan (which cycles).
_pool: asyncpg.Pool | None = None


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10)
    return _pool


def _uid() -> str:
    uid = _current_user.get()
    if uid is None:
        raise RuntimeError("not authenticated")
    return uid


# DNS-rebinding protection is for browser attacks; our clients aren't browsers and
# every request needs a bearer token, so we run behind Caddy's HTTPS + our own auth.
mcp = FastMCP(
    "zynd", stateless_http=True, json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def get_my_context(topic: str, k: int = 20) -> list[dict]:
    """Top-K facts about the signed-in user most relevant to `topic`. Use to ground
    a reply in their context without loading their whole graph."""
    return await context_slice(await _get_pool(), _uid(), topic, max(1, min(k, 50)))


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def export_my_context() -> dict:
    """Export the signed-in user's full active context as a JSON-LD packet."""
    return await build_jsonld_export(await _get_pool(), _uid())


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def find_similar_users(cluster_type: str = "intent_cluster", k: int = 10) -> list[dict]:
    """Find people whose active context overlaps the signed-in user's. cluster_type:
    intent_cluster, skill_cluster, belief_cluster, concept_cluster, full_context."""
    return await match_users(await _get_pool(), _uid(), cluster_type, k)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def confirm_fact_tool(predicate: str, object: str) -> dict:
    """Confirm one of the user's facts is true -> raises its confidence to the max."""
    return {"confirmed": await confirm_fact(await _get_pool(), _uid(), predicate, object)}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
async def forget_fact_tool(predicate: str, object: str) -> dict:
    """Forget one of the user's facts -> soft-deleted (kept for audit, no longer active)."""
    return {"forgotten": await forget_fact(await _get_pool(), _uid(), predicate, object)}


_mcp_app = mcp.streamable_http_app()  # Starlette app (handles its own session lifespan)


async def app(scope, receive, send):
    """Pure-ASGI auth wrapper. Pure ASGI (not BaseHTTPMiddleware) so the contextvar
    set here propagates into the tool call. Non-http scopes (lifespan) pass through."""
    if scope["type"] != "http":
        await _mcp_app(scope, receive, send)
        return

    headers = dict(scope.get("headers") or [])
    token = headers.get(b"authorization", b"").decode().removeprefix("Bearer ").strip()
    try:
        user_id = verify_access_token(token)
    except ValueError:
        await _send_401(send)
        return
    _current_user.set(user_id)
    await _mcp_app(scope, receive, send)


async def _send_401(send) -> None:
    body = b'{"error":"unauthorized - supply a valid ZYND bearer token"}'
    await send({"type": "http.response.start", "status": 401,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
