"""find_people: one search, one list of people.

Cards is the people index. The search asks Cards (free text plus the parsed role, place and
topics) and, as an extra signal, Zynd members whose profile is close to the target; those
are resolved to their Cards and merged, so a person appears once whichever way they were
found. Only when too few strong matches came back does it reach outside for LinkedIn
people. Every source that fails or is not configured says so in `warnings`.

    find_people("seed-stage investor who backs AI dev tools in India")
    find_people("like_me")        # people close to the caller's own profile
    find_people("Chandan from Zynd")   # a name: looked up as a name
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import asyncpg

from app.config import settings
from app.services import card_directory, people_discovery, people_results
from app.services.export import active_context
from app.services.matching import match_users, search_by_query
from app.services.people_query import (
    Intent, TargetQuery, detect_intent, parse_target, parse_target_heuristic)
from app.tools import cards_network

logger = logging.getLogger("zynd.find_people")

SOURCES = frozenset({"cards", "zynd", "quickenrich"})


@dataclass(frozen=True)
class Searcher:
    """Who is searching. A signed-in owner has a uid, a Card, match controls and (when invites are
    on) invitations to offer; the public MCP has none of these, so with no uid the search never
    reads another person's data on the caller's behalf: no Zynd source, no preferences, no invites."""
    uid: str | None = None
    own_handle: str | None = None
    prefs: dict = field(default_factory=dict)
    include_unclaimed: bool = True      # unclaimed Cards carry no contact fields, and owners see them
    invites: bool = False


def anonymous(include_unclaimed: bool = False) -> Searcher:
    return Searcher(include_unclaimed=include_unclaimed)


async def searcher_for(pool: asyncpg.Pool, uid: str) -> Searcher:
    """The signed-in owner's searcher: their Card (never a result, and what two-way matching reads)
    and their match controls, each fetched once per search."""
    return Searcher(uid=uid, own_handle=await _own_handle(pool, uid), prefs=await _preferences(pool, uid),
                    invites=bool(settings.feature_invite_to_claim))
_PROFILE_PREDICATES = ("is_building", "is_creating", "is_working_on", "has_expertise_in", "has_skill", "is_learning")
_PROFILE_TOPICS = 4
# Least similarity for a person found ONLY through their Zynd profile: per-fact matching, and the
# blurrier averaged profile vector. Starting values, to tune with the golden set.
ZYND_MIN_SCORE_FACT = 0.35
ZYND_MIN_SCORE_AVG = 0.45


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
            person = people_results.person_from_zynd(row, card, people_discovery.card_url(card["handle"]))
            if not like_me:
                per_fact = bool(row.get("matched_on"))
                floor = ZYND_MIN_SCORE_FACT if per_fact else ZYND_MIN_SCORE_AVG
                # Kept only if Cards also found them (see the filter in find). No generic reason
                # either: "Matches their Zynd profile" says nothing the person's presence does not.
                person["_weak"] = (row.get("similarity") or 0.0) < floor
                if not per_fact:
                    person["why"] = []
            people.append(person)
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
    # Topics are soft and only an explicit skill is required, as in a Cards search.
    result = await cards_network.group_search(
        pool, uid, group_id, text, query.role_noun, query.locality or query.location,
        ",".join(query.required_skills)[:200], limit, topics=",".join(query.topics)[:200], relax=True)
    if not result.get("ok"):
        return [], "group_unavailable: " + str(result.get("error") or "not a member of that group")[:120]
    return [
        {**row, "claimed": True, "why": people_discovery._why(row.get("match_reasons")),
         "linkedin_url": people_discovery._linkedin_url(row.get("linkedin_url")),
         "url": people_discovery.card_url(row.get("handle") or ""),
         "match_score": row.get("match_score")}
        for row in people_discovery.shape_cards(result.get("results") or [], limit * 2)
    ], None


def _parsed(query: TargetQuery) -> dict:
    return {k: v for k, v in query.as_dict().items() if v and k not in ("raw", "titles")}


async def _find_by_name(
    pool: asyncpg.Pool, searcher: Searcher, intent: Intent, *, limit: int, wanted: set[str], warnings: list[str],
) -> tuple[list[dict], set[str]]:
    """Look one person up by name: Cards' own name search, and when a company was given the
    company's LinkedIn people filtered by name (the contact-finder cannot search by name).
    Returns (people, sources searched). Empty people = nobody by that name."""
    coros: dict[str, object] = {}
    if "cards" in wanted:
        coros["cards"] = people_discovery.lookup_cards(
            intent.name, limit, include_unclaimed=searcher.include_unclaimed)
    if intent.company and "quickenrich" in wanted:
        coros["quickenrich"] = people_discovery.search_quickenrich_by_name(intent.name, intent.company, limit)
    results = dict(zip(coros, await asyncio.gather(*coros.values(), return_exceptions=True)))
    people: list[dict] = []
    for name, outcome in results.items():
        if isinstance(outcome, BaseException):
            logger.warning("%s name lookup failed: %s", name, outcome)
            warnings.append(f"{name}_unavailable")
            continue
        rows, warning = outcome
        if warning:
            warnings.append(warning)
        if name == "cards":
            people.extend(people_results.person_from_card(r) for r in rows)
        else:
            people.extend(people_results.person_from_external(r, i) for i, r in enumerate(rows))
    people = people_results.apply_preferences(people_results.merge_people(people), searcher.prefs)
    if searcher.own_handle:
        people = [p for p in people if (p["handle"] or "").lower() != searcher.own_handle.lower()]
    for person in people:
        exact = (sorted(people_discovery._name_words(person["name"])) == sorted(people_discovery._name_words(intent.name))
                 or (person["handle"] or "").lower() == intent.name.lower())
        person["match_quality"] = "exact" if exact else "close"
    return people[:limit], set(results)


async def find(
    pool: asyncpg.Pool, uid: str, target: str, *, limit: int, wanted: set[str], explicit: set[str],
    group_id: str = "",
) -> dict:
    """A signed-in owner's search (the find_people tool)."""
    return await search(pool, await searcher_for(pool, uid), target, limit=limit, wanted=wanted,
                        explicit=explicit, group_id=group_id)


async def search(
    pool: asyncpg.Pool, searcher: Searcher, target: str, *, limit: int, wanted: set[str], explicit: set[str],
    group_id: str = "", extra_params: dict | None = None,
) -> dict:
    """The one people search, for whoever is asking. `extra_params` are Cards filters the parser
    has no field for (industry, availability, experience_min), passed through unchanged."""
    target = (target or "").strip()
    intent = detect_intent(target)
    like_me = intent.kind == "like_me"
    warnings: list[str] = []
    searched: set[str] = set()
    extra: dict = {}
    if searcher.uid is None:
        wanted = wanted - {"zynd"}      # a Zynd member match is relative to the caller's own profile

    if like_me:
        text = await _profile_text(pool, searcher.uid) if searcher.uid else ""
        if not text:
            why = ("save a few facts about yourself first" if searcher.uid
                   else "people like you needs a signed-in account")
            return {"target": target, "mode": "like_me", "parsed": {}, "people": [],
                    "sources": sorted(wanted), "searched": [],
                    "warnings": [f"no_profile_to_compare: {why}"]}
        query: TargetQuery = parse_target_heuristic(text)
    else:
        text = target

    if intent.kind == "name" and not group_id:
        people, name_searched = await _find_by_name(
            pool, searcher, intent, limit=limit, wanted=wanted, warnings=warnings)
        exact = any(p["match_quality"] == "exact" for p in people)
        if not intent.company and not exact:
            # Without a company there is nothing to search LinkedIn with: the assistant should ask.
            warnings.append("name_needs_company: ask which company they work at, then search again with it")
        if people:
            result = {
                "target": target, "mode": "target", "intent": "name",
                "parsed": {"name": intent.name, **({"company": intent.company} if intent.company else {})},
                "people": _with_invites(people, searcher),
                "sources": sorted(wanted), "searched": sorted(name_searched),
            }
            if len(people) > 1:
                result["note"] = (f"{len(people)} people match \"{intent.name}\": tell them apart by "
                                  "headline and location before connecting.")
            if warnings:
                result["warnings"] = list(dict.fromkeys(warnings))
            return result
        searched |= name_searched
        extra["note"] = f"Nobody named \"{intent.name}\" was found; showing the closest matches for the text."
        query = await parse_target(target)
    elif not like_me:
        query = await parse_target(target)
    extra["intent"] = "like_me" if like_me else "target"

    if group_id and searcher.uid:
        # Scoped to one group (an event, a community): its members' Cards only, no other source.
        found, warning = await _group_people(pool, searcher.uid, group_id, text, query, limit)
        people = people_results.apply_preferences(
            people_results.merge_people([people_results.person_from_card(r) for r in found]), searcher.prefs)
        result = {"target": target, "mode": "group", "group_id": group_id, "parsed": _parsed(query),
                  "people": people[:limit], "sources": ["group"], "searched": ["group"]}
        if warning:
            result["warnings"] = [warning]
        return result

    # Ask for more than `limit` from each source so merging and ranking have something to choose from.
    pool_size = min(limit * 2, 30)
    people, searched_now, early_qe = await _retrieve(
        pool, searcher, text, query, like_me, wanted, explicit, pool_size, limit, warnings, extra_params)
    searched |= searched_now
    people = _rank(people, query, searcher)
    people = await _fallback_quickenrich(
        people, text, query, early_qe, limit=limit, wanted=wanted, explicit=explicit, like_me=like_me,
        searcher=searcher, searched=searched, warnings=warnings)

    people = people[:limit]
    if not like_me:
        for person in people:
            person["why"] = people_results.specific_why(person, query)
    note = people_results.label_quality(people)
    if note and "note" not in extra and not like_me:
        extra["note"] = note
    people = _with_invites(people, searcher)
    result = {
        "target": target,
        "mode": "like_me" if like_me else "target",
        "parsed": {} if like_me else _parsed(query),
        "people": people,
        "sources": sorted(wanted),
        "searched": sorted(searched),
        **extra,
    }
    if like_me:
        result["compared_with"] = text
    if warnings:
        result["warnings"] = list(dict.fromkeys(warnings))
    return result


async def outside(query: TargetQuery, limit: int) -> tuple[list[dict], str | None]:
    """People outside Zynd for a service caller (Cards' suggestions): the pipeline's LinkedIn step,
    with no user. Wrong-role titles are dropped, the rest are ordered by the same fit as any
    search and carry a specific `why`, a `score` and a `match_quality` next to the provider's
    own fields. An empty list with no warning means "searched, found none"."""
    rows, warning = await people_discovery.search_quickenrich(
        query.raw, min(limit * 2, 10), query=query)        # room to drop wrong-role titles
    rows = [r for r in rows if not people_discovery.has_excluded_title(r, query)]
    people = people_results.rescore([people_results.person_from_external(r, i) for i, r in enumerate(rows)], query)
    ranked = sorted(zip(people, rows), key=lambda pair: -pair[0]["score"])   # stable: the provider's order breaks ties
    for person, _ in ranked:
        person["why"] = people_results.specific_why(person, query)
    people_results.label_quality([person for person, _ in ranked])
    return [{**row, "score": person["score"], "why": person["why"], "match_quality": person["match_quality"]}
            for person, row in ranked][:limit], warning


def _with_invites(people: list[dict], searcher: Searcher) -> list[dict]:
    """Invitations are signed for a user, so an anonymous search has none to offer."""
    return people_results.with_invites(people, searcher.uid, bool(searcher.uid) and searcher.invites)


async def _retrieve(
    pool: asyncpg.Pool, searcher: Searcher, text: str, query: TargetQuery, like_me: bool, wanted: set[str],
    explicit: set[str], pool_size: int, limit: int, warnings: list[str], extra_params: dict | None,
) -> tuple[list[dict], set[str], "asyncio.Future | None"]:
    """Call every wanted source at once. Returns (people, sources searched, the early LinkedIn
    search when one was started, for _fallback_quickenrich to await or cancel)."""
    coros: dict[str, object] = {}
    if "cards" in wanted:
        coros["cards"] = people_discovery.search_cards(
            text, pool_size, query=query, as_handle=searcher.own_handle or "",
            less_like=searcher.prefs.get("less_like_this"), include_unclaimed=searcher.include_unclaimed,
            **({"extra": extra_params} if extra_params else {}))
    if "zynd" in wanted and searcher.uid:
        coros["zynd"] = _zynd_people(pool, searcher.uid, text, like_me, pool_size, warnings, query)
    # A role described through their company is the case Cards most often comes up short on, so
    # LinkedIn starts now instead of after Cards and Zynd; the answer is dropped if not needed.
    # Only when the fallback may run at all: an anonymous caller must name it, it is a paid lookup.
    early_qe = None
    if ("quickenrich" in wanted and not like_me and query.role and query.company_hint
            and (searcher.uid is not None or "quickenrich" in explicit)):
        early_qe = asyncio.ensure_future(people_discovery.search_quickenrich(text, limit, query=query))
    try:
        results = dict(zip(coros, await asyncio.gather(*coros.values(), return_exceptions=True)))
    except BaseException:
        if early_qe:
            early_qe.cancel()
        raise

    people: list[dict] = []
    for name, outcome in results.items():
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
    return people, set(results), early_qe


def _rank(people: list[dict], query: TargetQuery, searcher: Searcher) -> list[dict]:
    """One re-rank for every source: fit, one entry per person, the searcher's match controls, the
    Zynd floor, and never the searcher's own Card."""
    people = people_results.rescore(people, query)
    people = people_results.apply_preferences(people_results.merge_people(people), searcher.prefs)
    # A Zynd hit below the floor stays only when Cards found the same person.
    people = [p for p in people if not (p.get("_weak") and p["sources"] == ["zynd"])]
    for person in people:
        person.pop("_weak", None)
    if searcher.own_handle:
        people = [p for p in people if (p["handle"] or "").lower() != searcher.own_handle.lower()]
    return people


async def _fallback_quickenrich(
    people: list[dict], text: str, query: TargetQuery, early_qe: "asyncio.Future | None", *, limit: int,
    wanted: set[str], explicit: set[str], like_me: bool, searcher: Searcher, searched: set[str],
    warnings: list[str],
) -> list[dict]:
    """LinkedIn is the fallback: when explicitly asked for, or (for a signed-in owner) when too few
    strong matches. An anonymous caller only ever gets it by naming it: it is a paid lookup."""
    automatic = searcher.uid is not None and people_results.strong_count(people) < limit
    if "quickenrich" in wanted and not like_me and ("quickenrich" in explicit or automatic):
        searched.add("quickenrich")
        if early_qe is not None:
            found, warning = await early_qe
        else:
            found, warning = await people_discovery.search_quickenrich(text, limit, query=query)
        if warning:
            warnings.append(warning)
        return people_results.merge_people(
            people + people_results.rescore(
                [people_results.person_from_external(r, i) for i, r in enumerate(found)], query))
    if early_qe is not None:
        early_qe.cancel()
    return people


async def _own_handle(pool: asyncpg.Pool, uid: str) -> str | None:
    cards = await card_directory.cards_for_users(pool, [uid])
    card = (cards or {}).get(uid)
    return card.get("handle") if card else None
