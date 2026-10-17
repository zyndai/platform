import asyncio
import hmac
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

import config
from services.digest import clear_suggested_posts, run_digest
from services import intros

router = APIRouter()


class OwnerStatusRequest(BaseModel):
    email: str


class OwnerIntrosRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zynd_uid: UUID
    issuer: str


class McpIntroRequest(BaseModel):
    """Identity-bound request from the authenticated ZYND MCP service."""

    model_config = ConfigDict(extra="forbid")
    handle: str = Field(min_length=1, max_length=128)
    requester_uid: UUID
    why: str = Field(min_length=10, max_length=2000)
    asks: list[Literal["message", "meeting"]] = Field(min_length=1, max_length=2)
    idempotency_key: UUID

    @field_validator("why")
    @classmethod
    def reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Explain why you want to connect")
        return value

    @field_validator("asks")
    @classmethod
    def unique_asks(cls, value: list[str]) -> list[str]:
        return sorted(set(value))


class McpIntroList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zynd_uid: UUID
    issuer: str
    outgoing: bool = False


def _require_memory_mcp(authorization: str | None) -> None:
    if not config.FEATURE_S12_MCP_ACTIONS:
        raise HTTPException(404, "MCP introductions are not enabled")
    secret = config.MEMORY_SERVICE_TOKEN
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not secret or not hmac.compare_digest(supplied.encode(), secret.encode()):
        raise HTTPException(401, "Unauthorized")


@router.post("/owner-intros")
async def service_owner_intros(body: OwnerIntrosRequest, authorization: str | None = Header(default=None)):
    secret = config.MEMORY_SERVICE_TOKEN
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not secret or not hmac.compare_digest(supplied.encode(), secret.encode()):
        raise HTTPException(401,"Unauthorized")
    from services import intros
    intros.enabled()
    if body.issuer != config.AAFO_ISSUER:
        raise HTTPException(403,"Shared identity issuer does not match")
    await intros.memory_identity(str(body.zynd_uid))
    result = await intros.persona("/users/" + str(body.zynd_uid))
    intros.require_scope(result["intros"],str(body.zynd_uid))
    await intros.sync(result["intros"])
    return {"intros": [intros.public_record(row) for row in result["intros"]]}


@router.post("/mcp-intro")
async def service_mcp_intro(
    body: McpIntroRequest,
    authorization: str | None = Header(default=None),
):
    """Submit a verified-card intro on behalf of one authenticated MCP user.

    The memory service supplies the canonical shared-account UUID after it has
    authenticated the MCP token. Cards still performs the card eligibility,
    active-Persona, and Memory identity checks before asking Persona to create
    the atomic request.
    """
    _require_memory_mcp(authorization)
    intros.enabled()
    await intros.eligibility(body.handle)
    row = await asyncio.to_thread(intros.card_row, body.handle)
    if str(body.requester_uid) == row["owner_user_id"]:
        raise HTTPException(422, "You cannot request an intro to yourself")
    await intros.memory_identity(str(body.requester_uid))
    result = await intros.persona(
        "",
        "POST",
        {
            "card_id": row["id"],
            "handle": row["handle"],
            "owner_uid": row["owner_user_id"],
            "requester_uid": str(body.requester_uid),
            "why": body.why,
            "asks": body.asks,
            "idempotency_key": str(body.idempotency_key),
        },
    )
    intros.require_scope([result], str(body.requester_uid), outgoing=True)
    if result.get("owner_uid") != row["owner_user_id"] or result.get("card_id") != row["id"]:
        raise HTTPException(503, "Could not verify intro target")
    await intros.sync([result])
    return intros.public_record(result)


@router.post("/mcp-intros")
async def service_mcp_intros(
    body: McpIntroList,
    authorization: str | None = Header(default=None),
):
    """Read MCP user's sent or received verified-card intro requests."""
    _require_memory_mcp(authorization)
    intros.enabled()
    if body.issuer != config.AAFO_ISSUER:
        raise HTTPException(403, "Shared identity issuer does not match")
    await intros.memory_identity(str(body.zynd_uid))
    query = "?outgoing=true" if body.outgoing else ""
    result = await intros.persona("/users/" + str(body.zynd_uid) + query)
    intros.require_scope(result["intros"], str(body.zynd_uid), body.outgoing)
    await intros.sync(result["intros"])
    return {"intros": [intros.public_record(row) for row in result["intros"]]}


@router.post("/owner-status")
async def service_owner_status(body: OwnerStatusRequest, authorization: str | None = Header(default=None)):
    # Only memory can vouch for the owner behind an authenticated MCP call.
    secret = config.MEMORY_SERVICE_TOKEN
    supplied = (authorization or "").removeprefix("Bearer ")
    if not secret or not hmac.compare_digest(supplied, secret):
        raise HTTPException(401, "Unauthorized")
    from services import owner_home
    if not owner_home.enabled():
        raise HTTPException(404, "Owner home is not enabled")
    if not body.email.strip():
        raise HTTPException(422, "Email is required")
    return await owner_home.status(body.email.strip().lower(), persist=False)


@router.post("/refresh-card-memory")
async def refresh_card_memory(body: OwnerStatusRequest, authorization: str | None = Header(default=None)):
    # Only memory can vouch for a memory-side mutation (MCP forget/revoke/approve
    # via the agent path) that needs the card snapshot refreshed. See
    # services/memory/app/services/card_sync.py for the caller.
    secret = config.MEMORY_SERVICE_TOKEN
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not secret or not hmac.compare_digest(supplied.encode(), secret.encode()):
        raise HTTPException(401, "Unauthorized")
    email = body.email.strip().lower()
    if not email:
        raise HTTPException(422, "Email is required")
    from services.zynd_memory import refresh_owner_snapshot

    snapshot = await asyncio.to_thread(refresh_owner_snapshot, email)
    return {"zynd_memory": snapshot}


@router.post("/owner-notifications")
async def owner_notifications(authorization: str | None = Header(default=None), dry_run: bool = Query(default=False)):
    _require_cron(authorization)
    from services.owner_notifications import run_notifications
    return await run_notifications(dry_run=dry_run)


@router.post("/owner-notifications/test")
async def test_owner_notification(
    authorization: str | None = Header(default=None),
    kind: Literal["weekly", "reminder"] = Query(default="weekly"),
    email: str | None = Query(default=None),
):
    """Explicit repeatable send to one owner, or all owners when email is omitted."""
    _require_cron(authorization)
    from services.owner_notifications import send_test_notification, send_all_test_notifications
    if email is not None:
        return await send_test_notification(email=email, kind=kind)
    return await send_all_test_notifications(kind=kind)


def _require_cron(authorization: str | None) -> None:
    secret = (config.CRON_SECRET or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET not set")
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/morning-digest")
def morning_digest(
    authorization: str | None = Header(default=None),
    dry_run: bool = Query(default=False),
    handle: str | None = Query(default=None),
):
    _require_cron(authorization)
    return run_digest(dry_run=dry_run, handle=handle)


@router.post("/clear-suggested-posts")
def clear_suggested_posts_route(
    authorization: str | None = Header(default=None),
    handle: str | None = Query(default=None),
):
    _require_cron(authorization)
    return clear_suggested_posts(handle=handle)


@router.post("/purge-card-events")
def purge_card_events(authorization: str | None = Header(default=None)):
    """S04: drop card_events older than 180 days. Flag off → 204."""
    _require_cron(authorization)
    from services import events as events_service

    if not events_service.events_enabled():
        return Response(status_code=204)
    deleted = events_service.purge_older_than_days(180)
    return {"deleted": deleted}
