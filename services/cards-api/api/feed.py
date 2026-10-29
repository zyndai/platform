"""GET /cards/feed: the signed-in person's action feed (services/feed.py).

Synchronous on purpose, like api/network.py: the Supabase client blocks, so FastAPI runs the handler
in its threadpool. Authentication is the network API's too (a shared Zynd account session, or the
Memory service token with X-Zynd-User), so the feed and the reply buttons under it agree on who
the caller is.
"""
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query

from api.network import _uid
from services import feed

router = APIRouter()


@router.get("/feed")
def get_feed(
    filter: Literal["all", "asks", "network"] = Query("all"),
    limit: int = Query(feed.DEFAULT_LIMIT, ge=1, le=feed.MAX_LIMIT),
    cursor: str | None = Query(None, max_length=64),
    authorization: str | None = Header(default=None),
    x_zynd_user: str | None = Header(default=None),
):
    """{"items": [...], "next_cursor": str | null, "viewer": {"has_card", "handle"}}.

    A caller without a Card still gets the feed (has_card=false) so the page can invite them to
    create one; replying needs a Card, and the network endpoints say so themselves."""
    if not authorization:
        raise HTTPException(401, "Sign in to see your feed")
    user_id = _uid(authorization, x_zynd_user)
    try:
        offset = feed.decode_cursor(cursor)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return feed.feed_for_user(user_id, filter=filter, limit=limit, offset=offset)
