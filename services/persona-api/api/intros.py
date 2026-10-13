"""Human decisions and a dedicated Cards service bridge."""

import asyncio
import hmac
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from api.auth import get_current_user
from api.guards import _guard
from services import intros
import config

router = APIRouter()


def enabled():
    if not config.FEATURE_S12_INTROS:
        raise HTTPException(404, "Intros are not enabled")


@_guard
def cards_service(authorization: str = Header(default="")):
    enabled()
    expected = config.CARDS_INTRO_SERVICE_TOKEN
    token = authorization.removeprefix("Bearer ").strip()
    if not expected or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(401, "Invalid intro service credential")


class Create(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_id: str = Field(min_length=1, max_length=128)
    handle: str = Field(min_length=1, max_length=128)
    requester_uid: UUID
    owner_uid: UUID
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
    def unique_asks(cls, value):
        return sorted(set(value))


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept", "decline", "block", "propose_time"]
    allow_meetings: bool = False
    start_time: datetime | None = None
    end_time: datetime | None = None

    @model_validator(mode="after")
    def times(self):
        if bool(self.start_time) != bool(self.end_time):
            raise ValueError("Supply both meeting times")
        if self.start_time:
            if not self.start_time.tzinfo or not self.end_time.tzinfo:
                raise ValueError("Meeting times require a timezone")
            seconds = (self.end_time - self.start_time).total_seconds()
            if self.start_time <= datetime.now(timezone.utc) or not 0 < seconds <= 7200:
                raise ValueError("Choose a future meeting of at most two hours")
        if self.action == "propose_time" and not self.start_time:
            raise ValueError("Choose a time to propose")
        if self.action in ("decline", "block") and (
            self.start_time or self.allow_meetings
        ):
            raise ValueError("Declining cannot grant permissions or propose a meeting")
        return self


class ServiceResponse(Response):
    actor_uid: UUID


@router.get("/internal/agents/{uid}", dependencies=[Depends(cards_service)])
async def agent(uid: UUID):
    def read():
        rows = (
            config.get_supabase()
            .table("persona_agents")
            .select("agent_id,name")
            .eq("user_id", str(uid))
            .eq("active", True)
            .limit(2)
            .execute()
            .data
            or []
        )
        return {
            "active": len(rows) == 1,
            "agent_id": rows[0]["agent_id"] if len(rows) == 1 else None,
            "issuer": config.SUPABASE_URL.rstrip("/") + "/auth/v1",
        }

    return await asyncio.to_thread(read)


@router.post("/internal", dependencies=[Depends(cards_service)])
async def create(body: Create):
    return await asyncio.to_thread(
        intros.operation,
        "s12_create_intro",
        {
            "p_card_id": body.card_id,
            "p_handle": body.handle,
            "p_requester_uid": str(body.requester_uid),
            "p_owner_uid": str(body.owner_uid),
            "p_why": body.why,
            "p_asks": body.asks,
            "p_key": str(body.idempotency_key),
            "p_requester_cap": config.S12_REQUESTER_DAILY_CAP,
            "p_card_cap": config.S12_CARD_DAILY_CAP,
        },
    )


@router.get("/internal/users/{uid}", dependencies=[Depends(cards_service)])
async def service_list(
    uid: UUID, outgoing: bool = False, offset: int = Query(default=0, ge=0, le=10000)
):
    return {
        "intros": await asyncio.to_thread(intros.list_for, str(uid), outgoing, offset),
        "pending_count": await asyncio.to_thread(intros.pending_count, str(uid)),
    }


@router.post("/internal/{intro_id}/respond", dependencies=[Depends(cards_service)])
async def service_respond(intro_id: UUID, body: ServiceResponse):
    return await asyncio.to_thread(
        intros.respond, str(intro_id), str(body.actor_uid), body
    )


@router.get("")
async def mine(
    outgoing: bool = False,
    offset: int = Query(default=0, ge=0, le=10000),
    user: dict = Depends(get_current_user),
):
    enabled()
    return {
        "intros": await asyncio.to_thread(intros.list_for, user["id"], outgoing, offset)
    }


@router.post("/{intro_id}/respond")
async def respond(
    intro_id: UUID, body: Response, user: dict = Depends(get_current_user)
):
    enabled()
    return await asyncio.to_thread(intros.respond, str(intro_id), user["id"], body)


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requester_uid: UUID
    rule: Literal["allow", "deny"]


@router.get("/rules/mine")
async def rules(user: dict = Depends(get_current_user)):
    enabled()
    return {
        "rules": await asyncio.to_thread(
            lambda: (
                config.get_supabase()
                .table("persona_intro_rules")
                .select("requester_uid,rule")
                .eq("owner_uid", user["id"])
                .execute()
                .data
                or []
            )
        )
    }


@router.put("/rules/mine")
async def rule(body: Rule, user: dict = Depends(get_current_user)):
    enabled()
    return await asyncio.to_thread(
        intros.operation,
        "s12_set_intro_rule",
        {
            "p_owner": user["id"],
            "p_requester": str(body.requester_uid),
            "p_rule": body.rule,
        },
    )


@router.delete("/rules/mine/{uid}")
async def remove_rule(uid: UUID, user: dict = Depends(get_current_user)):
    enabled()
    return await asyncio.to_thread(
        intros.operation,
        "s12_set_intro_rule",
        {"p_owner": user["id"], "p_requester": str(uid), "p_rule": None},
    )
