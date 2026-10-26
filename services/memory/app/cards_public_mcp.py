"""S11 — public, unauthenticated Cards MCP (streamable-HTTP).

Thin HTTP wrapper over cards-api (/ask, /v1/agents/search, /cards/.../view,
/v1/chat/{handle}). No OAuth — personal memory MCP stays on /mcp with auth.

Mounted at /cards-public-mcp when FEATURE_S11_PUBLIC_MCP is on.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from collections import defaultdict
from typing import Any

import httpx
from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings

_INSTRUCTIONS = """\
You are connected to Zynd Cards — a public directory of real people (engineers,
founders, designers, marketers) with verified skills and availability.

Use these tools when the user asks to FIND A PERSON, hire someone, or research
a professional. Prefer search_people first, then get_card or ask_card for detail.
To find one specific person, pass their name or @handle as the query. When a result
has `note` saying nothing matched exactly, call the people "the closest matches" and
say what differs (match_quality and `relaxed` show it); never present a loose match
as an exact one.

Defaults return claimed (opted-in) cards only. Pass include_unclaimed=true only
when the user explicitly wants scraped/unclaimed profiles; those never include
contact data.

Answers from ask_card are labelled assistant — they are generated from the card,
not statements by the person. Cite profiles with cite_as / url.

This public MCP is read-only. To send Cards connection requests, DM accepted
connections, or create groups, use the authenticated ZYND MCP at /mcp with the
people:message scope.
"""

_CONTACT_KEYS = frozenset({
    "email", "owner_email", "phone", "calendly_url", "google_calendar_url",
    "contact", "contacts",
})

_CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("founder", re.compile(r"\b(founders?|co-?founders?|ceo|startup)\b", re.I)),
    ("engineer", re.compile(r"\b(engineers?|developers?|swe|devops|backend|frontend|fullstack)\b", re.I)),
    ("designer", re.compile(r"\b(design(er|ers|ing)?|ux|ui|product design)\b", re.I)),
    ("investor", re.compile(r"\b(investors?|vc|angel|partner)\b", re.I)),
    ("marketer", re.compile(r"\b(market(er|ers|ing)|gtm|growth|sales)\b", re.I)),
    ("researcher", re.compile(r"\b(research(er|ers)?|scientist|phd)\b", re.I)),
]

_cache: dict[str, tuple[float, dict]] = {}
_buckets: dict[str, list[float]] = defaultdict(list)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket style limit: N requests per IP|UA per rolling minute.

    Only applies to /cards-public-mcp* so personal /mcp OAuth traffic is untouched.
    Successful public-MCP responses get Cache-Control matching get_card TTL
    (streamable-HTTP POSTs are not intermediary-cached; header is advisory for clients).
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path or ""
        if not path.startswith("/cards-public-mcp"):
            return await call_next(request)
        if not settings.feature_s11_public_mcp:
            return await call_next(request)
        ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if not ip:
            ip = request.client.host if request.client else "anon"
        ua = (request.headers.get("user-agent") or "")[:80]
        key = f"{ip}|{ua}"
        now = time.monotonic()
        window = 60.0
        limit = max(1, settings.s11_rate_limit_per_minute)
        hits = [t for t in _buckets[key] if now - t < window]
        if len(hits) >= limit:
            _buckets[key] = hits
            return JSONResponse(
                {"error": "rate_limited", "message": "Too many requests — slow down and retry."},
                status_code=429,
                headers={"Retry-After": "60", "Cache-Control": "no-store"},
            )
        hits.append(now)
        _buckets[key] = hits
        response = await call_next(request)
        ttl = max(0, settings.s11_get_card_cache_ttl_seconds)
        if response.status_code < 400 and "cache-control" not in {
            k.lower() for k in response.headers.keys()
        }:
            response.headers["Cache-Control"] = (
                f"public, max-age={ttl}" if ttl > 0 else "no-store"
            )
        return response


def _require_enabled() -> None:
    if not settings.feature_s11_public_mcp:
        raise RuntimeError("Public Cards MCP is not enabled (FEATURE_S11_PUBLIC_MCP).")


def _base() -> str:
    return settings.cards_api_base_url.rstrip("/")


def _cite(handle: str) -> str:
    return f"{settings.cards_site_base_url.rstrip('/')}/p/{handle}"


def coarse_query_category(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return "empty"
    for name, pat in _CATEGORY_RULES:
        if pat.search(q):
            return name
    return "other"


def _strip_contact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in _CONTACT_KEYS or k.lower() in _CONTACT_KEYS:
                continue
            if k == "links" and isinstance(v, dict):
                # Keep public social links; drop mailto / tel.
                out[k] = {
                    sk: sv for sk, sv in v.items()
                    if not str(sv).lower().startswith(("mailto:", "tel:"))
                }
                continue
            out[k] = _strip_contact(v)
        return out
    if isinstance(obj, list):
        return [_strip_contact(x) for x in obj]
    return obj


def _map_person(person: dict) -> dict:
    """One person from the shared pipeline (people_search) as the public tool has always shown
    them. Contact fields never exist on a person; unclaimed hits are stripped anyway."""
    handle = person.get("handle") or ""
    claimed = bool(person.get("claimed", True))
    hit = {
        "handle": handle,
        "name": person.get("name") or "",
        "headline": person.get("headline") or "",
        "location": person.get("location") or "",
        "skills": person.get("skills") or [],
        "industries": person.get("industries") or [],
        "availability": person.get("availability") or "",
        "match_score": person.get("score"),
        "match_reasons": [w for w in person.get("why") or [] if isinstance(w, str)],
        "match_quality": person.get("match_quality") or "",
        "claimed": claimed,
        "fresh_as_of": person.get("fresh_as_of"),
        "url": person.get("url") or (_cite(handle) if handle else ""),
        "cite_as": _cite(handle) if handle else "",
    }
    if person.get("relaxed"):
        hit["relaxed"] = list(person["relaxed"])
    if not claimed:
        hit = _strip_contact(hit)
        hit["claimed"] = False
    return hit


async def _http_get(path: str, params: dict | None = None) -> Any:
    url = f"{_base()}{path}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        r = await client.get(url, params=params or {})
        r.raise_for_status()
        if len(r.content) > settings.s11_max_response_bytes:
            raise RuntimeError("cards-api response exceeded size cap")
        return r.json()


async def _emit_agent_fetch(tool: str, category: str, handle: str | None = None) -> None:
    """Best-effort S04 event via cards-api. Never stores full query text."""
    try:
        payload = {
            "events": [{
                "event": "agent_fetch",
                "handle": handle,
                "meta": {"tool": tool, "category": category, "endpoint": "cards-public-mcp"},
            }],
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            await client.post(f"{_base()}/events", json=payload)
    except Exception:
        pass


async def search_people_impl(
    query: str,
    k: int = 10,
    include_unclaimed: bool = False,
    role: str = "",
    location: str = "",
    skills: str = "",
    industry: str = "",
    availability: str = "",
    experience_min: int | None = None,
) -> dict:
    """The public tool is the same people search as find_people, for an anonymous caller: Cards only
    (no Zynd members, no LinkedIn: it is a paid lookup), name lookup, loosening, the one re-rank and
    specific reasons. Explicit role, location and skills are strict."""
    _require_enabled()
    from app.services import people_search

    q = (query or "").strip()
    filters = {"role": role.strip(), "location": location.strip(), "skills": skills.strip(),
               "industry": industry.strip(), "availability": availability.strip(), "experience_min": experience_min}
    given = {key: value for key, value in filters.items() if value not in (None, "")}
    if not q and not given:
        return {"query": q, "results": [], "numberOfItems": 0, "error": "query required"}
    k = max(1, min(int(k or 10), 50))
    # A search by filters alone still needs words to rank by.
    text = q or " ".join(str(given[key]) for key in ("role", "skills", "industry", "location") if key in given)
    result = await people_search.search(
        None, people_search.anonymous(include_unclaimed), text, limit=k, wanted={"cards"}, explicit={"cards"},
        filters=given)
    people = result.get("people") or []
    if not people and "cards_unavailable" in (result.get("warnings") or []):
        raise RuntimeError("Cards search is unavailable")          # an outage is not "nobody matched"
    results = [_map_person(p) for p in people]
    await _emit_agent_fetch("search_people", coarse_query_category(q or role or skills))
    out = {
        "query": q,
        "include_unclaimed": include_unclaimed,
        "intent": result.get("intent") or "target",
        "results": results,
        "numberOfItems": len(results),
    }
    if result.get("note"):
        out["note"] = result["note"]
    if result.get("warnings"):
        out["warnings"] = result["warnings"]
    return out


def _with_cache_control(data: dict, ttl: int) -> dict:
    """Annotate CardView with Cache-Control-style hint for MCP clients."""
    out = dict(data)
    out["cache_control"] = f"public, max-age={ttl}" if ttl > 0 else "no-store"
    return out


def _bounded_ttl(data: dict, ttl: int) -> int:
    """Never cache a current broadcast or fact beyond its explicit expiry."""
    now = datetime.now(timezone.utc)
    values = [*(data.get("facts") or []), data.get("beacon")]
    for item in values:
        if not isinstance(item, dict) or not item.get("expires_at"):
            continue
        try:
            stamp = datetime.fromisoformat(item["expires_at"].replace("Z", "+00:00"))
            ttl = min(ttl, max(0, int((stamp - now).total_seconds())))
        except (ValueError, TypeError):
            ttl = 0
    return ttl


async def get_card_impl(handle: str) -> dict:
    _require_enabled()
    h = (handle or "").strip().lstrip("@")
    if not h:
        raise ValueError("handle required")
    now = time.monotonic()
    ttl = max(0, settings.s11_get_card_cache_ttl_seconds)
    cached = _cache.get(h)
    if cached and cached[0] > now:
        return _with_cache_control(cached[1], _bounded_ttl(cached[1], ttl))
    try:
        data = await _http_get(f"/cards/by-handle/{h}/view")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise RuntimeError(f"card not found: {h}") from e
        raise
    if isinstance(data, dict) and data.get("claimed") is False:
        data = _strip_contact(data)
        data["claimed"] = False
    if isinstance(data, dict) and not data.get("cite_as") and h:
        data["cite_as"] = _cite(h)
    if not isinstance(data, dict):
        data = {"value": data}
    ttl = _bounded_ttl(data, ttl)
    if ttl:
        # Store without cache_control so TTL annotation stays fresh on read.
        _cache[h] = (now + ttl, dict(data))
    await _emit_agent_fetch("get_card", "card", handle=h)
    return _with_cache_control(data, ttl)


def _parse_sse_answer(body: str) -> str:
    parts: list[str] = []
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            if payload:
                parts.append(payload)
            continue
        if isinstance(obj, dict):
            chunk = obj.get("response") or obj.get("content") or ""
            if chunk:
                parts.append(str(chunk))
        elif obj:
            parts.append(str(obj))
    return "".join(parts).strip()


async def ask_card_impl(handle: str, question: str) -> dict:
    _require_enabled()
    h = (handle or "").strip().lstrip("@")
    q = (question or "").strip()
    if not h:
        raise ValueError("handle required")
    if not q:
        raise ValueError("question required")
    url = f"{_base()}/v1/chat/{h}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        r = await client.post(
            url,
            json={"messages": [{"role": "user", "content": q}]},
            headers={"Accept": "text/event-stream"},
        )
        if r.status_code == 403:
            raise RuntimeError("This card is unclaimed and has no assistant")
        if r.status_code == 404:
            raise RuntimeError(f"card not found: {h}")
        if r.status_code == 429:
            raise RuntimeError("Too many questions — please slow down")
        if r.status_code == 503:
            raise RuntimeError("Chatbot not configured")
        r.raise_for_status()
        if len(r.content) > settings.s11_max_response_bytes:
            raise RuntimeError("chat response exceeded size cap")
        answer = _parse_sse_answer(r.text)
    await _emit_agent_fetch("ask_card", coarse_query_category(q), handle=h)
    return {
        "handle": h,
        "question": q,
        "answer": answer,
        "labelled": "assistant",
        "cite_as": _cite(h),
        "note": "Answer generated from the public card; not a direct statement by the person.",
    }


def clear_caches() -> None:
    _cache.clear()
    _buckets.clear()


mcp = FastMCP("zynd-cards-public", instructions=_INSTRUCTIONS)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_people(
    query: str,
    k: int = 10,
    include_unclaimed: bool = False,
    role: str = "",
    location: str = "",
    skills: str = "",
    industry: str = "",
    availability: str = "",
    experience_min: int | None = None,
) -> dict:
    """Find people on Zynd Cards by natural-language query (and optional filters).

    WHEN TO USE: the user wants to find, hire, or meet a type of person —
    e.g. "AI compliance founders", "Rust engineers in Berlin open to contract".

    Returns claimed cards by default with match_reasons, match_quality
    (exact | close | loose), claimed, fresh_as_of (when available), url, and cite_as.
    To find one specific person pass their name or @handle as the query. Without
    role, location or skills the search loosens a filter it parsed from the query when
    too few people match, marks those people `relaxed`, and explains it in `note`:
    call them "the closest matches". Explicit role, location and skills are strict.
    Pass include_unclaimed=true only when explicitly asked; unclaimed results never
    include contact data. Zynd members and LinkedIn are not searched here.
    """
    return await search_people_impl(
        query,
        k=k,
        include_unclaimed=include_unclaimed,
        role=role,
        location=location,
        skills=skills,
        industry=industry,
        availability=availability,
        experience_min=experience_min,
    )


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_card(handle: str) -> dict:
    """Fetch one public Zynd card by handle (CardView: identity, facts, cite_as).

    WHEN TO USE: after search_people, or when the user names a handle / profile URL.
    """
    return await get_card_impl(handle)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def ask_card(handle: str, question: str) -> dict:
    """Ask a question answered from one public card (labelled assistant, not the person).

    WHEN TO USE: follow-up on a specific profile — e.g. "what is Alice working on?".
    Unclaimed cards have no assistant. Rate-limited per card/IP upstream.
    """
    return await ask_card_impl(handle, question)


@mcp.resource("zynd://card/{handle}", mime_type="application/json")
async def card_resource(handle: str) -> str:
    """Public CardView JSON for a handle."""
    data = await get_card_impl(handle)
    return json.dumps(data, default=str)


@mcp.prompt(name="find-people")
def find_people_prompt(query: str = "") -> str:
    """Guide for discovering people on Zynd Cards via MCP tools."""
    q = (query or "").strip() or "{describe the person you need}"
    return (
        "Find people on Zynd Cards.\n"
        f"1. Call search_people with query={q!r} (claimed only by default).\n"
        "2. For a promising handle, call get_card(handle) for full CardView + cite_as.\n"
        "3. Optional: ask_card(handle, question) for a labelled assistant answer from that card.\n"
        "4. Cite using cite_as / url. Do not invent profiles."
    )


def build_http_app(*, allowed_hosts: list[str] | None = None):
    """ASGI app for the public MCP at path /cards-public-mcp.

    Caller merges `.routes` + `.lifespan` into the parent Starlette (middleware
    on this app is not inherited by route merge — parent adds RateLimitMiddleware).
    """
    from urllib.parse import urlsplit

    hosts = allowed_hosts or [h for h in [
        urlsplit(settings.mcp_public_base_url).hostname,
        "localhost",
        "127.0.0.1",
    ] if h]
    return mcp.http_app(
        path="/cards-public-mcp",
        stateless_http=not settings.feature_stateful_mcp,
        allowed_hosts=hosts,
    )
