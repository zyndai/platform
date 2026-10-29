"""The action feed (services/feed.py): GET /cards/feed and POST /cards/feed/reply.

Synchronous on purpose, like api/network.py: the Supabase client blocks, so FastAPI runs the handler
in its threadpool. Authentication is the network API's too (a shared Zynd account session, or the
Memory service token with X-Zynd-User), so the feed and the reply buttons under it agree on who
the caller is.
"""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from api.network import _uid
from services import feed

router = APIRouter()


class FeedReply(BaseModel):
    """A reply to one feed item. Nothing here chooses the channel or the recipient beyond the item
    id: the server works both out from its own data."""
    model_config = ConfigDict(extra="forbid")
    item_id: str = Field(min_length=3, max_length=feed.ITEM_ID_MAX_CHARS)
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=feed.REPLY_MAX_CHARS)]
    # Idempotency key for the direct-message path: retrying the same send must not post it twice.
    client_id: UUID | None = None


def _session_user(authorization: str | None, x_zynd_user: str | None) -> str:
    if not authorization:
        raise HTTPException(401, "Sign in to see your feed")
    return _uid(authorization, x_zynd_user)


@router.get("/feed")
def get_feed(
    request: Request,
    filter: Literal["all", "asks", "network"] = Query("all"),
    limit: int = Query(feed.DEFAULT_LIMIT, ge=1, le=feed.MAX_LIMIT),
    cursor: str | None = Query(None, max_length=64),
    authorization: str | None = Header(default=None),
    x_zynd_user: str | None = Header(default=None),
):
    """{"items": [...], "next_cursor": str | null, "viewer": {"has_card", "handle"}}.

    A caller without a Card still gets the feed (has_card=false) so the page can invite them to
    create one; replying needs a Card."""
    user_id = _session_user(authorization, x_zynd_user)
    try:
        offset = feed.decode_cursor(cursor)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    page = feed.feed_for_user(user_id, filter=filter, limit=limit, offset=offset)
    feed.record_view(request, page, filter=filter, offset=offset)
    return page


@router.post("/feed/reply")
def reply_to_feed_item(
    body: FeedReply,
    authorization: str | None = Header(default=None),
    x_zynd_user: str | None = Header(default=None),
):
    """{"channel": "dm" | "request", "connection": {"id", "status", "incoming"}}.

    Connected: a direct message. Not connected: a connection request carrying the message, under the
    weekly request limits (429). Already requested, or they asked you first: 409."""
    user_id = _session_user(authorization, x_zynd_user)
    return feed.reply_to_item(user_id, body.item_id, body.message, str(body.client_id) if body.client_id else None)
