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
from app.tools import cards_network

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
    query: TargetQuery | None = None,
) -> list[dict]:
    """Zynd members close to the target, as people identified by their Cards."""
    try:
        rows = await (match_users(pool, uid, "full_context", limit) if like_me
                      else search_by_query(pool, uid, text, limit=limit, query=query))
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


async def _preferences(pool: asyncpg.Pool, uid: str) -> dict:
    """The searcher's match controls (A8). Never fatal: without them the search is just untuned."""
    try:
        result = await cards_network.preferences(pool, uid)
    except Exception as exc:  # noqa: BLE001
        logger.warning("match preferences unavailable: %s", exc)
        return {}
    prefs = result.get("preferences") if isinstance(result, dict) and result.get("ok") else None
    return prefs if isinstance(prefs, dict) else {}


async def _group_people(
    pool: asyncpg.Pool, uid: str, group_id: str, text: str, query: TargetQuery, limit: int,
) -> tuple[list[dict], str | None]:
    """A7: search only the Cards of one group's members. Cards enforces that the caller is a member."""
    result = await cards_network.group_search(
        pool, uid, group_id, text, query.role_noun, query.locality or query.location,
        ",".join(query.topics)[:200], limit)
    if not result.get("ok"):
        return [], "group_unavailable: " + str(result.get("error") or "not a member of that group")[:120]
    return [
        {**row, "claimed": True, "why": people_discovery._why(row.get("match_reasons")),
         "linkedin_url": people_discovery._linkedin_url(row.get("linkedin_url")),
         "url": people_discovery.card_url(row.get("handle") or ""),
         "match_score": row.get("match_score")}
        for row in people_discovery.shape_cards(result.get("results") or [], limit * 2)
    ], None


async def find(
    pool: asyncpg.Pool, uid: str, target: str, *, limit: int, wanted: set[str], explicit: set[str],
    group_id: str = "",
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

    prefs = await _preferences(pool, uid)
    if group_id:
        # Scoped to one group (an event, a community): its members' Cards only, no other source.
        found, warning = await _group_people(pool, uid, group_id, text, query, limit)
        people = people_results.apply_preferences(
            people_results.merge_people([people_results.person_from_card(r) for r in found]), prefs)
        result = {"target": target, "mode": "group", "group_id": group_id,
                  "parsed": {k: v for k, v in query.as_dict().items() if v and k not in ("raw", "titles")},
                  "people": people[:limit], "sources": ["group"], "searched": ["group"]}
        if warning:
            result["warnings"] = [warning]
        return result

    # Ask for more than `limit` from each source so merging and ranking have something to choose from.
    pool_size = min(limit * 2, 30)
    own = await _own_handle(pool, uid)       # the searcher's Card: never a result, and what two-way matching reads
    coros: dict[str, object] = {}
    if "cards" in wanted:
        coros["cards"] = people_discovery.search_cards(
            text, pool_size, query=query, as_handle=own or "", less_like=prefs.get("less_like_this"))
    if "zynd" in wanted:
        coros["zynd"] = _zynd_people(pool, uid, text, like_me, pool_size, warnings, query)
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

    people = people_results.apply_preferences(people_results.merge_people(people), prefs)
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

    people = people_results.with_invites(people[:limit], uid, settings.feature_invite_to_claim)
    result = {
        "target": target,
        "mode": "like_me" if like_me else "target",
        "parsed": {} if like_me else {k: v for k, v in query.as_dict().items() if v and k not in ("raw", "titles")},
        "people": people,
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
