"""Zynd Companion routes: pair a browser, then let it set Working on and Currently exploring.

Two kinds of caller, never mixed:
- the website, with the person's Supabase session, pairs/lists/revokes devices and can remove
  a Currently exploring clip;
- the extension, with the device token that pairing returned, reads and writes the two
  card fields. A device token is refused by every other route in this service.
See docs/plans/ZYND_COMPANION_PLAN.md.
"""
import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field

from api.mcp import _owner_email, _principal
from services import companion, owner_home, stale_signals

logger = logging.getLogger(__name__)

router = APIRouter()

# The table or function does not exist yet, i.e. cards migration 0032 is not applied: Postgres'
# undefined_table / undefined_function, and PostgREST's "not in the schema cache" for a table
# (PGRST205) or a function (PGRST202). Any other database error is a real failure, not "not yet".
_NOT_MIGRATED_CODES = {"42P01", "42883", "PGRST202", "PGRST205"}


async def _run(fn, *args):
    try:
        return await asyncio.to_thread(fn, *args)
    except companion.CompanionError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except APIError as exc:
        if str(exc.code) in _NOT_MIGRATED_CODES:
            logger.warning("companion unavailable: cards migration 0032 not applied (%s)", exc.code)
            raise HTTPException(503, "Zynd Companion is not available yet") from exc
        logger.error("companion database error code=%s message=%s", exc.code, exc.message)
        raise


async def _device(authorization: str | None) -> dict:
    token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else None
    device = await _run(companion.device_for_token, token)
    if not device:
        raise HTTPException(401, "Unauthorized")
    return device


async def _writer(authorization: str | None) -> dict:
    device = await _device(authorization)
    if not companion.allow_device_write(device["id"]):
        raise HTTPException(429, "Too many changes from this browser. Wait a minute.")
    return device


class PairBody(BaseModel):
    label: str = Field("", max_length=200)


class WorkingOnBody(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ExploringBody(BaseModel):
    url: str = Field(max_length=2000)
    title: str = Field("", max_length=2000)
    kind: str = Field("link", max_length=40)
    note: str = Field("", max_length=2000)


class UrlBody(BaseModel):
    url: str = Field(max_length=2000)


# ── Website session: pair and manage devices ─────────────────────────────────

@router.post("/pair")
async def pair(body: PairBody, authorization: str | None = Header(default=None)):
    email = _owner_email(_principal(authorization))
    if not companion.allow_pairing(email):
        raise HTTPException(429, "Too many connections in the last hour. Try again later.")
    mine = await _run(companion.profile, email)         # no card, nothing to connect
    token, device = await _run(companion.create_device, email, body.label)
    return {"token": token, "device": _public(device), "profile": mine}


@router.get("/devices")
async def devices(authorization: str | None = Header(default=None)):
    email = _owner_email(_principal(authorization))
    return {"devices": await _run(companion.list_devices, email)}


@router.delete("/devices/{device_id}")
async def revoke(device_id: UUID, authorization: str | None = Header(default=None)):
    email = _owner_email(_principal(authorization))
    if not await _run(companion.revoke_device, email, str(device_id)):
        raise HTTPException(404, "Device not found")
    return Response(status_code=204)


@router.post("/mine/exploring/remove")
async def remove_my_exploring(body: UrlBody, authorization: str | None = Header(default=None)):
    """The website's own remove for a clip. Card editor section saves (s10_save_section) cannot write
    `exploring`, and this needs no migration: it is the same row-locked save the extension uses."""
    email = _owner_email(_principal(authorization))
    if not companion.allow_owner_write(email):
        raise HTTPException(429, "Too many changes at once. Wait a minute.")
    saved = await _run(companion.drop_exploring, email, body.url)
    return companion.lists_of(saved)


def _public(device: dict) -> dict:
    return {k: device.get(k) for k in companion.PUBLIC_DEVICE_FIELDS}


# ── Device token: what the extension does ────────────────────────────────────

@router.get("/me")
async def me(authorization: str | None = Header(default=None)):
    device = await _device(authorization)
    return await _run(companion.profile, device["owner_email"])


@router.post("/working-on")
async def add_working_on(body: WorkingOnBody, authorization: str | None = Header(default=None)):
    device = await _writer(authorization)
    saved = await _run(companion.set_working_on, device["owner_email"], body.text)
    asyncio.create_task(asyncio.to_thread(companion.reembed, saved["handle"], saved))
    return companion.lists_of(saved)


@router.post("/working-on/remove")
async def remove_working_on(body: WorkingOnBody, authorization: str | None = Header(default=None)):
    device = await _writer(authorization)
    saved = await _run(companion.drop_working_on, device["owner_email"], body.text)
    asyncio.create_task(asyncio.to_thread(companion.reembed, saved["handle"], saved))
    return companion.lists_of(saved)


@router.post("/exploring")
async def add_exploring(body: ExploringBody, authorization: str | None = Header(default=None)):
    device = await _writer(authorization)
    saved = await _run(companion.add_exploring, device["owner_email"], body.url, body.title, body.kind, body.note)
    return companion.lists_of(saved)


@router.post("/exploring/remove")
async def remove_exploring(body: UrlBody, authorization: str | None = Header(default=None)):
    device = await _writer(authorization)
    saved = await _run(companion.drop_exploring, device["owner_email"], body.url)
    return companion.lists_of(saved)


@router.post("/working-on/confirm")
async def confirm_working_on(authorization: str | None = Header(default=None)):
    """"Yes, keep it" in the extension: the card page's "Still working on this", by device token."""
    if not stale_signals.enabled():
        raise HTTPException(404, "Stale signals are turned off")
    device = await _writer(authorization)
    return await _run(companion.confirm_working_on, device["owner_email"])


@router.post("/disconnect")
async def disconnect(authorization: str | None = Header(default=None)):
    device = await _device(authorization)
    await _run(companion.revoke_device, device["owner_email"], device["id"])
    return Response(status_code=204)
