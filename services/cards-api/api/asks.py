"""The owner's side of asks (services/asks.py): close-out and credits.

Every route derives the owner from the session (api/owner_home.py's email_for) and looks things up
through that owner's own card, so another owner's ask or offer id is a 404, exactly like one that
does not exist. Nothing is taken from the request body beyond the answer itself.
"""
import asyncio
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from api.owner_home import email_for
from models.card import AskKind, AskUrl
from services import asks, owner_home

router = APIRouter()

MAX_HELPERS = 20


class Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["helped", "solved_elsewhere", "still_looking"]
    helper_card_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=64)]] = Field(
        default_factory=list, max_length=MAX_HELPERS)


class AskPost(BaseModel):
    """The whole ask. Nothing else is read from the body: the card is the session's own, the dates and
    the id are made by the server."""
    model_config = ConfigDict(extra="forbid")
    kind: AskKind
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=280)]
    url: AskUrl = None


def _owner_card(authorization: str | None) -> tuple[str, dict]:
    email = email_for(authorization)
    row = owner_home.current_row(email)
    if not row:
        raise HTTPException(404, "Create your card first")
    return email, row


def _published_card(authorization: str | None) -> tuple[str, dict]:
    email, row = _owner_card(authorization)
    if row.get("status") != "published" or not row.get("handle"):
        raise HTTPException(409, "Publish your card before posting an ask")
    return email, row


def _refresh_public_card(handle: str) -> None:
    from services.zynd_memory import ping_revalidate

    ping_revalidate(handle)


@router.post("/mine/ask")
async def post_ask(body: AskPost, authorization: str | None = Header(default=None)):
    """Post the owner's ask: {"beacon": {...}, "ask_id": str}. The same path as the beacon on the edit
    page (services/beacons.save_beacon), so the previous ask is ended as replaced, routing starts in the
    background and the card is saved with a compare-and-swap (409 if it changed under you). At most
    ASK_POSTS_PER_DAY a day (429)."""
    from services.beacons import save_beacon

    email, row = await asyncio.to_thread(_published_card, authorization)
    beacon = await asyncio.to_thread(save_beacon, row["handle"], email, body.text, body.kind, body.url)
    await asyncio.to_thread(_refresh_public_card, row["handle"])
    return {"beacon": beacon, "ask_id": beacon["id"]}


@router.delete("/mine/ask")
async def take_down_ask(authorization: str | None = Header(default=None)):
    """Take the live ask down (it ends as dismissed). Nothing to take down is not an error."""
    from services.beacons import save_beacon

    email, row = await asyncio.to_thread(_published_card, authorization)
    await asyncio.to_thread(save_beacon, row["handle"], email, None)
    await asyncio.to_thread(_refresh_public_card, row["handle"])
    return Response(status_code=204)


@router.get("/mine/asks")
async def my_asks(authorization: str | None = Header(default=None)):
    """{"asks": [{id, text, kind, url, status: active|ended, created_at, expires_at, ended_at, outcome,
    routed, offer_count, offers: [...]}]}: the current ask and asks that ended in the last 14 days
    without an answer, with who offered. `kind` and `url` are only known for the live ask (they live in
    the card's beacon, not the asks table); `routed` is how many people it was sent to."""
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
