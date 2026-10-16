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


def _card_url(handle: str, upstream: object) -> str:
    built = f"{settings.cards_site_base_url.rstrip('/')}/p/{handle}"
    return built if _HANDLE.fullmatch(handle) else _public_url(upstream)


def _keywords(target: str) -> list[str]:
    words = []
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9+-]{2,}", target or ""):
        word = raw.strip()
        if word.lower() in _STOP:
            continue
        if word not in words:
            words.append(word)
        if len(words) == 4:
            break
    return words


def _na(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.upper() == "N/A" else text


async def search_cards(target: str, limit: int) -> tuple[list[dict], str | None]:
    """Claimed and unclaimed published cards. Unclaimed rows carry no contact fields."""
    q = (target or "").strip()
    if not q or not settings.cards_api_base_url:
        return [], None
    url = f"{settings.cards_api_base_url.rstrip('/')}/v1/agents/search"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0)) as client:
            resp = await client.get(url, params={"q": q, "limit": limit, "include_unclaimed": "true"})
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


async def search_quickenrich(target: str, limit: int) -> tuple[list[dict], str | None]:
    """Free contact-finder. Returns LinkedIn URLs and contact flags, never email/phone."""
    if not settings.quickenrich_base_url or not settings.quickenrich_api_key:
        return [], None
    keywords = _keywords(target)
    if not keywords:
        return [], None
    body = {
        "bio_li": {"include": keywords, "exclude": []},
        "page": 1,
        "per_page": max(1, min(limit, 10)),
    }
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
