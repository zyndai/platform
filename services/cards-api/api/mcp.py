"""MCP connector routes — dashboard-side of the coding-agent connection.

1. POST /cards/mcp/connect — the signed-in user generates their cards MCP
   token + paste-ready config (verified via Supabase JWT, minted by the
   memory layer after cards vouches for them).
2. GET  /cards/mcp/suggestions — facts reported by their coding agents that
   are still private, awaiting review.
3. POST /cards/mcp/approve, /cards/mcp/revoke — review decisions, proxied to
   the memory layer with MEMORY_SERVICE_TOKEN (the user's MCP token never
   enters the browser).
"""
import asyncio
import json
import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

import config
from api.auth import verify_supabase_jwt
from services import zynd_mcp

logger = logging.getLogger(__name__)

router = APIRouter()


def _principal(authorization: str | None):
    principal = verify_supabase_jwt(authorization)
    if not principal:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return principal


def _owner_email(principal) -> str:
    email = (principal.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=422, detail="account has no verified email")
    return email


class ApproveBody(BaseModel):
    predicate: str
    value: str


@router.post("/mcp/connect")
async def mcp_connect(authorization: str | None = Header(default=None)) -> dict:
    """Generate (or regenerate) the caller's cards MCP connection.

    Returns the paste-ready client config. The token is long-lived; generating
    a new one does not invalidate old ones — use /mcp/disconnect to revoke all."""
    principal = _principal(authorization)
    email = _owner_email(principal)

    if not config.MEMORY_SERVICE_TOKEN:
        raise HTTPException(status_code=503, detail="MCP connector not configured")

    result = await asyncio.to_thread(
        zynd_mcp.connect_mcp_sync,
        email, "", principal.sub if principal.iss == config.AAFO_ISSUER else "",
    )
    if not result:
        raise HTTPException(status_code=502, detail="memory layer unavailable — try again shortly")

    token, mcp_url = result["token"], result["mcp_url"]
    server_block = {
        "url": mcp_url,
        "headers": {"Authorization": f"Bearer {token}"},
    }
    return {
        "token": token,
        "mcp_url": mcp_url,
        # Ready-to-paste configs for the common coding-agent clients.
        "config_json": json.dumps({"mcpServers": {"zynd-cards": server_block}}, indent=2),
        "config_http": {
            "mcpServers": {
                "zynd-cards": server_block,
            }
        },
        "instructions": [
            "Claude Code: claude mcp add --transport http zynd-cards " + mcp_url
            + " --header 'Authorization: Bearer <token>'",
            "Cursor: Settings → MCP → Add HTTP server, paste the URL and header",
            "VS Code / Windsurf / Cline: add the JSON block to your mcp.json",
        ],
    }


@router.post("/mcp/disconnect")
async def mcp_disconnect(authorization: str | None = Header(default=None)) -> dict:
    """Revoke every ZYND token for the caller (signs the MCP connection out)."""
    principal = _principal(authorization)
    email = _owner_email(principal)
    if not config.MEMORY_SERVICE_TOKEN:
        raise HTTPException(status_code=503, detail="MCP connector not configured")
    try:
        result = await zynd_mcp._request("POST", "/v1/service/disconnect", {"email": email})
    except zynd_mcp.MemoryUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result


@router.get("/mcp/suggestions")
async def mcp_suggestions(authorization: str | None = Header(default=None)) -> dict:
    """Facts reported by the caller's coding agents, awaiting review."""
    principal = _principal(authorization)
    email = _owner_email(principal)
    if not config.MEMORY_SERVICE_TOKEN:
        raise HTTPException(status_code=503, detail="MCP connector not configured")
    try:
        return {"suggestions": await zynd_mcp.suggested_facts(email)}
    except zynd_mcp.MemoryUnavailable as exc:
        detail = str(exc)
        if "no ZYND account" in detail:
            return {"suggestions": []}
        raise HTTPException(status_code=502, detail=detail) from exc


@router.post("/mcp/approve")
async def mcp_approve(body: ApproveBody, authorization: str | None = Header(default=None)) -> dict:
    """Publish one reported fact onto the caller's public card."""
    principal = _principal(authorization)
    email = _owner_email(principal)
    if not config.MEMORY_SERVICE_TOKEN:
        raise HTTPException(status_code=503, detail="MCP connector not configured")
    try:
        result = await zynd_mcp.approve_fact(email, body.predicate, body.value)
    except zynd_mcp.MemoryUnavailable as exc:
        raise HTTPException(status_code=404 if "no matching" in str(exc) else 502,
                            detail=str(exc)) from exc
    from services.zynd_memory import refresh_owner_snapshot
    result["zynd_memory"] = await asyncio.to_thread(refresh_owner_snapshot, email)
    return result


@router.post("/mcp/revoke")
async def mcp_revoke(body: ApproveBody, authorization: str | None = Header(default=None)) -> dict:
    """Take one fact off the caller's public card (kept in private memory)."""
    principal = _principal(authorization)
    email = _owner_email(principal)
    if not config.MEMORY_SERVICE_TOKEN:
        raise HTTPException(status_code=503, detail="MCP connector not configured")
    try:
        result = await zynd_mcp.revoke_fact(email, body.predicate, body.value)
    except zynd_mcp.MemoryUnavailable as exc:
        raise HTTPException(status_code=404 if "no matching" in str(exc) else 502,
                            detail=str(exc)) from exc
    from services.zynd_memory import refresh_owner_snapshot
    result["zynd_memory"] = await asyncio.to_thread(refresh_owner_snapshot, email)
    return result
