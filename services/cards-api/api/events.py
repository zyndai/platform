"""POST /events — batched, rate-limited, unauthenticated allow-list."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from services import agent_ip_ranges
from services import events as events_service

router = APIRouter()

SERVER_EVENT_HEADER = events_service.SERVER_EVENT_HEADER
# The visitor IP cards-web or memory saw. Read only next to a valid SERVER_EVENT_HEADER: from
# anyone else it is a claim the caller makes about itself.
CLIENT_IP_HEADER = "X-Zynd-Client-IP"


class EventItem(BaseModel):
    event: str
    handle: str | None = None
    ref: str | None = None
    meta: dict[str, Any] | None = None


class EventsBody(BaseModel):
    events: list[EventItem] = Field(default_factory=list)


def _attested_visitor_ip(request: Request) -> str | None:
    address = agent_ip_ranges.parse_ip(request.headers.get(CLIENT_IP_HEADER))
    return str(address) if address else None


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
    attested = events_service.from_our_server(request)
    # Our servers report every visitor's reads from one address, so a per-caller limit would
    # throttle cards-web's page renders and memory's MCP reads together. Holding the token is
    # what earns the exemption.
    if not attested:
        rate_key = events_service.session_hash_for_ip(ip) or ip or "anon"
        if events_service.rate_limited(rate_key):
            raise HTTPException(status_code=429, detail="rate limited")

    ua = request.headers.get("user-agent")
    payload = [item.model_dump() for item in body.events]
    saved = await asyncio.to_thread(events_service.insert_batch, payload, user_agent=ua, ip=ip,
                                    server_observed=attested,
                                    visitor_ip=_attested_visitor_ip(request) if attested else None)
    if saved is False:
        raise HTTPException(status_code=503, detail="event storage unavailable")
    return Response(status_code=204)
