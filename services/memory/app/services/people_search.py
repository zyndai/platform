"""find_people: one search, one list of people.

Cards is the people index. The search asks Cards (free text plus the parsed role, place and
topics) and, as an extra signal, Zynd members whose profile is close to the target; those
are resolved to their Cards and merged, so a person appears once whichever way they were
found. Only when too few strong matches came back does it reach outside for LinkedIn
people. Every source that fails or is not configured says so in `warnings`.

    find_people("seed-stage investor who backs AI dev tools in India")
    find_people("like_me")        # people close to the caller's own profile
"""
from __future__ import annotations

import asyncio
import logging

import asyncpg

from app.config import settings
from app.services import card_directory, people_discovery, people_results
from app.services.export import active_context
from app.services.matching import match_users, search_by_query
from app.services.people_query import TargetQuery, parse_target, parse_target_heuristic

logger = logging.getLogger("zynd.find_people")

SOURCES = frozenset({"cards", "zynd", "quickenrich"})
LIKE_ME = frozenset({"like_me", "like me", "people like me", "similar to me"})
_PROFILE_PREDICATES = ("is_building", "is_creating", "is_working_on", "has_expertise_in", "has_skill", "is_learning")
_PROFILE_TOPICS = 4


def requested_sources(sources: str) -> tuple[set[str], set[str]]:
    """(sources to use, sources the caller named explicitly). "all" or nothing = every source."""
    asked = {part.strip().lower() for part in (sources or "").split(",") if part.strip()}
    named = asked & SOURCES
    if not asked or "all" in asked or not named:
        return set(SOURCES), named
    return named, named


async def _profile_text(pool: asyncpg.Pool, uid: str) -> str:
    """The caller's own profile as a short search text, for "people like me"."""
    facts = await active_context(pool, uid, 20)
    topics: list[str] = []
    for predicate in _PROFILE_PREDICATES:
        for fact in facts:
            name = (fact.get("object") or "").strip()
            if fact.get("predicate") == predicate and name and name.lower() not in (t.lower() for t in topics):
                topics.append(name)
    return ", ".join(topics[:_PROFILE_TOPICS])


async def _zynd_people(
    pool: asyncpg.Pool, uid: str, text: str, like_me: bool, limit: int, warnings: list[str],
) -> list[dict]:
    """Zynd members close to the target, as people identified by their Cards."""
    try:
        rows = await (match_users(pool, uid, "full_context", limit) if like_me
                      else search_by_query(pool, uid, text, limit=limit))
    except Exception as exc:  # noqa: BLE001 — one source failing must not sink the search
        logger.warning("zynd search failed: %s", exc)
        warnings.append("zynd_unavailable")
        return []
    rows = [r for r in rows if isinstance(r, dict) and r.get("user_id")]
    if not rows:
        return []
    cards = await card_directory.cards_for_users(pool, [r["user_id"] for r in rows])
    if cards is None:
        warnings.append("cards_unavailable")
        return []
    people = []
    for row in rows:
        card = cards.get(row["user_id"])
        if card and card.get("handle"):   # no published Card = nobody to connect to
            people.append(people_results.person_from_zynd(row, card, people_discovery.card_url(card["handle"])))
    return people


async def find(
    pool: asyncpg.Pool, uid: str, target: str, *, limit: int, wanted: set[str], explicit: set[str],
) -> dict:
    target = (target or "").strip()
    like_me = target.lower() in LIKE_ME
    warnings: list[str] = []
    searched: set[str] = set()

    if like_me:
        text = await _profile_text(pool, uid)
        if not text:
            return {"target": target, "mode": "like_me", "parsed": {}, "people": [],
                    "sources": sorted(wanted), "searched": [],
                    "warnings": ["no_profile_to_compare: save a few facts about yourself first"]}
        query: TargetQuery = parse_target_heuristic(text)
    else:
        text = target
        query = await parse_target(target)

    # Ask for more than `limit` from each source so merging and ranking have something to choose from.
    pool_size = min(limit * 2, 30)
    coros: dict[str, object] = {}
    if "cards" in wanted:
        coros["cards"] = people_discovery.search_cards(text, pool_size, query=query)
    if "zynd" in wanted:
        coros["zynd"] = _zynd_people(pool, uid, text, like_me, pool_size, warnings)
    results = dict(zip(coros, await asyncio.gather(*coros.values(), return_exceptions=True)))

    people: list[dict] = []
    for name, outcome in results.items():
        searched.add(name)
        if isinstance(outcome, BaseException):
            logger.warning("%s search failed: %s", name, outcome)
            warnings.append(f"{name}_unavailable")
        elif name == "cards":
            rows, warning = outcome
            people.extend(people_results.person_from_card(r) for r in rows)
            if warning:
                warnings.append(warning)
        else:
            people.extend(outcome)

    people = people_results.merge_people(people)
    own = await _own_handle(pool, uid) if people else None
    if own:
        people = [p for p in people if (p["handle"] or "").lower() != own.lower()]

    # LinkedIn is the fallback: only when explicitly asked for, or when too few strong matches.
    if "quickenrich" in wanted and not like_me and (
        "quickenrich" in explicit or people_results.strong_count(people) < limit
    ):
        searched.add("quickenrich")
        found, warning = await people_discovery.search_quickenrich(text, limit, query=query)
        if warning:
            warnings.append(warning)
        people = people_results.merge_people(
            people + [people_results.person_from_external(r, i) for i, r in enumerate(found)])

    result = {
        "target": target,
        "mode": "like_me" if like_me else "target",
        "parsed": {} if like_me else {k: v for k, v in query.as_dict().items() if v and k not in ("raw", "titles")},
        "people": people[:limit],
        "sources": sorted(wanted),
        "searched": sorted(searched),
    }
    if like_me:
        result["compared_with"] = text
    if warnings:
        result["warnings"] = list(dict.fromkeys(warnings))
    return result


async def _own_handle(pool: asyncpg.Pool, uid: str) -> str | None:
    cards = await card_directory.cards_for_users(pool, [uid])
    card = (cards or {}).get(uid)
    return card.get("handle") if card else None
