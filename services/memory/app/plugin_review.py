"""Supabase-session-only review of temporary plugin proposals."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from app.config import settings
from app.db import get_pool
from app.services import plugin_consent
from app.supabase_auth import supabase_identity

router = APIRouter(prefix="/me/plugin/proposals", tags=["plugin-review"])


class PreviewBody(BaseModel):
    public_text: str | None = None


class DecisionBody(BaseModel):
    nonce: str
    decision: str


async def _owner(authorization: str) -> str:
    if not getattr(settings, "feature_plugin_consent", False):
        raise HTTPException(503, "plugin review unavailable")
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise HTTPException(401, "Supabase session required")
    identity = await supabase_identity(value.strip())
    if not identity or not identity[2]:
        raise HTTPException(401, "Supabase session required")
    email, _, sub = identity
    row = await get_pool().fetchrow(
        "SELECT id FROM users WHERE supabase_user_id = $1 AND lower(email) = $2",
        sub, email)
    if not row:
        raise HTTPException(403, "linked account not found")
    return str(row["id"])


async def _run(awaitable):
    try:
        return await awaitable
    except plugin_consent.ConsentError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


def _redis(request: Request):
    redis = getattr(request.app.state, "arq", None)
    if redis is None:
        raise HTTPException(503, "plugin review unavailable")
    return redis


@router.get("/{proposal_id}")
async def get_proposal(proposal_id: str, request: Request, authorization: str = Header(default="")):
    uid = await _owner(authorization)
    return await _run(plugin_consent.get_review(get_pool(), _redis(request), uid, proposal_id))


@router.post("/{proposal_id}/preview")
async def preview_proposal(proposal_id: str, request: Request, body: PreviewBody,
                           authorization: str = Header(default="")):
    uid = await _owner(authorization)
    return await _run(plugin_consent.preview(get_pool(), _redis(request), uid,
                                              proposal_id, body.public_text))


@router.post("/{proposal_id}/decision")
async def decide_proposal(proposal_id: str, request: Request, body: DecisionBody,
                          authorization: str = Header(default="")):
    uid = await _owner(authorization)
    return await _run(plugin_consent.decide(get_pool(), _redis(request), uid,
                                             proposal_id, body.nonce, body.decision))
