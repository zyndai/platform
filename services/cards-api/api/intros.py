import asyncio
from typing import Literal
from uuid import UUID
from datetime import datetime
import jwt
from fastapi import APIRouter, Header, HTTPException, Response, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from api.auth import verify_supabase_jwt
from services import intros
import config

router = APIRouter()


def human(authorization: str | None):
    intros.enabled()
    principal = verify_supabase_jwt(authorization)
    if not principal:
        raise HTTPException(401, "Sign in to request an introduction")
    expected = config.SUPABASE_URL.rstrip("/") + "/auth/v1"
    if (
        not config.AAFO_ISSUER
        or config.AAFO_ISSUER != expected
        or principal.iss != expected
    ):
        raise HTTPException(403, "Use your shared Zynd account for introductions")
    claims = jwt.decode(authorization[7:], options={"verify_signature": False})
    if claims.get("role") != "authenticated" or claims.get("aud") != "authenticated":
        raise HTTPException(403, "Introductions require a human sign-in session")
    try:
        UUID(principal.sub)
    except ValueError as exc:
        raise HTTPException(403, "Invalid account identity") from exc
    return principal


class Create(BaseModel):
    model_config = ConfigDict(extra="forbid")
    why: str = Field(min_length=10, max_length=2000)
    asks: list[Literal["message", "meeting"]] = Field(min_length=1, max_length=2)
    idempotency_key: UUID

    @field_validator("why")
    @classmethod
    def reason(cls, value):
        if len(value.strip()) < 10:
            raise ValueError("Explain why you want to connect")
        return value.strip()

    @field_validator("asks")
    @classmethod
    def unique(cls, value):
        return sorted(set(value))


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept", "decline", "block", "propose_time"]
    allow_meetings: bool = False
    start_time: datetime | None = None
    end_time: datetime | None = None


@router.get("/by-handle/{handle}/intro-eligibility")
async def eligible(handle: str, response: Response):
    response.headers["Cache-Control"] = "no-store"
    intros.enabled()
    try:
        return await intros.eligibility(handle)
    except HTTPException as exc:
        if exc.status_code in (404, 409, 503):
            return {"available": False}
        raise


@router.post("/by-handle/{handle}/intro")
async def create(
    handle: str, body: Create, authorization: str | None = Header(default=None)
):
    caller = human(authorization)
    await intros.eligibility(handle)
    row = await asyncio.to_thread(intros.card_row, handle)
    if caller.sub == row["owner_user_id"]:
        raise HTTPException(422, "You cannot request an intro to yourself")
    await intros.memory_identity(caller.sub)
    result = await intros.persona(
        "",
        "POST",
        {
            "card_id": row["id"],
            "handle": row["handle"],
            "owner_uid": row["owner_user_id"],
            "requester_uid": caller.sub,
            **body.model_dump(mode="json"),
        },
    )
    intros.require_scope([result], caller.sub, outgoing=True)
    if (
        result.get("owner_uid") != row["owner_user_id"]
        or result.get("card_id") != row["id"]
    ):
        raise HTTPException(503, "Could not verify intro target")
    await intros.sync([result])
    return intros.public_record(result)


@router.get("/mine/intros")
async def mine(
    outgoing: bool = False,
    offset: int = Query(default=0, ge=0, le=10000),
    authorization: str | None = Header(default=None),
):
    caller = human(authorization)
    query = "?outgoing=true" if outgoing else ""
    if offset:
        query += ("&" if query else "?") + "offset=" + str(offset)
    result = await intros.persona("/users/" + caller.sub + query)
    intros.require_scope(result["intros"], caller.sub, outgoing)
    await intros.sync(result["intros"])
    return {"intros": [intros.public_record(row) for row in result["intros"]]}


@router.post("/mine/intros/{intro_id}/respond")
async def respond(
    intro_id: UUID, body: Decision, authorization: str | None = Header(default=None)
):
    caller = human(authorization)
    result = await intros.persona(
        "/" + str(intro_id) + "/respond",
        "POST",
        {"actor_uid": caller.sub, **body.model_dump(mode="json")},
    )
    intros.require_scope([result], caller.sub)
    await intros.sync([result])
    return intros.public_record(result)
