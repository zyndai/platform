"""POST /cards/visibility/check: the public AI visibility report. Unauthenticated; 503 while
OPENROUTER_API_KEY is not set. Mounted under /cards because api.zynd.ai only routes /cards*, /ask*,
/onboard* and /v1* to cards-api (infra/single-box/Caddyfile)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import config
from services import visibility

router = APIRouter()


class VisibilityCheck(BaseModel):
    # Generous ceilings only bound the payload; validate_query enforces the real limits with a
    # message a visitor can read instead of a 422 list.
    name: str = Field("", max_length=1000)
    link: str | None = Field(None, max_length=2000)


@router.post("/check")
async def check_visibility(body: VisibilityCheck, request: Request):
    # Before validation and the rate limit, so an unconfigured server spends nobody's checks.
    if not config.OPENROUTER_API_KEY:
        raise HTTPException(status_code=503, detail=visibility.NOT_CONFIGURED)
    try:
        query = visibility.validate_query(body.name, body.link)
    except visibility.VisibilityInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return await visibility.run_check(query, visibility.client_key(request))
    except visibility.VisibilityUnavailable as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
