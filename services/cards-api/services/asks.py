"""Asks: a beacon that reaches the right people, records who offered, closes, and credits the helper.

The plan is docs/plans/ZYND_ASKS_PLAN.md. In short:

  publish   save_beacon() gives the beacon an id and (after the card write succeeds) record_publish()
            stores an `asks` row; a new ask ends the previous one ("replaced"), a dismiss ends it.
  route     a background task runs the existing people search with the ask as the query and keeps the
            best claimed matches (select_routes) in `ask_routes`: they see the ask in their feed and,
            once, in their morning digest.
  offer     a feed reply to an ask records an `ask_offers` row (record_offer), one per helper.
  close     the owner picks an outcome and which offerers helped (set_outcome); those get a credit.
  credit    a helper's public card shows "Helped" for credited offers that are not hidden and whose
            asker is still published (credits_for_card); the helper can hide any credit.

Everything here is optional. The tables come from migration cards 0033; until a person applies it,
every function quietly does nothing (the missing relation is detected once, logged at info level and
re-checked a minute later, so applying the migration needs no restart). Publishing a beacon, the
feed and replies never fail because of asks. Nothing here logs or stores message text, and a failure
is logged by its error code only (PostgREST errors can quote the row).
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException

import config
from models.card import AgentProfileCard
from services.saved_searches import STRONG_MATCH

logger = logging.getLogger(__name__)

ASK_ROUTE_MAX = 5                       # people an ask is routed to
ASK_ROUTE_CANDIDATES = 20               # search results read to find them
ASK_ROUTE_MIN_SCORE = STRONG_MATCH      # search.py's scale: 0.6+ is a good match (what saved-search alerts wait for)
ASKS_PER_DIGEST = 2                     # "Asks you could help with" entries in one digest
ASK_CLOSEOUT_DAYS = 14                  # how long an ended ask still asks "did you find help?"
CREDITS_SHOWN = 3                       # latest credits listed on a helper's card
CREDITS_IN_DIGEST = 3
CREDIT_ASK_CHARS = 80                   # an ask's text is cut to this on a card
TABLES_RETRY_SECONDS = 60.0             # after finding the tables missing, look again this often
OUTCOMES = ("helped", "solved_elsewhere", "still_looking")
CLOSING_OUTCOMES = ("helped", "solved_elsewhere")      # these end a live ask

_state_lock = threading.Lock()
_missing_until = 0.0
_pool: ThreadPoolExecutor | None = None


# --- Tables missing (migration 0033 not applied) ------------------------------------------------

def is_missing_table(exc: Exception) -> bool:
    code = str(getattr(exc, "code", "") or "")
    text = str(exc)
    return (code in ("42P01", "PGRST205")
            or ("schema cache" in text and "table" in text)
            or ("does not exist" in text and "relation" in text))


def available() -> bool:
    return time.monotonic() >= _missing_until


def guarded(what: str, fn, default=None):
    """Run a database step of the asks features. A missing table switches the features off for
    TABLES_RETRY_SECONDS (one info line); any other failure is logged by code and skipped. Always
    returns `default` on failure: callers never need a try/except of their own."""
    global _missing_until
    if not available():
        return default
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — asks must never break what they are attached to
        if is_missing_table(exc):
            with _state_lock:
                first = time.monotonic() >= _missing_until
                _missing_until = time.monotonic() + TABLES_RETRY_SECONDS
            if first:
                logger.info("asks: tables not found (cards migration 0033 not applied); asks features are off")
        else:
            logger.warning("asks: %s failed (%s %s)", what, type(exc).__name__, getattr(exc, "code", ""))
        return default


def reset() -> None:
    """Forget that the tables were missing (tests)."""
    global _missing_until
    _missing_until = 0.0


def _sb():
    return config.get_supabase()


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def is_active(ask: dict, now: datetime) -> bool:
    """Live: not ended and not expired."""
    expires = _parse(ask.get("expires_at"))
    return ask.get("ended_at") is None and expires is not None and expires > now


def ended_at(ask: dict) -> datetime | None:
    """When the ask stopped being live: the moment it was ended, else its expiry."""
    return _parse(ask.get("ended_at")) or _parse(ask.get("expires_at"))


# --- Publish and dismiss ------------------------------------------------------------------------

def record_publish(card_row: dict, ask_id: str, text: str, created_at: datetime, expires_at: datetime) -> bool:
    """Store the ask and end whatever ask the card had before ("replaced"). True when stored."""
    def run() -> bool:
        sb = _sb().table("asks")
        sb.insert({"id": ask_id, "card_id": card_row["id"], "owner_user_id": card_row.get("owner_user_id"),
                   "text": text, "created_at": _iso(created_at), "expires_at": _iso(expires_at)}).execute()
        _sb().table("asks").update({"ended_at": _iso(created_at), "end_reason": "replaced"}) \
            .eq("card_id", card_row["id"]).is_("ended_at", "null").neq("id", ask_id).execute()
        return True
    return bool(guarded("record_publish", run, False))


def record_dismiss(card_id: str, now: datetime) -> None:
    guarded("record_dismiss", lambda: _sb().table("asks").update({"ended_at": _iso(now), "end_reason": "dismissed"})
            .eq("card_id", card_id).is_("ended_at", "null").execute())


def _executor() -> ThreadPoolExecutor:
    global _pool
    with _state_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ask-route")
        return _pool


def schedule_routing(ask_id: str, card_row: dict, text: str) -> None:
    """Route the ask off the request path: search is slow and the publish must not wait for it."""
    _executor().submit(route_safely, ask_id, card_row, text)


# --- Routing ------------------------------------------------------------------------------------

def select_routes(results: list[dict], *, asker_handle: str, excluded: set[str],
                  limit: int = ASK_ROUTE_MAX, min_score: float = ASK_ROUTE_MIN_SCORE) -> list[dict]:
    """Who to route an ask to, from people-search results: [{"card_id", "handle", "score"}], best
    first. Pure: nothing here reads a database. `excluded` is lower-cased handles."""
    own = (asker_handle or "").lower()
    picked: dict[str, dict] = {}
    for r in results:
        handle = (r.get("handle") or "").lower()
        card_id = r.get("agent_id") or ""
        score = float(r.get("match_score") or 0.0)
        if not handle or not card_id or handle == own or handle in excluded or score < min_score:
            continue
        if card_id not in picked or score > picked[card_id]["score"]:
            picked[card_id] = {"card_id": card_id, "handle": r["handle"], "score": score}
    return sorted(picked.values(), key=lambda p: (-p["score"], p["handle"].lower()))[:limit]


def _excluded_handles(card_row: dict, candidate_ids: list[str]) -> set[str]:
    """Handles never routed to: blocked, declined, revoked or hidden by the asker, and people who
    hid the asker. Raises when it cannot find out, so a failure means no routing, never routing to
    someone who should have been left out."""
    from services import feed, match_prefs, network

    user_id = card_row.get("owner_user_id")
    excluded: set[str] = set()
    if user_id:
        hidden = list(match_prefs.get(user_id).get("hide_person") or [])
        _, blocked = feed.connection_maps(network.get_inbox(user_id).get("connections", []), hidden)
        excluded |= blocked
    if candidate_ids and card_row.get("handle"):
        try:
            hiders = [r["user_id"] for r in (_sb().table("match_preferences").select("user_id")
                      .eq("kind", "hide_person").eq("value", card_row["handle"].lower()).execute().data or [])]
        except Exception as exc:  # noqa: BLE001 — the table only exists with network controls
            if not is_missing_table(exc):
                raise
            hiders = []
        if hiders:
            rows = (_sb().table("agent_profile_cards").select("handle,owner_user_id")
                    .in_("id", candidate_ids).in_("owner_user_id", hiders).execute().data or [])
            excluded |= {r["handle"].lower() for r in rows if r.get("handle")}
    return excluded


def route_ask(ask_id: str, card_row: dict, text: str) -> int:
    """Find the people an ask should reach and store them; how many were stored."""
    from services import search

    card = AgentProfileCard.model_validate(card_row.get("card") or {})
    card.handle = card_row.get("handle") or card.handle
    results = search.search_agents(q=text, limit=ASK_ROUTE_CANDIDATES, searcher=card, include_unclaimed=False)
    results = [r for r in results if r.get("match_score", 0) >= ASK_ROUTE_MIN_SCORE and r.get("agent_id") != card_row.get("id")]
    if not results:
        return 0
    excluded = _excluded_handles(card_row, [r["agent_id"] for r in results])
    routes = select_routes(results, asker_handle=card.handle, excluded=excluded)
    if not routes:
        return 0
    guarded("route_ask", lambda: _sb().table("ask_routes").upsert(
        [{"ask_id": ask_id, "helper_card_id": r["card_id"], "score": r["score"]} for r in routes],
        on_conflict="ask_id,helper_card_id", ignore_duplicates=True).execute())
    return len(routes)


def route_safely(ask_id: str, card_row: dict, text: str) -> int:
    if not available():
        return 0
    try:
        return route_ask(ask_id, card_row, text)
    except Exception as exc:  # noqa: BLE001 — a background task has no caller to tell
        logger.warning("asks: routing failed (%s %s)", type(exc).__name__, getattr(exc, "code", ""))
        return 0


def routed_ask_ids(card_id: str | None) -> set[str]:
    """Ask ids routed to this card: one query (the feed boosts them)."""
    if not card_id:
        return set()
    rows = guarded("routed_ask_ids", lambda: _sb().table("ask_routes").select("ask_id")
                   .eq("helper_card_id", card_id).execute().data, []) or []
    return {r["ask_id"] for r in rows}


# --- Offers -------------------------------------------------------------------------------------

def record_offer(ask_id: str, *, asker_card_id: str, helper_user_id: str, helper_card_id: str,
                 connection_id: str | None, channel: str, now: datetime) -> bool:
    """Record that someone offered help on a live ask (their feed reply went out). One offer per
    helper: a second reply is a no-op. True when a new offer was stored."""
    if channel not in ("dm", "request") or helper_card_id == asker_card_id:
        return False
    try:
        UUID(ask_id)
        connection = str(UUID(connection_id)) if connection_id else None
    except ValueError:
        return False

    def run() -> bool:
        rows = _sb().table("asks").select("id,card_id,ended_at,expires_at").eq("id", ask_id).limit(1).execute().data or []
        if not rows or rows[0]["card_id"] != asker_card_id or not is_active(rows[0], now):
            return False
        stored = _sb().table("ask_offers").upsert(
            {"ask_id": ask_id, "helper_user_id": helper_user_id, "helper_card_id": helper_card_id,
             "connection_id": connection, "channel": channel},
            on_conflict="ask_id,helper_user_id", ignore_duplicates=True).execute().data
        return bool(stored)
    created = bool(guarded("record_offer", run, False))
    if created:
        _emit("ask_offer", meta={"channel": channel})
    return created


def _emit(event: str, *, handle: str | None = None, meta: dict | None = None) -> None:
    from services import events

    try:
        events.emit(event, handle=handle, meta=meta)
    except Exception:  # noqa: BLE001 — an event must never fail the request
        logger.info("asks: could not record %s", event)


# --- Close-out ----------------------------------------------------------------------------------

def _person(card_id: str, row: dict | None) -> dict:
    card = (row or {}).get("card") or {}
    identity = card.get("identity") or {}
    return {"card_id": card_id, "handle": (row or {}).get("handle") or "", "name": identity.get("name") or "Zynd member",
            "headline": identity.get("headline") or "", "avatar_url": identity.get("avatar_url") or None}


def _cards_by_id(ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    rows = (_sb().table("agent_profile_cards").select("id,handle,card").in_("id", list(dict.fromkeys(ids)))
            .eq("status", "published").execute().data or [])
    return {r["id"]: r for r in rows}


def list_for_owner(card_row: dict, now: datetime) -> dict:
    """The owner's current ask plus asks that ended in the last ASK_CLOSEOUT_DAYS without an outcome,
    each with who offered. Three queries however many asks: asks, offers, the offerers' cards."""
    def run() -> list[dict]:
        since = _iso(now - timedelta(days=ASK_CLOSEOUT_DAYS + 8))     # an ask lives 7 days before it expires
        asks = (_sb().table("asks").select("*").eq("card_id", card_row["id"]).gte("created_at", since)
                .order("created_at", desc=True).limit(20).execute().data or [])
        shown = []
        for ask in asks:
            end = ended_at(ask)
            if is_active(ask, now):
                shown.append((ask, "active"))
            elif ask.get("outcome") is None and end and now - end <= timedelta(days=ASK_CLOSEOUT_DAYS):
                shown.append((ask, "ended"))
        if not shown:
            return []
        offers = (_sb().table("ask_offers").select("id,ask_id,helper_card_id,created_at,credited_at")
                  .in_("ask_id", [a["id"] for a, _ in shown]).order("created_at").execute().data or [])
        people = _cards_by_id([o["helper_card_id"] for o in offers])
        out = []
        for ask, status in shown:
            mine = [{**_person(o["helper_card_id"], people[o["helper_card_id"]]), "offered_at": o["created_at"],
                     "credited": o.get("credited_at") is not None}
                    for o in offers if o["ask_id"] == ask["id"] and o["helper_card_id"] in people]
            if ask.get("end_reason") == "replaced" and not mine:
                continue            # the owner posted a new ask and nobody had offered: nothing to close
            out.append({"id": ask["id"], "text": ask["text"], "status": status, "created_at": ask["created_at"],
                        "expires_at": ask["expires_at"], "ended_at": ask.get("ended_at"), "outcome": ask.get("outcome"),
                        "offers": mine})
        return out
    return {"asks": guarded("list_for_owner", run, []) or []}


def set_outcome(card_row: dict, email: str, ask_id: str, outcome: str, helper_card_ids: list[str],
                now: datetime) -> dict:
    """Record how an ask ended. Owner-only (another owner's ask is a 404). Credits go only to people
    who offered on this ask (422 otherwise), `helped` needs at least one, the other outcomes none.
    Repeating the same answer changes nothing; a different one is a 409."""
    if outcome not in OUTCOMES:
        raise HTTPException(422, "Unknown outcome")
    wanted = list(dict.fromkeys(helper_card_ids))
    if outcome == "helped" and not wanted:
        raise HTTPException(422, "Pick at least one person who helped")
    if outcome != "helped" and wanted:
        raise HTTPException(422, "Only a 'helped' outcome credits people")
    try:
        UUID(ask_id)
    except ValueError as exc:
        raise HTTPException(404, "Ask not found") from exc

    def load():
        rows = _sb().table("asks").select("*").eq("id", ask_id).eq("card_id", card_row["id"]).limit(1).execute().data or []
        if not rows:
            return None
        offers = _sb().table("ask_offers").select("id,helper_card_id,credited_at").eq("ask_id", ask_id).execute().data or []
        return rows[0], offers
    loaded = guarded("set_outcome", load, None)
    if not loaded:
        raise HTTPException(404, "Ask not found")
    ask, offers = loaded

    offered = {o["helper_card_id"] for o in offers}
    if not set(wanted) <= offered:
        raise HTTPException(422, "You can only credit people who offered help on this ask")
    if ask.get("outcome") is not None:
        credited = {o["helper_card_id"] for o in offers if o.get("credited_at")}
        if ask["outcome"] == outcome and credited == set(wanted):
            return {"ask_id": ask_id, "outcome": outcome, "credited": len(credited), "changed": False}
        raise HTTPException(409, "You already answered this")

    was_active = is_active(ask, now)
    closing = was_active and outcome in CLOSING_OUTCOMES

    def write():
        update = {"outcome": outcome, "outcome_at": _iso(now)}
        if closing:
            update |= {"ended_at": _iso(now), "end_reason": "solved"}
        won = _sb().table("asks").update(update).eq("id", ask_id).is_("outcome", "null").execute().data
        if not won:
            return False            # answered by another request a moment ago
        if wanted:
            _sb().table("ask_offers").update({"credited_at": _iso(now)}).eq("ask_id", ask_id) \
                .in_("helper_card_id", wanted).is_("credited_at", "null").execute()
        return True
    if not guarded("set_outcome_write", write, False):
        raise HTTPException(409, "You already answered this")

    cleared = False
    if closing:
        from services.beacons import save_beacon
        try:
            save_beacon(card_row["handle"], email, None)
            cleared = True
        except HTTPException:
            logger.info("asks: could not clear the beacon after a solved ask")
    if wanted:
        _revalidate_helpers(wanted)
    _emit("ask_outcome", meta={"outcome": outcome, "helpers": len(wanted), "offers": len(offered), "was_active": was_active})
    return {"ask_id": ask_id, "outcome": outcome, "credited": len(wanted), "changed": True, "beacon_cleared": cleared}


def _revalidate_helpers(card_ids: list[str]) -> None:
    """Their public cards now show (or no longer show) a credit: refresh the cached pages."""
    from services.zynd_memory import ping_revalidate

    rows = guarded("revalidate", lambda: _cards_by_id(card_ids), {}) or {}
    for row in rows.values():
        if row.get("handle"):
            try:
                ping_revalidate(row["handle"])
            except Exception:  # noqa: BLE001
                logger.info("asks: could not refresh a helper's page")


# --- Credits ------------------------------------------------------------------------------------

def _first_name(card: dict) -> str:
    name = (((card or {}).get("identity") or {}).get("name") or "").strip()
    return name.split()[0] if name else "someone"


def _short(text: str, limit: int = CREDIT_ASK_CHARS) -> str:
    from services.feed import preview

    return preview(text, limit)


def shape_credits(rows: list[dict], limit: int | None = CREDITS_SHOWN) -> dict:
    """{"count", "items"} from ask_offers rows with the ask and asker embedded. A credit shows only
    when it is credited, not hidden by the helper, and the asker's card is still published."""
    visible = []
    for r in rows:
        ask = r.get("ask") or {}
        asker = ask.get("card") or {}
        if not r.get("credited_at") or r.get("credit_hidden_at") or asker.get("status") != "published" or not asker.get("handle"):
            continue
        visible.append({"offer_id": r["id"], "credited_at": r["credited_at"], "asker_handle": asker["handle"],
                        "asker_name": _first_name(asker.get("card")), "ask": _short(ask.get("text") or "")})
    visible.sort(key=lambda c: c["credited_at"], reverse=True)
    people = {c["asker_handle"] for c in visible}
    return {"count": len(people), "items": visible[:limit] if limit else visible}


# The foreign-key hints are required: asks and cards are also related through the offers and routes
# tables, so PostgREST refuses an unhinted embed as ambiguous (checked against a real PostgREST).
_CREDIT_SELECT = ("id,credited_at,credit_hidden_at,credit_notified_at,"
                  "ask:asks!ask_offers_ask_id_fkey(id,text,card:agent_profile_cards!asks_card_id_fkey(handle,status,card))")


def _credit_rows(card_id: str) -> list[dict]:
    return (_sb().table("ask_offers").select(_CREDIT_SELECT).eq("helper_card_id", card_id)
            .not_.is_("credited_at", "null").execute().data or [])


def credits_for_card(card_id: str | None) -> dict:
    """What a helper's public card shows: {"count", "items": [{asker_handle, asker_name, ask}]}.
    One query by helper card (the offers index), the ask and asker embedded. Offer ids stay private."""
    if not card_id:
        return {"count": 0, "items": []}
    rows = guarded("credits_for_card", lambda: _credit_rows(card_id), []) or []
    shaped = shape_credits(rows)
    return {"count": shaped["count"], "items": [{k: v for k, v in c.items() if k not in ("offer_id", "credited_at")}
                                                for c in shaped["items"]]}


def credits_for_owner(card_id: str) -> dict:
    """The owner's own view of their credits, with offer ids so they can hide one."""
    rows = guarded("credits_for_owner", lambda: _credit_rows(card_id), []) or []
    return {"credits": shape_credits(rows, limit=None)["items"]}


def hide_credit(card_row: dict, offer_id: str, now: datetime) -> dict:
    """The helper hides a credit on their card. Owner-only: an offer that is not theirs (or not
    credited) is a 404, exactly like one that does not exist."""
    try:
        UUID(offer_id)
    except ValueError as exc:
        raise HTTPException(404, "Credit not found") from exc

    def run():
        rows = (_sb().table("ask_offers").select("id,credit_hidden_at").eq("id", offer_id)
                .eq("helper_card_id", card_row["id"]).not_.is_("credited_at", "null").limit(1).execute().data or [])
        if not rows:
            return None
        if rows[0].get("credit_hidden_at") is None:
            _sb().table("ask_offers").update({"credit_hidden_at": _iso(now)}).eq("id", offer_id).execute()
        return True
    if not guarded("hide_credit", run, None):
        raise HTTPException(404, "Credit not found")
    try:
        from services.zynd_memory import ping_revalidate
        ping_revalidate(card_row["handle"])
    except Exception:  # noqa: BLE001
        logger.info("asks: could not refresh the card after hiding a credit")
    return {"hidden": True}


# --- Digest -------------------------------------------------------------------------------------

def digest_items(card_row: dict, blocked: set[str], now: datetime) -> dict:
    """What the morning digest may say about asks for this owner, and the rows to mark afterwards:
    {"routed": [...], "prompts": [...], "credits": [...], "marks": {...}}. Best effort; empty when the
    tables are missing. `blocked` is the owner's blocked / hidden / declined handles (lower case)."""
    empty = {"routed": [], "prompts": [], "credits": [], "marks": {"routes": [], "prompts": [], "credits": []}}
    card_id = card_row.get("id")
    if not card_id:
        return empty

    def run() -> dict:
        out = {"routed": [], "prompts": [], "credits": [], "marks": {"routes": [], "prompts": [], "credits": []}}
        routes = (_sb().table("ask_routes").select("ask_id").eq("helper_card_id", card_id)
                  .is_("digest_sent_at", "null").order("created_at", desc=True).limit(20).execute().data or [])
        ids = [r["ask_id"] for r in routes]
        if ids:
            asks = _sb().table("asks").select("id,card_id,text,ended_at,expires_at").in_("id", ids).execute().data or []
            live = [a for a in asks if is_active(a, now)]
            askers = _cards_by_id([a["card_id"] for a in live])
            for ask in sorted(live, key=lambda a: ids.index(a["id"])):
                asker = askers.get(ask["card_id"])
                if not asker or (asker.get("handle") or "").lower() in blocked:
                    continue
                if len(out["routed"]) < ASKS_PER_DIGEST:
                    out["routed"].append({"ask_id": ask["id"], "text": ask["text"], "asker_handle": asker["handle"],
                                          "asker_name": _first_name(asker.get("card"))})
                    out["marks"]["routes"].append(ask["id"])
        since = _iso(now - timedelta(days=ASK_CLOSEOUT_DAYS + 8))
        mine = (_sb().table("asks").select("id,text,ended_at,expires_at,end_reason,outcome,outcome_prompted_at")
                .eq("card_id", card_id).gte("created_at", since).order("created_at", desc=True).limit(20).execute().data or [])
        for ask in mine:
            end = ended_at(ask)
            if (ask.get("outcome") is None and ask.get("outcome_prompted_at") is None and not is_active(ask, now)
                    and ask.get("end_reason") != "replaced" and end and now - end <= timedelta(days=ASK_CLOSEOUT_DAYS)):
                out["prompts"].append({"ask_id": ask["id"], "text": ask["text"]})
                out["marks"]["prompts"].append(ask["id"])
                break               # one line a day is enough
        pending = [r for r in _credit_rows(card_id) if r.get("credit_notified_at") is None and not r.get("credit_hidden_at")]
        for credit in shape_credits(pending, limit=CREDITS_IN_DIGEST)["items"]:
            out["credits"].append({"asker_name": credit["asker_name"], "asker_handle": credit["asker_handle"], "ask": credit["ask"]})
            out["marks"]["credits"].append(credit["offer_id"])
        return out
    return guarded("digest_items", run, empty) or empty


def mark_digest_sent(card_row: dict, marks: dict, now: datetime) -> None:
    """After the email went out: what it said is not said again."""
    card_id = card_row.get("id")
    stamp = _iso(now)
    if marks.get("routes"):
        guarded("mark_routes", lambda: _sb().table("ask_routes").update({"digest_sent_at": stamp})
                .eq("helper_card_id", card_id).in_("ask_id", marks["routes"]).execute())
    if marks.get("prompts"):
        guarded("mark_prompts", lambda: _sb().table("asks").update({"outcome_prompted_at": stamp})
                .eq("card_id", card_id).in_("id", marks["prompts"]).execute())
    if marks.get("credits"):
        guarded("mark_credits", lambda: _sb().table("ask_offers").update({"credit_notified_at": stamp})
                .eq("helper_card_id", card_id).in_("id", marks["credits"]).execute())
