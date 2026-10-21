"""Fact-review routes for the cards MCP connector.

The cards MCP server — and its paste-credential "Connect MCP" flow — has been
removed. What remains is fact review, a service-to-service path where cards-api
vouches for the caller's Supabase session and proxies the decision to the memory
layer with MEMORY_SERVICE_TOKEN:

1. GET  /cards/mcp/suggestions — facts reported by their coding agents that
   are still private, awaiting review (may include group/public_label).
2. POST /cards/mcp/approve, /cards/mcp/dismiss, /cards/mcp/revoke, /cards/mcp/forget
   — review decisions (approve publishes, dismiss permanently hides from inbox,
   revoke unpublishes, forget deletes the fact from memory).
"""
import asyncio
import logging

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

import config
from api.auth import verify_supabase_jwt
from services import events as events_service
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
    as_predicate: str | None = None


@router.get("/mcp/suggestions")
async def mcp_suggestions(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    """Facts reported by the caller's coding agents, awaiting review."""
    principal = _principal(authorization)
    email = _owner_email(principal)
    if not config.MEMORY_SERVICE_TOKEN:
        raise HTTPException(status_code=503, detail="MCP connector not configured")
    try:
        suggestions = await zynd_mcp.suggested_facts(email)
    except zynd_mcp.MemoryUnavailable as exc:
        detail = str(exc)
        if "no ZYND account" in detail:
            return {"suggestions": []}
        raise HTTPException(status_code=502, detail=detail) from exc
    if suggestions:
        events_service.emit(
            "fact_reported",
            request=request,
            meta={"count": len(suggestions)},
        )
    return {"suggestions": suggestions}


@router.get("/mcp/card-facts")
async def mcp_card_facts(
    authorization: str | None = Header(default=None),
) -> dict:
    """The caller's own public card facts, each with where it came from and the
    sentence behind it. Owner-only: the evidence is the person's own words."""
    principal = _principal(authorization)
    email = _owner_email(principal)
    if not config.MEMORY_SERVICE_TOKEN:
        raise HTTPException(status_code=503, detail="MCP connector not configured")
    try:
        facts = await zynd_mcp.owner_card_facts(email)
    except zynd_mcp.MemoryUnavailable as exc:
        detail = str(exc)
        if "no ZYND account" in detail:
            return {"facts": []}
        raise HTTPException(status_code=502, detail=detail) from exc
    return {"facts": facts}


@router.post("/mcp/approve")
async def mcp_approve(
    body: ApproveBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    """Publish one reported fact onto the caller's public card."""
    principal = _principal(authorization)
    email = _owner_email(principal)
    if not config.MEMORY_SERVICE_TOKEN:
        raise HTTPException(status_code=503, detail="MCP connector not configured")
    try:
        result = await zynd_mcp.approve_fact(
            email, body.predicate, body.value, as_predicate=body.as_predicate,
        )
    except zynd_mcp.MemoryUnavailable as exc:
        raise HTTPException(status_code=422 if exc.status_code == 422 else 404 if "no matching" in str(exc) else 502,
                            detail=str(exc)) from exc
    from services.zynd_memory import refresh_owner_snapshot

    result["zynd_memory"] = await asyncio.to_thread(refresh_owner_snapshot, email)
    events_service.emit("fact_approved", request=request)
    return result


@router.post("/mcp/dismiss")
async def mcp_dismiss(
    body: ApproveBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    """Permanently hide one suggestion from the inbox (keeps private memory)."""
    principal = _principal(authorization)
    email = _owner_email(principal)
    if not config.MEMORY_SERVICE_TOKEN:
        raise HTTPException(status_code=503, detail="MCP connector not configured")
    try:
        result = await zynd_mcp.dismiss_fact(email, body.predicate, body.value)
    except zynd_mcp.MemoryUnavailable as exc:
        raise HTTPException(status_code=404 if "no matching" in str(exc) else 502,
                            detail=str(exc)) from exc
    from services.zynd_memory import refresh_owner_snapshot

    result["zynd_memory"] = await asyncio.to_thread(refresh_owner_snapshot, email)
    events_service.emit("fact_dismissed", request=request)
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


@router.post("/mcp/forget")
async def mcp_forget(
    body: ApproveBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    """Delete one reported fact from the owner's memory (hard reject)."""
    principal = _principal(authorization)
    email = _owner_email(principal)
    if not config.MEMORY_SERVICE_TOKEN:
        raise HTTPException(status_code=503, detail="MCP connector not configured")
    try:
        result = await zynd_mcp.forget_fact(email, body.predicate, body.value)
    except zynd_mcp.MemoryUnavailable as exc:
        raise HTTPException(status_code=404 if "no matching" in str(exc) else 502,
                            detail=str(exc)) from exc
    from services.zynd_memory import refresh_owner_snapshot

    result["zynd_memory"] = await asyncio.to_thread(refresh_owner_snapshot, email)
    events_service.emit("fact_dismissed", request=request)
    return result
