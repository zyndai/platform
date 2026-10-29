"""The action feed: moments of momentum from other people's cards, each ending in a reply.

Cards' promise is a living identity: the card stays current because the owner's AI, GitHub and
browser keep it current. The feed turns that into something to act on. It shows what happened
recently on OTHER people's cards, built from data Cards already holds (no new tables), and every
item is a reason to start a conversation (a DM, or a connection request), not something to like:

  ask        the card's live beacon ("Looking for ...", 7 days at most)
  working_on a live `is_working_on` memory fact, stamped with its approval time
  exploring  something the owner clipped with the Zynd Companion, stamped with when
  joined     the card was published recently
  github     a release, new public repository or merged pull request (services/feed_github.py)
  post       the owner's own recent LinkedIn / X post: a short preview and a link out, never the
             full text (the original stays where it was written)

Plain `card.working_on` strings carry no timestamp, so they make no items: an item without a real
time cannot be placed in a feed honestly.

Ranking is deliberately plain so it can be explained: an item's recency (halving every
RECENCY_HALF_LIFE_DAYS, weighted by kind) plus boosts for a connected author, for similar work
(cosine of the two card embeddings), and for an ask that overlaps what the viewer can help with.
The reason shown to the viewer is whichever of those applies.

When the recent feed is thin, older posts and GitHub activity (up to EARLIER_MAX_DAYS) follow every
recent item, newest first and marked `earlier`; they never outrank a recent one. People the viewer
is blocked from, or has declined or revoked a connection with, never appear.

reply_to_item() is the one way to answer an item: the server picks the channel from the real
connection state (a message if connected, otherwise a connection request carrying the message) and
re-checks the author, the blocks and the item itself, so the client decides nothing. Feed events
(feed_view, feed_reply) carry counts and kinds only, never what anyone typed.

build_feed() is pure (viewer, rows, connections, blocks, GitHub items, now in; a page out) so it is
tested without a database. feed_for_user() gathers those inputs: the published-cards snapshot, one
inbox call for connections and blocks, and the cached GitHub items (never waiting on GitHub).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import HTTPException

from models.card import AgentProfileCard
from scraping.github import github_handle_from_url
from services import card_cache
from services.beacons import active_beacon
from services.card_view import _parse_ts, fact_object, fact_predicate, live_facts
from services.search_text import query_terms

logger = logging.getLogger(__name__)

WINDOW_DAYS = 30                    # recent items: ranked, and always ahead of earlier ones
EARLIER_MAX_DAYS = 365              # posts and GitHub activity older than the window still fill a thin feed up to this age
RECENCY_HALF_LIFE_DAYS = 3.0        # an item loses half its recency score every 3 days
CLOCK_SKEW = timedelta(minutes=5)   # a stamp this far ahead of now is a clock difference, not the future

# Recency is scaled by kind: a request for help is the most actionable moment, a clipped link the least.
KIND_WEIGHT = {"ask": 1.0, "github": 0.9, "working_on": 0.85, "joined": 0.8, "post": 0.7, "exploring": 0.6}
CONNECTION_BOOST = 0.35             # the author is an accepted connection
RELEVANCE_WEIGHT = 0.35             # times how far the cards' cosine is above RELEVANCE_FLOOR
RELEVANCE_FLOOR = 0.3               # a cosine below this says nothing about similar work
SIMILAR_COSINE = 0.5                # from here the reason reads "Similar work to yours"
ASK_HELP_BOOST = 0.5                # an ask whose words overlap what the viewer can help with

PER_AUTHOR_CAP = 2                  # most items one person gets in a page (see _diversify)
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
POST_PREVIEW_CHARS = 200
JOINED_TOPICS = 3
POST_PLATFORMS = ("linkedin", "x")
FILTERS = ("all", "asks", "network")
FINAL_STATUSES = frozenset({"blocked", "declined", "revoked"})

REASON_CONNECTED = "You're connected"
REASON_CAN_HELP = "Matches what you can help with"
REASON_SIMILAR = "Similar work to yours"
REASON_NEW = "New on Zynd"


@dataclass
class Viewer:
    """Whoever is reading the feed. Without a card there is nothing to match against, but the feed
    still renders (the page then asks them to create one)."""
    card_id: str | None = None
    handle: str | None = None
    card: AgentProfileCard | None = None
    unit: list[float] = field(default_factory=list)


# --- Small helpers ----------------------------------------------------------------------------

def _when(value, now: datetime, max_days: int = WINDOW_DAYS) -> datetime | None:
    """A stored timestamp or date as an aware datetime no older than `max_days`, else None."""
    if isinstance(value, datetime):
        stamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    else:
        stamp = _parse_ts(value if isinstance(value, str) else None)
    if stamp is None or now - stamp > timedelta(days=max_days) or stamp - now > CLOCK_SKEW:
        return None
    return min(stamp, now)


def _short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def preview(text: str, limit: int = POST_PREVIEW_CHARS) -> str:
    """The first `limit` characters of a post, cut on a word boundary and marked with an ellipsis;
    a post that already fits is returned whole."""
    clean = " ".join((text or "").split())
    if len(clean) <= limit:
        return clean
    cut = clean[:limit]
    space = cut.rfind(" ")
    if space >= limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,.;:-–—") + "…"


def _http_url(value) -> str:
    return value if isinstance(value, str) and value.startswith(("http://", "https://")) else ""


# --- Items from one card ----------------------------------------------------------------------

def _items_for(row: dict, now: datetime, github_items: list[dict], earlier: bool = True) -> list[dict]:
    """Every feed item this card produces: {"kind", "at", "key", "content", "earlier"}, each stamped
    with the time the thing happened. Asks, working-on facts, clips and joins must be inside the
    window; posts and GitHub activity may also be "earlier" (older than the window, up to
    EARLIER_MAX_DAYS) when `earlier` is true. Earlier items are shown after every recent one."""
    card: AgentProfileCard = row["model"]
    out: list[dict] = []

    beacon = active_beacon(card, now)
    if beacon and (at := _when(beacon.created_at, now)):
        out.append({"kind": "ask", "at": at, "key": beacon.created_at.isoformat(), "content": {"text": beacon.text.strip()}})

    seen: set[str] = set()
    for fact in live_facts(card.zynd_memory, now):
        text = " ".join(fact_object(fact).split())
        if fact_predicate(fact) != "is_working_on" or not text or text.casefold() in seen:
            continue
        if at := _when(fact.get("approved_at"), now):
            seen.add(text.casefold())
            out.append({"kind": "working_on", "at": at, "key": _short_hash(text), "content": {"text": text}})

    for item in card.exploring:
        if item.url and (at := _when(item.added_at, now)):
            title = item.title.strip() or (urlparse(item.url).hostname or item.url)
            out.append({"kind": "exploring", "at": at, "key": _short_hash(item.url), "content": {
                "title": title, "url": item.url, "note": item.note.strip(), "kind": item.kind}})

    if at := _when(row.get("published_at"), now):
        out.append({"kind": "joined", "at": at, "key": "joined", "content": {
            "headline": card.identity.headline.strip(), "can_help_with": list(card.can_help_with[:JOINED_TOPICS])}})

    reach = EARLIER_MAX_DAYS if earlier else WINDOW_DAYS
    for event in github_items:
        if at := _when(event.get("at"), now, reach):
            out.append({"kind": "github", "at": at, "key": str(event.get("id") or ""), "content": {
                "type": event.get("type"), "repo": event.get("repo"), "title": event.get("title") or "",
                "url": event.get("url")}})

    for sample in card.writing_samples:
        url = _http_url(sample.url)
        platform = (sample.platform or "").lower()
        # No parseable posted_at, no item: the sample could be years old.
        if platform in POST_PLATFORMS and url and sample.excerpt.strip() and (at := _when(sample.posted_at, now, reach)):
            out.append({"kind": "post", "at": at, "key": _short_hash(url), "content": {
                "platform": platform, "preview": preview(sample.excerpt), "url": url}})
    for item in out:
        item["earlier"] = now - item["at"] > timedelta(days=WINDOW_DAYS)
    return out


def github_handle(card: AgentProfileCard) -> str | None:
    return github_handle_from_url((card.identity.links or {}).get("github"))


# --- Scoring ----------------------------------------------------------------------------------

def _recency(item: dict, now: datetime) -> float:
    age_days = max((now - item["at"]).total_seconds(), 0.0) / 86400
    return KIND_WEIGHT[item["kind"]] * 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


def _overlaps(ask: str, can_help: list[str]) -> bool:
    wanted = set(query_terms(ask))
    return bool(wanted) and any(wanted & set(query_terms(topic)) for topic in can_help)


def _score_and_reason(item: dict, viewer: Viewer, row: dict, connection: dict | None, now: datetime) -> tuple[float, str]:
    score = _recency(item, now)
    cosine = card_cache.dot(viewer.unit, row.get("unit") or []) or 0.0
    relevance = max(0.0, (cosine - RELEVANCE_FLOOR) / (1 - RELEVANCE_FLOOR))
    connected = bool(connection and connection["status"] == "accepted")
    helps = item["kind"] == "ask" and viewer.card is not None and _overlaps(item["content"]["text"], viewer.card.can_help_with)

    score += (CONNECTION_BOOST if connected else 0.0) + RELEVANCE_WEIGHT * relevance + (ASK_HELP_BOOST if helps else 0.0)
    if helps:
        reason = REASON_CAN_HELP
    elif connected:
        reason = REASON_CONNECTED
    elif cosine >= SIMILAR_COSINE:
        reason = REASON_SIMILAR
    elif item["kind"] == "joined":
        reason = REASON_NEW
    else:
        reason = ""
    return score, reason


def _diversify(ranked: list[dict], block: int, cap: int = PER_AUTHOR_CAP, first: int | None = None) -> list[dict]:
    """Reorder so no author has more than `cap` items in any block of `block` positions, keeping rank
    order otherwise. What a block cannot take is pushed to a later block rather than dropped, so the
    feed still ends with everything in it. A block always takes at least the best remaining item.
    `first` is the size of the first block when the list starts part-way through a page."""
    remaining, out = list(ranked), []
    size = first or block
    while remaining:
        taken: dict[str, int] = {}
        page, rest = [], []
        for item in remaining:
            handle = item["author"]["handle"]
            if len(page) < size and taken.get(handle, 0) < cap:
                taken[handle] = taken.get(handle, 0) + 1
                page.append(item)
            else:
                rest.append(item)
        out.extend(page)
        remaining = rest
        size = block
    return out


# --- Cursor -----------------------------------------------------------------------------------

def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o{offset}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    """The offset an opaque cursor stands for; ValueError for anything this module did not issue."""
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        offset = int(raw[1:]) if raw.startswith("o") else -1
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("Invalid cursor") from exc
    if offset < 0:
        raise ValueError("Invalid cursor")
    return offset


# --- The pure builder -------------------------------------------------------------------------

def connection_maps(inbox_connections: list[dict], hidden_handles: list[str] | None = None) -> tuple[dict[str, dict], set[str]]:
    """(handle -> {"id", "status", "incoming"}, handles to leave out) from the inbox's connection rows.

    A block is stored as a connection row with status "blocked" for the pair, whoever blocked, and
    the inbox returns it to both people; so one list covers "blocked" and "blocked me". A declined or
    revoked connection is final too (the pair can never connect again), so those people are left out
    as well: only pending and accepted ones stay. Handles the viewer chose to hide (match
    preferences) are left out too."""
    by_handle: dict[str, dict] = {}
    blocked = {h.lower() for h in hidden_handles or [] if h}
    for c in inbox_connections or []:
        handle = ((c.get("partner") or {}).get("handle") or "").lower()
        if not handle:
            continue
        if c.get("status") in FINAL_STATUSES:
            blocked.add(handle)
        by_handle[handle] = {"id": c.get("id"), "status": c.get("status"), "incoming": bool(c.get("incoming"))}
    return by_handle, blocked


def rank_feed(
    viewer: Viewer,
    rows: list[dict],
    connections: dict[str, dict],
    blocked: set[str],
    github: dict[str, list[dict]],
    now: datetime,
    *,
    filter: str = "all",
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    """The whole feed in display order: every recent item (ranked by score), then, for the "all" and
    "network" filters, the earlier items (newest first). Earlier items never outrank recent ones, and
    each block is diversified separately so the per-author cap holds on every page.

    `rows` are published-card rows ({"id", "handle", "model", "unit", "claimed", "published_at"});
    only claimed cards take part, since only a claimed card can be messaged. `connections` is
    handle -> {"id", "status", "incoming"}; `github` is handle -> items from feed_github.get()."""
    limit = max(1, min(limit, MAX_LIMIT))
    own = (viewer.handle or "").lower()
    recent: list[dict] = []
    earlier: list[dict] = []
    for row in rows:
        handle = (row.get("handle") or "").lower()
        if not handle or not row.get("claimed") or handle in blocked or handle == own or row.get("id") == viewer.card_id:
            continue
        connection = connections.get(handle)
        if filter == "network" and not (connection and connection["status"] == "accepted"):
            continue
        card: AgentProfileCard = row["model"]
        for item in _items_for(row, now, github.get(row["handle"]) or [], earlier=filter != "asks"):
            if filter == "asks" and item["kind"] != "ask":
                continue
            score, reason = _score_and_reason(item, viewer, row, connection, now)
            built = {
                "id": f"{item['kind']}:{row['handle']}:{item['key']}",
                "kind": item["kind"],
                "at": item["at"].isoformat(),
                "earlier": item["earlier"],
                "reason": reason,
                "author": {
                    "handle": row["handle"], "name": card.identity.name or "Zynd member",
                    "headline": card.identity.headline, "avatar_url": card.identity.avatar_url or None,
                    "location": card.identity.location, "claimed": True,
                },
                "content": item["content"],
                "connection": connection,
            }
            if item["earlier"]:
                built["_sort"] = (-item["at"].timestamp(), item["kind"], item["key"])
                earlier.append(built)
            else:
                built["_sort"] = (-score, -item["at"].timestamp(), item["kind"], item["key"])
                recent.append(built)
    recent.sort(key=lambda i: i["_sort"])
    earlier.sort(key=lambda i: i["_sort"])
    ordered = _diversify(recent, limit)
    lead = len(ordered) % limit          # the earlier block starts part-way through a page
    ordered += _diversify(earlier, limit, first=limit - lead if lead else None)
    for item in ordered:
        del item["_sort"]
    return ordered


def build_feed(
    viewer: Viewer,
    rows: list[dict],
    connections: dict[str, dict],
    blocked: set[str],
    github: dict[str, list[dict]],
    now: datetime,
    *,
    filter: str = "all",
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict:
    """One page of the feed: {"items": [...], "next_cursor": str | None}. See rank_feed for the order;
    paging is an offset into that one list, so it is consistent across the recent / earlier boundary."""
    limit = max(1, min(limit, MAX_LIMIT))
    ordered = rank_feed(viewer, rows, connections, blocked, github, now, filter=filter, limit=limit)
    return {"items": ordered[offset:offset + limit],
            "next_cursor": encode_cursor(offset + limit) if offset + limit < len(ordered) else None}


# --- Gathering the inputs ---------------------------------------------------------------------

_FALLBACK_TTL_SECONDS = 60.0
_fallback_lock = threading.Lock()
_fallback: tuple[float, list[dict]] | None = None


def _rows_from_database() -> list[dict]:
    """Every published card, read straight from the database: the way search degrades when the
    corpus is too big to copy. Kept for a minute so a busy feed does not rescan on every request."""
    global _fallback
    with _fallback_lock:
        if _fallback and time.monotonic() - _fallback[0] < _FALLBACK_TTL_SECONDS:
            return _fallback[1]
    from services import cards as cards_service
    rows = []
    for r in cards_service.list_published_rows(columns="id,card,handle,embedding,owner_email,published_at"):
        try:
            model = AgentProfileCard.model_validate(r.get("card") or {})
        except Exception:  # noqa: BLE001 — a card that cannot be read has no feed items
            continue
        if r.get("handle"):
            model.handle = r["handle"]
        owner = (r.get("owner_email") or "").strip()
        rows.append({"id": r.get("id"), "handle": r.get("handle"), "model": model, "unit": card_cache.unit(r.get("embedding")),
                     "claimed": bool(owner), "published_at": r.get("published_at") or ""})
    with _fallback_lock:
        _fallback = (time.monotonic(), rows)
    return rows


def published_rows() -> list[dict]:
    snap = card_cache.snapshot()
    return snap.rows if snap is not None else _rows_from_database()


def _hidden(user_id: str, match_prefs) -> list[str]:
    """Handles the viewer chose to hide; best effort, since the table only exists with network controls."""
    try:
        return list(match_prefs.get(user_id).get("hide_person") or [])
    except Exception as exc:  # noqa: BLE001
        logger.info("feed: match preferences unavailable (%s)", exc)
        return []


@dataclass
class Context:
    """Everything the feed needs about one viewer, gathered once per request."""
    now: datetime
    rows: list[dict]
    mine: dict | None
    viewer: Viewer
    connections: dict[str, dict]
    blocked: set[str]
    github: dict[str, list[dict]]


def _context(user_id: str, now: datetime) -> Context:
    from services import feed_github, match_prefs, network

    rows = published_rows()
    mine = network._find_card_for_user(user_id)
    viewer = Viewer()
    if mine:
        viewer.card_id, viewer.handle = mine.get("id"), mine.get("handle")
        known = next((r for r in rows if r.get("id") == viewer.card_id or r.get("handle") == viewer.handle), None)
        if known:
            viewer.card, viewer.unit = known["model"], known.get("unit") or []
        else:       # published a moment ago, before the snapshot refreshed
            try:
                viewer.card = AgentProfileCard.model_validate(mine.get("card") or {})
            except Exception:  # noqa: BLE001
                viewer.card = None

    connections, blocked = connection_maps(network.get_inbox(user_id).get("connections", []), _hidden(user_id, match_prefs))

    wanted: dict[str, str] = {}     # github login -> card handle, for cards that can appear
    for row in rows:
        handle = (row.get("handle") or "").lower()
        if row.get("claimed") and handle and handle not in blocked and handle != (viewer.handle or "").lower():
            if login := github_handle(row["model"]):
                wanted[row["handle"]] = login
    cached = feed_github.get(list(wanted.values()))
    github = {handle: cached[login] for handle, login in wanted.items() if login in cached}
    return Context(now, rows, mine, viewer, connections, blocked, github)


def feed_for_user(user_id: str, *, filter: str = "all", limit: int = DEFAULT_LIMIT, offset: int = 0,
                  now: datetime | None = None) -> dict:
    """The feed for a signed-in person. Blocking (database and snapshot reads): call it from a
    threadpool, as the other network routes do."""
    ctx = _context(user_id, now or datetime.now(timezone.utc))
    page = build_feed(ctx.viewer, ctx.rows, ctx.connections, ctx.blocked, ctx.github, ctx.now,
                      filter=filter, limit=limit, offset=offset)
    page["viewer"] = {"has_card": ctx.mine is not None, "handle": ctx.viewer.handle}
    return page


# --- Replying ---------------------------------------------------------------------------------

REPLY_MAX_CHARS = 2000              # the connection request note limit (a DM allows more)
ITEM_ID_MAX_CHARS = 200


def parse_item_id(item_id: str) -> tuple[str, str]:
    """(kind, handle) from "kind:handle:key"; ValueError when it is not an id this module issues."""
    parts = (item_id or "").split(":", 2)
    if len(parts) != 3 or parts[0] not in KIND_WEIGHT or not parts[1] or not parts[2]:
        raise ValueError("Invalid item")
    return parts[0], parts[1]


def reply_to_item(user_id: str, item_id: str, message: str, client_id: str | None = None,
                  now: datetime | None = None) -> dict:
    """Reply to a feed item: a message when the two are connected, a connection request carrying the
    message when they are not. The server decides the channel from the real connection state and
    re-checks everything itself (the author, the blocks, the item), so a client can neither pick
    the channel nor reach someone the feed would not show. Returns
    {"channel": "dm" | "request", "connection": {id, status, incoming}}; request limits (429) and
    state conflicts (409) come from the network service and pass through."""
    from services import network

    try:
        kind, handle = parse_item_id(item_id)
    except ValueError as exc:
        raise HTTPException(422, "That is not a feed item") from exc
    ctx = _context(user_id, now or datetime.now(timezone.utc))
    if ctx.mine is None:
        raise HTTPException(422, "Create your Card before replying to people")
    key = handle.lower()
    if key == (ctx.viewer.handle or "").lower():
        raise HTTPException(422, "You cannot reply to your own item")
    if key in ctx.blocked:
        # Blocked, declined, revoked or hidden: worded neutrally, as everywhere else.
        raise HTTPException(403, "Replying to this person is not available")
    author = network._card_for_handle(handle)       # 404 unless published and claimed
    if author["owner_user_id"] == user_id:
        raise HTTPException(422, "You cannot reply to your own item")
    item = next((i for i in rank_feed(ctx.viewer, ctx.rows, ctx.connections, ctx.blocked, ctx.github, ctx.now,
                                      limit=MAX_LIMIT) if i["id"] == item_id), None)
    if item is None or item["kind"] != kind:
        raise HTTPException(404, "That item is no longer in your feed")

    connection = ctx.connections.get(key)
    if connection is None:
        result = network.request_connection(user_id, handle, message)
        found = result["connection"]
        if not result["existing"]:
            return _replied("request", found, item, ctx)
        # Someone else's request landed between loading the inbox and now.
        connection = {"id": found["id"], "status": found["status"], "incoming": found["incoming"]}
    if connection["status"] == "accepted":
        network.send_message(user_id, connection["id"], message, client_id)
        return _replied("dm", connection, item, ctx)
    if connection["status"] == "pending":
        if connection["incoming"]:
            raise HTTPException(409, "They already sent you a request. Accept it in your Network.")
        raise HTTPException(409, "Already requested")
    raise HTTPException(403, "Replying to this person is not available")


def _replied(channel: str, connection: dict, item: dict, ctx: Context) -> dict:
    out = {"id": connection.get("id"), "status": connection.get("status"), "incoming": bool(connection.get("incoming"))}
    record_reply(item, channel, ctx.now)
    return {"channel": channel, "connection": out}


# --- Events -----------------------------------------------------------------------------------
# Counts and kinds only: never the message, the viewer, or anything they typed. Best effort.

def record_view(request, page: dict, *, filter: str, offset: int) -> None:
    from services import events

    kinds: dict[str, int] = {}
    for item in page["items"]:
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    try:
        events.emit("feed_view", request=request, meta={"filter": filter, "offset": offset, "n": len(page["items"]), "kinds": kinds})
    except Exception:  # noqa: BLE001 — an event must never fail the request
        logger.info("feed: could not record feed_view")


def record_reply(item: dict, channel: str, now: datetime) -> None:
    from services import events

    age_hours = int(max((now - datetime.fromisoformat(item["at"])).total_seconds(), 0) // 3600)
    try:
        events.emit("feed_reply", handle=item["author"]["handle"], meta={
            "kind": item["kind"], "channel": channel, "earlier": bool(item["earlier"]), "age_hours": age_hours})
    except Exception:  # noqa: BLE001
        logger.info("feed: could not record feed_reply")
