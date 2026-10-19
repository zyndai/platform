"""External sources for find_people: published Cards and QuickEnrich.

Cards covers claimed and unclaimed public profiles. QuickEnrich is the free
contact-finder (LinkedIn URL + has_email/has_phone flags, never the contact
values). Either source failing leaves the others intact.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.services.people_query import TargetQuery, parse_target_heuristic

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


def company_keywords(query: TargetQuery, limit: int = 2) -> list[str]:
    """Words that would appear in the About text of the person's COMPANY, e.g. a fund that
    "backs AI dev tools". Topic words only, deduplicated, generic nouns dropped. Short words
    such as "AI" are kept: they are the signal, not noise."""
    words: list[str] = []
    for topic in query.topics:
        for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9+#.-]*", topic):
            if word.lower() in _GENERIC_TOPIC_WORDS or word.lower() in (w.lower() for w in words):
                continue
            words.append(word)
            if len(words) >= limit:
                return words
    return words


def quickenrich_body(query: TargetQuery, limit: int) -> dict | None:
    """Map a parsed target onto QuickEnrich contact-finder filters, or None when there is
    nothing specific enough to search with.

    title / country_code / locality describe the PERSON. bio_li is the company's LinkedIn
    About text, so it only gets topic keywords when the target is described through their
    company (an investor, a founder), never for "a Rust engineer".
    """
    body: dict = {"page": 1, "per_page": max(1, min(limit, 10))}
    keywords = company_keywords(query) if query.company_hint else []
    if query.titles:
        body["title"] = {"include": list(query.titles), "exclude": []}
    if keywords:
        body["bio_li"] = {"include": keywords, "exclude": []}
    if "title" not in body and "bio_li" not in body:
        return None   # a location alone would return arbitrary people
    if query.country_code:
        body["country_code"] = {"include": [query.country_code], "exclude": []}
    if query.locality:
        body["locality"] = {"include": [query.locality], "exclude": []}
    return body


def _na(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.upper() == "N/A" else text


def _why(reasons: object) -> list[str]:
    """Cards' match_reasons are strings or {"type": "memory", "text": ...}; show both as text."""
    out: list[str] = []
    for reason in reasons if isinstance(reasons, list) else []:
        if isinstance(reason, str):
            text = reason
        elif isinstance(reason, dict) and isinstance(reason.get("text"), str):
            text = f"Approved fact: {reason['text']}"
        else:
            continue
        text = _public_text(text, 120)
        if text and text not in out:
            out.append(text)
    return out[:4]


def cards_search_params(target: str, limit: int, query: TargetQuery, as_handle: str = "") -> dict:
    """/v1/agents/search params: the free text plus the parsed filters Cards can score on, and
    the searcher's own handle so people who want to meet someone like them rank higher."""
    params: dict = {"q": (target or "").strip(), "limit": limit, "include_unclaimed": "true"}
    if as_handle:
        params["as_handle"] = as_handle
    if query.role:
        params["role"] = query.role_noun
    if query.locality or query.location:
        params["location"] = query.locality or query.location
    if query.topics:
        params["skills"] = ",".join(query.topics)[:200]
    return params


async def search_cards(
    target: str, limit: int, *, query: TargetQuery | None = None, as_handle: str = "",
) -> tuple[list[dict], str | None]:
    """Claimed and unclaimed published cards. Unclaimed rows carry no contact fields."""
    q = (target or "").strip()
    if not q or not settings.cards_api_base_url:
        return [], None
    query = query or parse_target_heuristic(q)
    url = f"{settings.cards_api_base_url.rstrip('/')}/v1/agents/search"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0)) as client:
            resp = await client.get(url, params=cards_search_params(q, limit, query, as_handle))
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        logger.warning("find_people cards search failed: %s", exc)
        return [], "cards_unavailable"
    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return [], "cards_unavailable"

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
            "linkedin_url": _linkedin_url(row.get("linkedin_url")),
            "url": _card_url(handle, row.get("url")),
            "connection_eligible": False,
        }
        out.append(item)
        if len(out) >= limit:
            break
    return out, None


def _qe_headers() -> dict:
    name = (settings.quickenrich_auth_header or "Authorization").strip()
    key = settings.quickenrich_api_key
    value = f"Bearer {key}" if name.lower() == "authorization" else key
    return {name: value, "Accept": "application/json"}


async def search_quickenrich(
    target: str, limit: int, *, query: TargetQuery | None = None,
) -> tuple[list[dict], str | None]:
    """Free contact-finder. Returns LinkedIn URLs and contact flags, never email/phone.

    Every way this can return nothing carries a warning: not configured, a query too vague
    to search with, an HTTP error. An empty list with no warning means "searched, found none".
    """
    if not settings.quickenrich_base_url or not settings.quickenrich_api_key:
        return [], "quickenrich_not_configured"
    body = quickenrich_body(query or parse_target_heuristic(target), limit)
    if body is None:
        return [], "quickenrich_query_too_vague"
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

    out: list[dict] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        name = " ".join(part for part in (_na(record.get("first_name")), _na(record.get("last_name"))) if part)
        link = _public_url(record.get("employee_linkedin"))
        key = link or name
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({
            "source": "quickenrich",
            "name": _public_text(name),
            "title": _public_text(record.get("title")),
            "company": _public_text(record.get("company_name")),
            "linkedin_url": link,
            "has_email": record.get("has_email") is True,
            "has_phone": record.get("has_phone") is True,
            "connection_eligible": False,
        })
        if len(out) >= limit:
            break
    return out, None
