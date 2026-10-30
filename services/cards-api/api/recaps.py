"""Owner controls reuse the existing Cards principal. Public reads require explicit publication."""
import asyncio
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, Response
from pydantic import BaseModel, Field

from api.mcp import _owner_email, _principal
from services import recaps

router = APIRouter()


def email_for(authorization):
    return _owner_email(_principal(authorization))


class Milestone(BaseModel):
    kind: Literal["shipped", "learned"]
    title: str = Field(min_length=1, max_length=140)
    url: str = Field(default="", max_length=500)
    occurred_on: date


class Generate(BaseModel):
    period: str = Field(max_length=7)
    refresh: bool = False


class Edit(BaseModel):
    selected_ids: list[str] = Field(max_length=101)
    caption: str = Field(max_length=2000)
    publish: bool = False


@router.get("/mine/recaps")
async def list_recaps(authorization: str | None = Header(default=None)):
    return await asyncio.to_thread(recaps.list_owned, email_for(authorization))


@router.post("/mine/milestones")
async def add_milestone(body: Milestone, authorization: str | None = Header(default=None)):
    return await asyncio.to_thread(recaps.add_milestone, email_for(authorization), **body.model_dump())


@router.post("/mine/recaps")
async def generate(body: Generate, authorization: str | None = Header(default=None)):
    return await recaps.generate(email_for(authorization), body.period, body.refresh)


@router.get("/mine/recaps/{recap_id}")
async def get_owned(recap_id: UUID, authorization: str | None = Header(default=None)):
    recap, row = await asyncio.to_thread(recaps.owned, email_for(authorization), str(recap_id))
    return recaps.owner_payload(recap, row)


@router.patch("/mine/recaps/{recap_id}")
async def edit(recap_id: UUID, body: Edit, authorization: str | None = Header(default=None)):
    return await asyncio.to_thread(recaps.update, email_for(authorization), str(recap_id), **body.model_dump())


@router.post("/mine/recaps/{recap_id}/unpublish")
async def unpublish(recap_id: UUID, authorization: str | None = Header(default=None)):
    return await asyncio.to_thread(recaps.unpublish, email_for(authorization), str(recap_id))


@router.get("/by-handle/{handle}/recaps/{recap_id}")
async def public(handle: str, recap_id: UUID, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await asyncio.to_thread(recaps.public, str(recap_id), handle)
