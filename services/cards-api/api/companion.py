"""Zynd Companion routes: pair a browser, then let it set Working on and Currently exploring.

Two kinds of caller, never mixed:
- the website, with the person's Supabase session, pairs/lists/revokes devices;
- the extension, with the device token that pairing returned, reads and writes the two
  card fields. A device token is refused by every other route in this service.
See docs/plans/ZYND_COMPANION_PLAN.md.
"""
import asyncio
import logging

from fastapi import APIRouter, Header, HTTPException, Response
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field

from api.mcp import _owner_email, _principal
from services import companion, owner_home

logger = logging.getLogger(__name__)

router = APIRouter()


async def _run(fn, *args):
    try:
        return await asyncio.to_thread(fn, *args)
    except companion.CompanionError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except APIError as exc:
        # Includes the table or function not existing yet (migration 0032 not applied).
        logger.warning("companion database error code=%s message=%s", exc.code, exc.message)
        raise HTTPException(503, "Zynd Companion is not available yet") from exc


async def _device(authorization: str | None) -> dict:
    token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else None
    device = await _run(companion.device_for_token, token)
    if not device:
        raise HTTPException(401, "Unauthorized")
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
    mine = await _run(companion.profile, email)         # no card, nothing to connect
    token, device = await _run(companion.create_device, email, body.label)
    return {"token": token, "device": _public(device), "profile": mine}


@router.get("/devices")
async def devices(authorization: str | None = Header(default=None)):
    email = _owner_email(_principal(authorization))
    return {"devices": await _run(companion.list_devices, email)}


@router.delete("/devices/{device_id}")
async def revoke(device_id: str, authorization: str | None = Header(default=None)):
    email = _owner_email(_principal(authorization))
    if not await _run(companion.revoke_device, email, device_id):
        raise HTTPException(404, "Device not found")
    return Response(status_code=204)


def _public(device: dict) -> dict:
    return {k: device.get(k) for k in companion.PUBLIC_DEVICE_FIELDS}


# ── Device token: what the extension does ────────────────────────────────────

@router.get("/me")
async def me(authorization: str | None = Header(default=None)):
    device = await _device(authorization)
    return await _run(companion.profile, device["owner_email"])


@router.post("/working-on")
async def add_working_on(body: WorkingOnBody, authorization: str | None = Header(default=None)):
    device = await _device(authorization)
    saved = await _run(companion.set_working_on, device["owner_email"], body.text)
    asyncio.create_task(asyncio.to_thread(companion.reembed, saved["handle"], saved))
    return companion.lists_of(saved)


@router.post("/working-on/remove")
async def remove_working_on(body: WorkingOnBody, authorization: str | None = Header(default=None)):
    device = await _device(authorization)
    saved = await _run(companion.drop_working_on, device["owner_email"], body.text)
    asyncio.create_task(asyncio.to_thread(companion.reembed, saved["handle"], saved))
    return companion.lists_of(saved)


@router.post("/exploring")
async def add_exploring(body: ExploringBody, authorization: str | None = Header(default=None)):
    device = await _device(authorization)
    saved = await _run(companion.add_exploring, device["owner_email"], body.url, body.title, body.kind, body.note)
    return companion.lists_of(saved)


@router.post("/exploring/remove")
async def remove_exploring(body: UrlBody, authorization: str | None = Header(default=None)):
    device = await _device(authorization)
    saved = await _run(companion.drop_exploring, device["owner_email"], body.url)
    return companion.lists_of(saved)


@router.post("/disconnect")
async def disconnect(authorization: str | None = Header(default=None)):
    device = await _device(authorization)
    await _run(companion.revoke_device, device["owner_email"], device["id"])
    return Response(status_code=204)
