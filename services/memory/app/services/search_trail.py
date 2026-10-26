"""Which find_people search a connection request or invitation came from.

After a signed-in owner's search, the people it returned are remembered for a day as
{handle or LinkedIn profile -> (rank, source)} under the search's id. When the same user then
requests a connection to one of them, or invites one, the request carries that search (rank and
source included) to Cards, which records the step in the funnel without the user having to do
anything. The query text is never stored, and the record is overwritten by the next search.
Everything here is best effort: no Redis, or Redis slow, means no record and the action goes on.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import urlsplit

from app.config import settings
from app.services import people_results

logger = logging.getLogger("zynd.find_people")

TRAIL_TTL_SECONDS = 24 * 3600
_SOURCE_ORDER = ("card", "zynd", "linkedin")      # the one source named when several found a person
_redis = None


def _client():
    global _redis
    if _redis is None:
        import redis.asyncio as aioredis
        _redis = aioredis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
    return _redis


def _key(uid: str) -> str:
    return f"people_search:last:{uid}"


def _source(person: dict) -> str:
    sources = person.get("sources") or []
    return next((s for s in _SOURCE_ORDER if s in sources), "")


async def remember(uid: str, search_id: str, people: list[dict]) -> None:
    """Keep the people of this search (1-based ranks, as shown) as the user's last search."""
    by: dict[str, list] = {}
    for rank, person in enumerate(people[:100], 1):
        source = _source(person)
        if source:
            for key in people_results.identity_keys(person):
                by.setdefault(key, [rank, source])
    try:
        await _client().set(_key(uid), json.dumps({"id": search_id, "by": by}), ex=TRAIL_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        logger.debug("last search not remembered: %s", exc)


async def came_from(uid: str, *, handle: str = "", linkedin_url: str = "") -> dict | None:
    """{"search_id", "rank", "source"} when this person was in the user's last search, else None."""
    keys = []
    if handle.strip().lstrip("@"):
        keys.append(f"handle:{handle.strip().lstrip('@').lower()}")
    if li := people_results.linkedin_key(linkedin_url):
        keys.append(f"li:{li}")
    if not keys:
        return None
    try:
        raw = await _client().get(_key(uid))
        trail = json.loads(raw) if raw else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("last search not read: %s", exc)
        return None
    if not isinstance(trail, dict) or not isinstance(trail.get("by"), dict):
        return None
    for key in keys:
        hit = trail["by"].get(key)
        if isinstance(hit, list) and len(hit) == 2 and isinstance(hit[0], int):
            return {"search_id": trail.get("id"), "rank": hit[0], "source": hit[1]}
    return None
