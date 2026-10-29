"""The owner's side of asks (services/asks.py): close-out and credits.

Every route derives the owner from the session (api/owner_home.py's email_for) and looks things up
through that owner's own card, so another owner's ask or offer id is a 404, exactly like one that
does not exist. Nothing is taken from the request body beyond the answer itself.
"""
import asyncio
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from api.owner_home import email_for
from services import asks, owner_home

router = APIRouter()

MAX_HELPERS = 20


class Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["helped", "solved_elsewhere", "still_looking"]
    helper_card_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=64)]] = Field(
        default_factory=list, max_length=MAX_HELPERS)


def _owner_card(authorization: str | None) -> tuple[str, dict]:
    email = email_for(authorization)
    row = owner_home.current_row(email)
    if not row:
        raise HTTPException(404, "Create your card first")
    return email, row


@router.get("/mine/asks")
async def my_asks(authorization: str | None = Header(default=None)):
    """{"asks": [{id, text, status: active|ended, created_at, expires_at, ended_at, outcome, offers: [...]}]}:
    the current ask and asks that ended in the last 14 days without an answer, with who offered."""
    _, row = await asyncio.to_thread(_owner_card, authorization)
    return await asyncio.to_thread(asks.list_for_owner, row, datetime.now(timezone.utc))


@router.post("/mine/asks/{ask_id}/outcome")
async def ask_outcome(ask_id: str, body: Outcome, authorization: str | None = Header(default=None)):
    """Answer "did your ask get answered?". `helped` credits the chosen people, who must have offered
    help on this ask; `solved_elsewhere` and `still_looking` credit nobody."""
    email, row = await asyncio.to_thread(_owner_card, authorization)
    return await asyncio.to_thread(asks.set_outcome, row, email, ask_id, body.outcome, body.helper_card_ids,
                                   datetime.now(timezone.utc))


@router.get("/mine/credits")
async def my_credits(authorization: str | None = Header(default=None)):
    """The "Helped" credits on the owner's card, with ids so they can hide one."""
    _, row = await asyncio.to_thread(_owner_card, authorization)
    return await asyncio.to_thread(asks.credits_for_owner, row["id"])


@router.post("/mine/credits/{offer_id}/hide")
async def hide_credit(offer_id: str, authorization: str | None = Header(default=None)):
    _, row = await asyncio.to_thread(_owner_card, authorization)
    return await asyncio.to_thread(asks.hide_credit, row, offer_id, datetime.now(timezone.utc))
