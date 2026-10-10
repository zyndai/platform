"""Fact-review routes for the cards MCP connector.

The cards MCP server — and its paste-credential "Connect MCP" flow — has been
removed. What remains is fact review, a service-to-service path where cards-api
vouches for the caller's Supabase session and proxies the decision to the memory
layer with MEMORY_SERVICE_TOKEN:

1. GET  /cards/mcp/suggestions — facts reported by their coding agents that
   are still private, awaiting review.
2. POST /cards/mcp/approve, /cards/mcp/revoke — review decisions, proxied to
   the memory layer.
"""
import asyncio
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
