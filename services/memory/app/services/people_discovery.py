"""External sources for find_people: published Cards and QuickEnrich.

Cards covers claimed and unclaimed public profiles. QuickEnrich is the free
contact-finder (LinkedIn URL + has_email/has_phone flags, never the contact
values). Either source failing leaves the others intact.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.services.people_query import (
    COUNTRIES, ROLE_COMPANY_WORDS, ROLE_STRONG_TITLES, TargetQuery, parse_target_heuristic, title_filters,
)

logger = logging.getLogger(__name__)

_HANDLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_STOP = frozenset({
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at", "who",
    "with", "that", "this", "from", "into", "by", "me", "my", "find", "people",
    "person", "someone", "looking", "want", "need", "like",
})


def _public_text(value: object, limit: int = 200) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"https?://\S+", "", value).strip()
    return text[:limit]


def _public_url(value: object) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 33 for c in value):
        return ""
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not host:
        return ""
    if host in ("localhost", "127.0.0.1") or host.endswith((".localhost", ".local", ".internal")):
        return ""
    if "linkedin.com" not in host and not host.endswith("zynd.ai"):
        return ""
    return value


def _linkedin_url(value: object) -> str:
    url = _public_url(value)
    return url if "linkedin.com" in url.lower() else ""


def card_url(handle: str) -> str:
    """Public page of a Card, built from the handle (never trusted from upstream)."""
    return f"{settings.cards_site_base_url.rstrip('/')}/p/{handle}" if _HANDLE.fullmatch(handle or "") else ""


def _card_url(handle: str, upstream: object) -> str:
    return card_url(handle) or _public_url(upstream)


_GENERIC_TOPIC_WORDS = frozenset({
    "tool", "tools", "platform", "platforms", "software", "company", "companies", "product",
    "products", "service", "services", "app", "apps", "system", "systems", "technology", "tech",
})


_SHORT_SIGNALS = frozenset({"ai", "ml", "vr", "ar", "ux", "ui", "it", "b2b", "b2c"})

# bio_li matches whole words and phrases of the company's About text: a bare "seed" found "SEED
# Healthcare", "seed stage" finds funds (checked against the live API, 2026-10-26).
_STAGE_PHRASES: dict[str, tuple[str, ...]] = {
    "seed": ("seed stage", "seed fund"),
    "pre-seed": ("pre-seed", "pre seed"), "preseed": ("pre-seed", "pre seed"), "pre seed": ("pre-seed", "pre seed"),
}


def company_phrases(query: TargetQuery, limit: int = 3) -> list[str]:
    """What the person's company's About text would say, kept as whole phrases ("developer tools",
    not "developer" and "tools"). A one- or two-letter word is dropped only when the phrase has a
    longer word and it is not a known signal like "AI". Investors also get their stage ("seed")
    and, with no topic at all, "venture" and "capital" so a fund is the likely match."""
    phrases: list[str] = []
    for topic in query.topics:
        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9+#.-]*", topic)
        if not words or all(w.lower() in _GENERIC_TOPIC_WORDS for w in words):
            continue
        longest = max(len(w) for w in words)
        kept = [w for w in words if len(w) > 2 or w.lower() in _SHORT_SIGNALS or longest <= 2]
        phrase = " ".join(kept)
        if phrase and phrase.lower() not in (p.lower() for p in phrases):
            phrases.append(phrase)
    phrases = phrases[:limit]
    if query.role == "investor":
        if query.stage:
            phrases[:0] = _STAGE_PHRASES.get(query.stage, (query.stage,))
        if not query.topics:
            phrases += ["venture", "capital"]
    return phrases


def quickenrich_body(query: TargetQuery, limit: int) -> dict | None:
    """Map a parsed target onto QuickEnrich contact-finder filters, or None when there is
    nothing specific enough to search with.

    title / country_code / locality describe the PERSON. bio_li is the company's LinkedIn
    About text, so it only gets topic keywords when the target is described through their
    company (an investor, a founder), never for "a Rust engineer".
    """
    body: dict = {"page": 1, "per_page": max(1, min(limit, 10))}
    keywords = company_phrases(query) if query.company_hint else []
    include, exclude = title_filters(query)
    if not keywords and query.role in ROLE_STRONG_TITLES:
        # with nothing about the company, "Principal" or "Managing Partner" returns consultancies
        include = [t for t in include if t in ROLE_STRONG_TITLES[query.role]]
    if include:
        body["title"] = {"include": include, "exclude": exclude}
    if keywords:
        body["bio_li"] = {"include": keywords, "exclude": []}
    if "title" not in body and "bio_li" not in body:
        return None   # a location alone would return arbitrary people
    if query.country_code:
        body["country_code"] = {"include": [query.country_code], "exclude": []}
    # country_code is the company's country (people in Los Altos come back for IN); locality is where
    # the person is, and matches a country name as a word of "Bengaluru, Karnataka, India".
    place = query.locality or ("" if query.country_code in _LOCALITY_OMITS_COUNTRY
                               else _COUNTRY_NAMES.get(query.country_code, ""))
    if place:
        body["locality"] = {"include": [place], "exclude": []}
    return body


def _na(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.upper() == "N/A" else text


def _age_phrase(days: object) -> str:
    """" (this week)" style hint of how current an approved fact is; "" when unknown."""
    if not isinstance(days, int) or days < 0:
        return ""
    if days <= 7:
        return " (this week)"
    if days <= 30:
        return f" ({days // 7} weeks ago)"
    return f" ({days // 30} months ago)"


RAW_WHY_LIMIT = 8   # Cards lists what was loosened last, after any approved facts: do not cut it off


def _why(reasons: object) -> list[str]:
    """Cards' match_reasons are strings or {"type": "memory", "text": ...}; show both as text."""
    out: list[str] = []
    for reason in reasons if isinstance(reasons, list) else []:
        if isinstance(reason, str):
            text = reason
        elif isinstance(reason, dict) and isinstance(reason.get("text"), str):
            text = f"Approved fact: {reason['text']}{_age_phrase(reason.get('age_days'))}"
        else:
            continue
        text = _public_text(text, 120)
        if text and text not in out:
            out.append(text)
    return out[:RAW_WHY_LIMIT]


# Filters a caller (the public MCP) may pass through to Cards unchanged. role, location and skills
# are PINNED: the caller asked for exactly those, so they are strict and nothing is loosened.
PINNED_PARAMS = ("role", "location", "skills")
PASSTHROUGH_PARAMS = frozenset({*PINNED_PARAMS, "industry", "availability", "experience_min"})


def cards_search_params(
    target: str, limit: int, query: TargetQuery, as_handle: str = "", less_like: list[str] | None = None,
    *, include_unclaimed: bool = True, extra: dict | None = None, search_id: str = "", via: str = "",
) -> dict:
    """/v1/agents/search params: the free text plus the parsed filters Cards can score on, and
    the searcher's own handle so people who want to meet someone like them rank higher.

    `extra` are filters the caller gave explicitly. When any of role, location or skills is among
    them they are the only role/location/skills sent and nothing is relaxed (as a UI filter is
    strict); the parse then only contributes topics."""
    extra = {k: v for k, v in (extra or {}).items() if k in PASSTHROUGH_PARAMS and v not in (None, "")}
    pinned = any(k in extra for k in PINNED_PARAMS)
    params: dict = {"q": (target or "").strip(), "limit": limit,
                    "include_unclaimed": "true" if include_unclaimed else "false"}
    if as_handle:
        params["as_handle"] = as_handle
    if less_like:
        params["less_like"] = ",".join(h for h in less_like if _HANDLE.fullmatch(h))[:700]
    if not pinned:
        if query.role:
            params["role"] = query.role_noun
        if query.locality or query.location:
            params["location"] = query.locality or query.location
    # Topics are guesses about what the person works on: they raise a score, never filter.
    # Only a skill the user explicitly asked for ("knows Rust") is a requirement, and when
    # the filters leave too few people Cards loosens them instead of returning nothing.
    if query.topics:
        params["topics"] = ",".join(query.topics)[:200]
    if query.required_skills and not pinned:
        params["skills"] = ",".join(query.required_skills)[:200]
    params.update(extra)
    if not pinned:
        params["relax"] = "true"
    if search_id:       # lets Cards' funnel tie a later connection to this search; never the query
        params["search_id"] = search_id
    if via:
        params["via"] = via
    return params


CARDS_TIMEOUT_SECONDS = 8.0
CARDS_SLOW_WARNING = ("cards_slow: Cards answered slowly, so only exact matches are shown; "
                      "looser matches were skipped")


async def _cards_get(url: str, params: dict) -> object:
    async with httpx.AsyncClient(timeout=httpx.Timeout(CARDS_TIMEOUT_SECONDS)) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def search_cards(
    target: str, limit: int, *, query: TargetQuery | None = None, as_handle: str = "",
    less_like: list[str] | None = None, include_unclaimed: bool = True, extra: dict | None = None,
    search_id: str = "", via: str = "",
) -> tuple[list[dict], str | None]:
    """Claimed and unclaimed published cards. Unclaimed rows carry no contact fields."""
    q = (target or "").strip()
    if not q or not settings.cards_api_base_url:
        return [], None
    query = query or parse_target_heuristic(q)
    url = f"{settings.cards_api_base_url.rstrip('/')}/v1/agents/search"
    params = cards_search_params(
        q, limit, query, as_handle, less_like, include_unclaimed=include_unclaimed, extra=extra,
        search_id=search_id, via=via)
    slow = False
    try:
        try:
            payload = await _cards_get(url, params)
        except httpx.TimeoutException as exc:
            if params.get("relax") != "true":
                raise
            # A relaxed search is up to four passes in Cards and can outlast the timeout when Cards
            # is busy; its first pass (the exact matches) alone is quick, and better than nothing.
            logger.warning("find_people cards search timed out (%s); retrying without relaxing", type(exc).__name__)
            payload = await _cards_get(url, {k: v for k, v in params.items() if k != "relax"})
            slow = True
    except Exception as exc:
        logger.warning("find_people cards search failed: %s %s", type(exc).__name__, exc)
        return [], "cards_unavailable"
    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return [], "cards_unavailable"

    return shape_cards(rows, limit), CARDS_SLOW_WARNING if slow else None


async def lookup_cards(
    name: str, limit: int, include_unclaimed: bool = True, search_id: str = "", via: str = "",
) -> tuple[list[dict], str | None]:
    """Published Cards whose name or handle matches, exact full name first. For "find Chandan",
    where meaning-based search has nothing to rank by."""
    name = (name or "").strip()
    if len(name) < 2 or not settings.cards_api_base_url:
        return [], None
    url = f"{settings.cards_api_base_url.rstrip('/')}/v1/agents/lookup"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(CARDS_TIMEOUT_SECONDS)) as client:
            params = {"name": name[:100], "limit": max(1, min(limit, 10)),
                      "include_unclaimed": "true" if include_unclaimed else "false"}
            if search_id:
                params["search_id"] = search_id
            if via:
                params["via"] = via
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        logger.warning("find_people cards lookup failed: %s %s", type(exc).__name__, exc)
        return [], "cards_unavailable"
    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return [], "cards_unavailable"
    return shape_cards(rows, limit), None


def shape_cards(rows: list, limit: int) -> list[dict]:
    """Public, sanitized view of Cards-API search results (also used for group-scoped search)."""
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        handle = row.get("handle")
        if not isinstance(handle, str) or not _HANDLE.fullmatch(handle) or handle.lower() in seen:
            continue
        seen.add(handle.lower())
        claimed = row.get("claimed") is True
        item = {
            "source": "zynd_card",
            "claimed": claimed,
            "handle": handle,
            "name": _public_text(row.get("name")),
            "headline": _public_text(row.get("headline")),
            "location": _public_text(row.get("location")),
            "skills": [
                _public_text(skill, 80) for skill in row.get("skills") or [] if isinstance(skill, str)
            ][:8],
            "match_score": row.get("match_score") if isinstance(row.get("match_score"), (int, float)) else None,
            "why": _why(row.get("match_reasons")),
            "verified": [v for v in (row.get("verified") or []) if v in ("linkedin", "github", "work_email")],
            "linkedin_url": _linkedin_url(row.get("linkedin_url")),
            "url": _card_url(handle, row.get("url")),
            "connection_eligible": False,
            "industries": [_public_text(i, 80) for i in row.get("industries") or [] if isinstance(i, str)][:5],
            "availability": _public_text(row.get("availability"), 40),
            "fresh_as_of": row.get("fresh_as_of") if isinstance(row.get("fresh_as_of"), str) else None,
        }
        if isinstance(row.get("relaxed"), list) and row["relaxed"]:
            item["relaxed"] = [str(r)[:20] for r in row["relaxed"] if isinstance(r, str)][:4]
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _qe_headers() -> dict:
    name = (settings.quickenrich_auth_header or "Authorization").strip()
    key = settings.quickenrich_api_key
    value = f"Bearer {key}" if name.lower() == "authorization" else key
    return {name: value, "Accept": "application/json"}


# US localities are often "Richmond, Virginia", with no country, so a country-word filter would miss them.
_LOCALITY_OMITS_COUNTRY = frozenset({"US"})
_COUNTRY_NAMES: dict[str, str] = {"US": "United States", "GB": "United Kingdom", "AE": "United Arab Emirates"}
for _name, _code in COUNTRIES.items():
    _COUNTRY_NAMES.setdefault(_code, _name.title())


def _linkedin_with_scheme(value: object) -> object:
    """Some providers return "linkedin.com/in/x" with no scheme, which _public_url rejects."""
    if isinstance(value, str):
        v = value.strip()
        if v and "://" not in v and re.match(r"(?:[a-z]{2,3}\.|www\.)?linkedin\.com/", v, re.I):
            return "https://" + v
    return value


def _qe_location(record: dict) -> str:
    """Where the person is. `locality` is theirs and already ends in the country ("Bengaluru,
    Karnataka, India"); `city` is an office address ("Vihar Road", "Palo Alto") and `country_code`
    the company's country, so they are only a fallback, and never appended to a locality."""
    locality = _public_text(_na(record.get("locality")), 120)
    if locality:
        return locality
    place = _public_text(_na(record.get("city")), 80)
    code = _na(record.get("country_code")).upper()
    country = _COUNTRY_NAMES.get(code, "") if code else ""
    if country and country.lower() in place.lower():
        country = ""
    return ", ".join(part for part in (place, country) if part)


def _shape_qe(records: list) -> list[dict]:
    """Sanitized QuickEnrich people: public fields and has_email/has_phone flags, never the values."""
    out: list[dict] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        name = " ".join(part for part in (_na(record.get("first_name")), _na(record.get("last_name"))) if part)
        link = _public_url(_linkedin_with_scheme(record.get("employee_linkedin")))
        key = link or name
        if not key or key in seen:
            continue
        seen.add(key)
        row = {
            "source": "quickenrich",
            "name": _public_text(name),
            "title": _public_text(_na(record.get("title"))),
            "company": _public_text(_na(record.get("company_name"))),
            "linkedin_url": link,
            "has_email": record.get("has_email") is True,
            "has_phone": record.get("has_phone") is True,
            "connection_eligible": False,
        }
        row["location"] = _qe_location(record)
        row["city"] = row["location"].split(",")[0].strip()
        row["country_code"] = _na(record.get("country_code")).upper()[:2]
        out.append(row)
    return out


def _fit_words(text: str, words: list[str]) -> bool:
    low = (text or "").lower()
    return any(w.lower() in low for w in words)


def has_excluded_title(row: dict, query: TargetQuery) -> bool:
    """True when the person's title holds a word that makes it a different job ("Investor
    Grievance Officer" for an investor search). The request already excludes these, but the
    provider's matching is unconfirmed (plan Q1), so callers that cannot show a wrong-role
    person drop them here too."""
    return _fit_words(row.get("title") or "", title_filters(query)[1])


LINKEDIN_PRIOR = 0.8      # as people_results.LINKEDIN_PRIOR: a LinkedIn match is a weaker signal than a Card
BROAD_TITLE = 0.6         # "Principal" at a company that does not look like the role's kind of organisation


def title_strength(row: dict, query: TargetQuery) -> float:
    """How surely the title is the asked role: 1 for a title that says it ("General Partner", or any
    include word for roles with no strong-title row), BROAD_TITLE for a broad one ("Principal",
    "Managing Partner") unless the company looks like a fund, 0 for an excluded word."""
    include, exclude = title_filters(query)
    title = row.get("title") or ""
    if not include:
        return 1.0
    if _fit_words(title, exclude):
        return 0.0
    strong = ROLE_STRONG_TITLES.get(query.role)
    if strong is None:
        return 1.0 if _fit_words(title, include) else BROAD_TITLE
    if _fit_words(title, list(strong)):
        return 1.0
    company_words = ROLE_COMPANY_WORDS.get(query.role, ())
    company = re.findall(r"[a-z0-9]+", (row.get("company") or "").lower())
    if any(tok == w.lower() or tok.endswith(w.lower()) for tok in company for w in company_words):   # "247VC"
        return 1.0
    return BROAD_TITLE if _fit_words(title, include) else 0.5


def rank_quickenrich(rows: list[dict], query: TargetQuery) -> list[dict]:
    """Give each LinkedIn person a score on the same scale as Cards and Zynd, before the shared fit
    (role, place) that people_results.rescore applies to every source: LINKEDIN_PRIOR x how surely
    their title is the asked role. Ties keep people with a profile URL first, then the provider's
    order."""
    scored = [({**row, "score": round(LINKEDIN_PRIOR * title_strength(row, query), 3)}, index)
              for index, row in enumerate(rows)]
    scored.sort(key=lambda pair: (-pair[0]["score"], not pair[0].get("linkedin_url"), pair[1]))
    return [row for row, _ in scored]


_redis = None
_CACHE_TTL_SECONDS = 7 * 24 * 3600     # an identical contact-finder request is reused for a week


def _cache_key(body: dict) -> str:
    return "qe:contact-finder:" + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


async def _cache_get(key: str) -> list[dict] | None:
    """Sanitized rows cached for an identical request, or None. Never raises: no Redis = no cache."""
    global _redis
    try:
        if _redis is None:
            import redis.asyncio as aioredis
            _redis = aioredis.from_url(settings.redis_url)
        raw = await _redis.get(key)
        rows = json.loads(raw) if raw else None
        return rows if isinstance(rows, list) else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("quickenrich cache read skipped: %s", exc)
        return None


async def _cache_set(key: str, rows: list[dict]) -> None:
    try:
        if _redis is not None:
            await _redis.set(key, json.dumps(rows), ex=_CACHE_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        logger.debug("quickenrich cache write skipped: %s", exc)


async def _quickenrich_rows(body: dict) -> tuple[list[dict], str | None]:
    """Run one contact-finder request. An identical request in the last week is answered from the
    cache; only the sanitized rows (flags, never values) are stored."""
    key = _cache_key(body)
    if (cached := await _cache_get(key)) is not None:
        return cached, None
    url = f"{settings.quickenrich_base_url.rstrip('/')}/api/employees/contact-finder"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.quickenrich_timeout)) as client:
            resp = await client.post(url, json=body, headers=_qe_headers())
            if resp.status_code >= 400:
                logger.warning("find_people quickenrich HTTP %s", resp.status_code)
                return [], "quickenrich_unavailable"
            payload = resp.json()
    except Exception as exc:
        logger.warning("find_people quickenrich failed: %s", exc)
        return [], "quickenrich_unavailable"

    records = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return [], "quickenrich_unavailable"
    rows = _shape_qe(records)
    await _cache_set(key, rows)
    return rows, None


async def search_quickenrich(
    target: str, limit: int, *, query: TargetQuery | None = None,
) -> tuple[list[dict], str | None]:
    """Free contact-finder. Returns LinkedIn URLs and contact flags, never email/phone.

    Every way this can return nothing carries a warning: not configured, a query too vague
    to search with, an HTTP error. An empty list with no warning means "searched, found none".
    """
    if not settings.quickenrich_base_url or not settings.quickenrich_api_key:
        return [], "quickenrich_not_configured"
    query = query or parse_target_heuristic(target)
    body = quickenrich_body(query, limit)
    if body is None:
        return [], "quickenrich_query_too_vague"
    rows, warning = await _quickenrich_rows(body)
    if warning:
        return [], warning
    return rank_quickenrich(rows, query)[:limit], None


def _name_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def name_matches(wanted: str, found: str) -> bool:
    """Every word of the name asked for is a word of the person's name, or the start of one (3+
    letters), so "chandan" finds "Chandan Kumar" and "Chandan K" does too."""
    have = _name_words(found)
    want = _name_words(wanted)
    return bool(want) and all(
        any(h == w or (len(w) >= 3 and h.startswith(w)) for h in have) for w in want)


NAME_SEARCH_PAGES = 2


async def search_quickenrich_by_name(name: str, company: str, limit: int) -> tuple[list[dict], str | None]:
    """A named person at a named company. The contact-finder cannot search by name, so list the
    company's people and keep the ones whose name matches."""
    if not settings.quickenrich_base_url or not settings.quickenrich_api_key:
        return [], "quickenrich_not_configured"
    found: list[dict] = []
    for page in range(1, NAME_SEARCH_PAGES + 1):
        body = {"page": page, "per_page": 10, "company_name": {"include": [company], "exclude": []}}
        rows, warning = await _quickenrich_rows(body)
        if warning:
            return found[:limit], warning if not found else None
        found += [r for r in rows if name_matches(name, r.get("name") or "")]
        if len(rows) < 10:
            break
    return found[:limit], None
