"""POST /events — batched, rate-limited, unauthenticated allow-list."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from services import events as events_service

router = APIRouter()


class EventItem(BaseModel):
    event: str
    handle: str | None = None
    ref: str | None = None
    meta: dict[str, Any] | None = None


class EventsBody(BaseModel):
    events: list[EventItem] = Field(default_factory=list)


@router.post("/events")
async def post_events(body: EventsBody, request: Request):
    if not events_service.events_enabled():
        return Response(status_code=204)

    if not body.events:
        return Response(status_code=204)
    if len(body.events) > events_service._MAX_BATCH:
        raise HTTPException(status_code=400, detail=f"batch max {events_service._MAX_BATCH}")

    for item in body.events:
        if item.event not in events_service.ALLOWED_EVENTS:
            raise HTTPException(status_code=400, detail=f"unknown event: {item.event}")

    ip = events_service.client_ip(request)
    rate_key = events_service.session_hash_for_ip(ip) or ip or "anon"
    if events_service.rate_limited(rate_key):
        raise HTTPException(status_code=429, detail="rate limited")

    ua = request.headers.get("user-agent")
    payload = [item.model_dump() for item in body.events]
    events_service.insert_batch(payload, user_agent=ua, ip=ip)
    return Response(status_code=204)
