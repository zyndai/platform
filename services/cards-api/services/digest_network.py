"""A4 — what the weekly digest says about your network.

Three things beyond activity counts:
  - mutual matches: Cards that want to meet someone like you while you want to meet someone like
    them (two-way, from connect_with and approved is_seeking facts), not yet connected
  - connection updates: what the people you are connected to approved onto their Cards this week
    ("Ada is now looking for investment")
  - saved-search hits: the new matches your saved searches found

Pure over card data already loaded by the notification run, so building it adds no queries per owner
beyond one connections lookup. Behind FEATURE_NETWORK_CONTROLS for the data it reads.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from models.card import AgentProfileCard
from services.card_view import _parse_ts, fact_object, fact_predicate, live_facts
from services.connection_brief import _label
from services.two_way import kinds_of, two_way_match, wanted_kinds

MAX_EACH = 3
_CHANGE_PREDICATES = ("is_building", "is_working_on", "is_seeking", "open_to", "is_affiliated_with", "has_expertise_in")


def _card(row: dict) -> AgentProfileCard | None:
    try:
        card = AgentProfileCard.model_validate(row.get("card") or {})
    except Exception:  # noqa: BLE001
        return None
    card.handle = row.get("handle") or card.handle
    return card


def mutual_matches(me: AgentProfileCard, rows: list[dict], exclude_handles: set[str]) -> list[dict]:
    my_kinds, my_wants = kinds_of(me), wanted_kinds(me)
    if not my_kinds or not my_wants:
        return []
    out = []
    for row in rows:
        if not (row.get("owner_email") or "").strip() or row.get("handle") in exclude_handles or row.get("handle") == me.handle:
            continue
        other = _card(row)
        if other is None:
            continue
        fits_me = two_way_match(my_kinds, other)          # they want someone like me
        if fits_me and my_wants & kinds_of(other):        # and I want someone like them
            out.append({"handle": other.handle, "name": other.identity.name, "headline": other.identity.headline,
                        "wants": fits_me[:2]})
        if len(out) >= MAX_EACH:
            break
    return out


def connection_updates(partners: list[AgentProfileCard], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=7)
    out = []
    for card in partners:
        for fact in live_facts(card.zynd_memory, now):
            approved = _parse_ts(fact.get("approved_at"))
            if fact_predicate(fact) in _CHANGE_PREDICATES and approved and approved >= since:
                out.append({"handle": card.handle, "name": card.identity.name or card.handle,
                            "change": _label(fact_predicate(fact), fact_object(fact)), "approved_at": approved.isoformat()})
    out.sort(key=lambda u: u["approved_at"], reverse=True)
    return out[:MAX_EACH * 2]


def section(mutual: list[dict], updates: list[dict], search_hits: list[str]) -> dict | None:
    if not (mutual or updates or search_hits):
        return None
    return {"mutual_matches": mutual, "connection_updates": updates, "saved_search_hits": search_hits[:MAX_EACH]}


def lines(network: dict | None) -> list[str]:
    """Plain-text lines for the weekly email."""
    if not network:
        return []
    out = ["", "Your network this week"]
    for m in network["mutual_matches"]:
        out.append(f"- {m['name'] or m['handle']} wants to meet people like you ({', '.join(m['wants'])})")
    for u in network["connection_updates"]:
        out.append(f"- {u['name']}: {u['change']}")
    for hit in network["saved_search_hits"]:
        out.append(f"- {hit}")
    return out
