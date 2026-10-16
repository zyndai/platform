import asyncio
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

import config
from api.mcp import _principal
from services import events, visitor_privacy as privacy

router = APIRouter()


def require_visitors():
    if config.SUPABASE_DB_SCHEMA != 'cards':
        raise HTTPException(404, 'Visitor privacy unavailable')


class PrivacyPreference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    anonymous_mode: bool


class Visit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    visit_id: UUID


@router.get('/mine/visitor-privacy')
async def get_privacy(authorization: str | None = Header(default=None)):
    require_visitors()
    uid = privacy.user_id(_principal(authorization))
    return await asyncio.to_thread(privacy.preference, uid)


@router.patch('/mine/visitor-privacy')
async def set_privacy(body: PrivacyPreference, authorization: str | None = Header(default=None)):
    require_visitors()
    principal = _principal(authorization)
    uid = privacy.user_id(principal)
    name = '' if body.anonymous_mode else await asyncio.to_thread(privacy.display_name, principal)
    return await asyncio.to_thread(privacy.rpc, 's10_set_visitor_privacy', {
        'p_user': uid, 'p_anonymous': body.anonymous_mode,
        'p_name': name,
    })


@router.post('/by-handle/{handle}/visit')
async def record_visit(handle: str, body: Visit, request: Request, authorization: str | None = Header(default=None)):
    require_visitors()
    if not authorization or not events.events_enabled():
        return Response(status_code=204)
    principal = _principal(authorization)
    uid = privacy.user_id(principal)
    key = 'named-visit:' + uid
    if events.rate_limited(key):
        raise HTTPException(429, 'Too many visit requests')
    name = await asyncio.to_thread(privacy.display_name, principal)
    # Human counts are recorded separately by the browser's public view event.
    recorded = await asyncio.to_thread(privacy.rpc, 's10_record_named_visit', {
        'p_id': str(body.visit_id), 'p_user': uid, 'p_email': principal.email,
        'p_handle': handle, 'p_name': name,
    })
    return {'recorded': bool(recorded)}
