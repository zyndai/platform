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

from models.card import AgentProfileCard
from scraping.github import github_handle_from_url
from services import card_cache
from services.beacons import active_beacon
from services.card_view import _parse_ts, fact_object, fact_predicate, live_facts
from services.search_text import query_terms

logger = logging.getLogger(__name__)

WINDOW_DAYS = 30                    # nothing older than this is shown (asks are live beacons, so 7 at most)
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

def _when(value, now: datetime) -> datetime | None:
    """A stored timestamp or date as an aware datetime inside the window, else None."""
    if isinstance(value, datetime):
        stamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    else:
        stamp = _parse_ts(value if isinstance(value, str) else None)
    if stamp is None or now - stamp > timedelta(days=WINDOW_DAYS) or stamp - now > CLOCK_SKEW:
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

def _items_for(row: dict, now: datetime, github_items: list[dict]) -> list[dict]:
    """Every feed item this card produces: {"kind", "at", "key", "content"}, each stamped with the
    time the thing happened and inside the window."""
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

    for event in github_items:
        if at := _when(event.get("at"), now):
            out.append({"kind": "github", "at": at, "key": str(event.get("id") or ""), "content": {
                "type": event.get("type"), "repo": event.get("repo"), "title": event.get("title") or "",
                "url": event.get("url")}})

    for sample in card.writing_samples:
        url = _http_url(sample.url)
        platform = (sample.platform or "").lower()
        # No parseable posted_at, no item: the sample could be years old.
        if platform in POST_PLATFORMS and url and sample.excerpt.strip() and (at := _when(sample.posted_at, now)):
            out.append({"kind": "post", "at": at, "key": _short_hash(url), "content": {
                "platform": platform, "preview": preview(sample.excerpt), "url": url}})
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


def _diversify(ranked: list[dict], block: int, cap: int = PER_AUTHOR_CAP) -> list[dict]:
    """Reorder so no author has more than `cap` items in any block of `block` positions, keeping rank
    order otherwise. What a block cannot take is pushed to a later block rather than dropped, so the
    feed still ends with everything in it. A block always takes at least the best remaining item."""
    remaining, out = list(ranked), []
    while remaining:
        taken: dict[str, int] = {}
        page, rest = [], []
        for item in remaining:
            handle = item["author"]["handle"]
            if len(page) < block and taken.get(handle, 0) < cap:
                taken[handle] = taken.get(handle, 0) + 1
                page.append(item)
            else:
                rest.append(item)
        out.extend(page)
        remaining = rest
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
    the inbox returns it to both people; so one list covers "blocked" and "blocked me". Handles the
    viewer chose to hide (match preferences) are left out too."""
    by_handle: dict[str, dict] = {}
    blocked = {h.lower() for h in hidden_handles or [] if h}
    for c in inbox_connections or []:
        handle = ((c.get("partner") or {}).get("handle") or "").lower()
        if not handle:
            continue
        if c.get("status") == "blocked":
            blocked.add(handle)
        by_handle[handle] = {"id": c.get("id"), "status": c.get("status"), "incoming": bool(c.get("incoming"))}
    return by_handle, blocked


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
    """One page of the feed: {"items": [...], "next_cursor": str | None}.

    `rows` are published-card rows ({"id", "handle", "model", "unit", "claimed", "published_at"});
    only claimed cards take part, since only a claimed card can be messaged. `connections` is
    handle -> {"id", "status", "incoming"}; `github` is handle -> items from feed_github.get()."""
    limit = max(1, min(limit, MAX_LIMIT))
    own = (viewer.handle or "").lower()
    ranked: list[dict] = []
    for row in rows:
        handle = (row.get("handle") or "").lower()
        if not handle or not row.get("claimed") or handle in blocked or handle == own or row.get("id") == viewer.card_id:
            continue
        connection = connections.get(handle)
        if filter == "network" and not (connection and connection["status"] == "accepted"):
            continue
        card: AgentProfileCard = row["model"]
        for item in _items_for(row, now, github.get(row["handle"]) or []):
            if filter == "asks" and item["kind"] != "ask":
                continue
            score, reason = _score_and_reason(item, viewer, row, connection, now)
            ranked.append({
                "id": f"{item['kind']}:{row['handle']}:{item['key']}",
                "kind": item["kind"],
                "at": item["at"].isoformat(),
                "reason": reason,
                "author": {
                    "handle": row["handle"], "name": card.identity.name or "Zynd member",
                    "headline": card.identity.headline, "avatar_url": card.identity.avatar_url or None,
                    "location": card.identity.location, "claimed": True,
                },
                "content": item["content"],
                "connection": connection,
                "_sort": (-score, -item["at"].timestamp(), item["kind"], item["key"]),
            })
    ranked.sort(key=lambda i: i["_sort"])
    ordered = _diversify(ranked, limit)
    page = ordered[offset:offset + limit]
    for item in page:
        del item["_sort"]
    return {"items": page, "next_cursor": encode_cursor(offset + limit) if offset + limit < len(ordered) else None}


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


def feed_for_user(user_id: str, *, filter: str = "all", limit: int = DEFAULT_LIMIT, offset: int = 0,
                  now: datetime | None = None) -> dict:
    """The feed for a signed-in person. Blocking (database and snapshot reads): call it from a
    threadpool, as the other network routes do."""
    from services import feed_github, match_prefs, network

    now = now or datetime.now(timezone.utc)
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

    page = build_feed(viewer, rows, connections, blocked, github, now, filter=filter, limit=limit, offset=offset)
    page["viewer"] = {"has_card": mine is not None, "handle": viewer.handle}
    return page


def _hidden(user_id: str, match_prefs) -> list[str]:
    """Handles the viewer chose to hide; best effort, since the table only exists with network controls."""
    try:
        return list(match_prefs.get(user_id).get("hide_person") or [])
    except Exception as exc:  # noqa: BLE001
        logger.info("feed: match preferences unavailable (%s)", exc)
        return []
