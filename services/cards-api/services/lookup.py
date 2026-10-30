"""Find one specific person by name or handle ("Chandan", "Chandan Kumar", "@chandan-kumar-2en8").

Semantic search is the wrong tool for a name: it ranks by meaning, and a name has none. This is a
plain text match on the card's handle and name, public Card data only (the same fields /search
returns), so it cannot be used to read anything search could not.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque

import config
from services import card_cache, network

FETCH = 25
RATE_LIMIT = 30          # lookups per client per minute
_WINDOW = 60.0
_hits: dict[str, deque] = defaultdict(deque)


def allow(request) -> bool:
    """Per-client rate limit: lookups let anyone page through names, so they are throttled harder
    than search. In-process, so it is per worker, which is enough to stop a script."""
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    client = forwarded or (request.client.host if request.client else "unknown")
    now = time.monotonic()
    hits = _hits[client]
    while hits and now - hits[0] > _WINDOW:
        hits.popleft()
    if not hits:
        _hits.pop(client, None)
        hits = _hits[client]
    if len(hits) >= RATE_LIMIT:
        return False
    hits.append(now)
    if len(_hits) > 5000:       # never grow without bound under a spray of addresses
        for key in [k for k, v in _hits.items() if not v or now - v[-1] > _WINDOW]:
            _hits.pop(key, None)
    return True


def _rank(row: dict, needle: str) -> int:
    """0: the full name or handle is exactly the text; 1: the name or handle starts with it; 2: a
    word in the name does; 3: it is somewhere inside."""
    handle = (row.get("handle") or "").lower()
    name = (((row.get("card") or {}).get("identity") or {}).get("name") or "").lower().strip()
    if needle in (name, handle):
        return 0
    if handle.startswith(needle) or name.startswith(needle):
        return 1
    if any(word.startswith(needle) for word in re.split(r"[\s._-]+", name)):
        return 2
    return 3


_REASONS = {0: "Name match", 1: "Name starts with your search", 2: "A word in the name starts with your search",
            3: "Name contains your search"}
_SCORES = {0: 0.95, 1: 0.8, 2: 0.7, 3: 0.6}


def lookup_by_name(name: str, limit: int = 5, include_unclaimed: bool = False) -> list[dict]:
    term = network._search_term(name)
    if len(term) < network.SUGGEST_MIN_CHARS:
        return []
    needle = term.lower()
    snap = card_cache.snapshot()
    if snap is not None:
        # the database query below, on the in-process copy: a name or handle that contains the text,
        # newest first, at most FETCH
        newest = sorted(snap.rows, key=lambda r: r.get("published_at") or "", reverse=True)
        rows = [r for r in newest if (include_unclaimed or r["claimed"])
                and (needle in (r.get("handle") or "").lower()
                     or needle in (((r.get("card") or {}).get("identity") or {}).get("name") or "").lower())][:FETCH]
        return _shape(rows, needle, limit)
    pattern = f'"*{term}*"'      # quoted so spaces and dots survive; the term holds no quote to escape
    query = (
        network._sb()
        .table("agent_profile_cards")
        .select("id,handle,card,owner_email")
        .eq("status", "published")
        .or_(f"handle.ilike.{pattern},card->identity->>name.ilike.{pattern}")
        .order("published_at", desc=True, nullsfirst=False)
        .limit(FETCH)
    )
    if not include_unclaimed:
        query = query.not_.is_("owner_email", "null")
    rows = query.execute().data or []
    return _shape(rows, needle, limit)


def _shape(rows: list[dict], needle: str, limit: int) -> list[dict]:
    ranked = sorted(enumerate(rows), key=lambda item: (_rank(item[1], needle), item[0]))
    out: list[dict] = []
    for _, row in ranked:
        card = row.get("card") or {}
        identity = card.get("identity") or {}
        rank = _rank(row, needle)
        handle = row.get("handle")
        out.append({
            "agent_id": row.get("id"),
            "handle": handle,
            "name": identity.get("name") or "",
            "headline": identity.get("headline") or "",
            "location": identity.get("location") or "",
            "skills": [s.get("name") for s in card.get("skills") or [] if isinstance(s, dict) and s.get("name")][:8],
            "linkedin_url": (identity.get("links") or {}).get("linkedin") or "",
            "match_score": _SCORES[rank],
            "match_reasons": [_REASONS[rank]],
            "url": config.profile_url(handle) if handle else f"{config.SITE_BASE_URL}/profile/{row.get('id')}",
        })
        if len(out) >= limit:
            break
    return out
