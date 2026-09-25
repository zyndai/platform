"""LinkedIn people search powered by Exa (semantic) / Tavily (fallback),
with Firecrawl profile enrichment and ZYND internal cross-referencing.

Flow for MCP tools:
  1. Get user's context graph facts via active_context()
  2. Build a natural-language query from those facts
  3. Search ZYND internal users (find_people)   → ranked FIRST
  4. Search LinkedIn externally via Exa/Tavily  → ranked SECOND
  5. Enrich each external LinkedIn URL via Firecrawl (name, headline, about, ...)

Every external API call is wrapped with logging + graceful fallback — if Exa is
out of credits, Tavily picks up. If Firecrawl is down, profiles come back as
bare URLs. Warnings are aggregated and surfaced to the caller.
"""

import logging
import re
from typing import Any

import asyncpg
import httpx

from app.config import settings
from app.services.export import active_context
from app.services.matching import search_by_query

logger = logging.getLogger("zynd.linkedin_search")

_LINKEDIN_PROFILE_RE = re.compile(
    r"^https?://([a-z]{2,3}\.)?linkedin\.com/in/[^/?#]+/?$", re.IGNORECASE
)

EXA_ENDPOINT = "https://api.exa.ai/search"
TAVILY_ENDPOINT = "https://api.tavily.com/search"
FIRECRAWL_SCRAPE_ENDPOINT = "https://api.firecrawl.dev/v1/scrape"

# ── LinkedIn profile URL search (Exa → Tavily fallback) ──────────────────────


async def _search_exa(client: httpx.AsyncClient, query: str, num_results: int, timeout: int) -> list[str]:
    resp = await client.post(
        EXA_ENDPOINT,
        headers={"x-api-key": settings.exa_api_key, "Content-Type": "application/json"},
        json={
            "query": query,
            "type": "neural",
            "numResults": max(num_results * 3, 20),
            "includeDomains": ["linkedin.com"],
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return [r.get("url", "") for r in resp.json().get("results", [])]


async def _search_tavily(client: httpx.AsyncClient, query: str, num_results: int, timeout: int) -> list[str]:
    resp = await client.post(
        TAVILY_ENDPOINT,
        json={
            "api_key": settings.tavily_api_key,
            "query": f"{query} site:linkedin.com/in",
            "search_depth": "advanced",
            "max_results": max(num_results * 3, 20),
            "include_domains": ["linkedin.com"],
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return [r.get("url", "") for r in resp.json().get("results", [])]


def _format_http_error(exc: Exception) -> str:
    """Human-readable one-liner from an httpx error (network, HTTP 4xx/5xx, timeout)."""
    if isinstance(exc, httpx.HTTPStatusError):
        detail = ""
        try:
            body = exc.response.text[:300]
            detail = f" — {body}"
        except Exception:
            pass
        return f"HTTP {exc.response.status_code}{detail}"
    if isinstance(exc, httpx.TimeoutException):
        return f"timeout after {exc.request.extensions.get('timeout', {})}s" if exc.request else "timeout"
    if isinstance(exc, httpx.NetworkError):
        return f"network error: {exc}"
    return f"{type(exc).__name__}: {exc}"


def _extract_profile_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if not u:
            continue
        u = u.split("?")[0].rstrip("/")
        if _LINKEDIN_PROFILE_RE.match(u) and u not in seen:
            seen.add(u)
            out.append(u)
    return out


async def search_linkedin_profile_urls(
    query: str,
    num_results: int = 10,
    timeout: int = 15,
) -> tuple[list[str], list[str]]:
    """Semantic search for LinkedIn profile URLs matching `query`.

    Primary: Exa neural search (semantic). Fallback: Tavily keyword search.

    Returns (profile_urls, warnings). If every provider fails, urls will be []
    and warnings explain why.
    """
    if not query or not query.strip():
        return [], ["empty query — nothing to search"]
    query = query.strip()
    num_results = max(1, min(num_results, 50))

    if not settings.exa_api_key and not settings.tavily_api_key:
        return [], ["no Exa or Tavily API key configured"]

    warnings: list[str] = []

    async with httpx.AsyncClient() as client:
        profiles: list[str] = []

        providers: list[tuple[str, Any]] = []
        if settings.exa_api_key:
            providers.append(("exa", _search_exa))
        if settings.tavily_api_key:
            providers.append(("tavily", _search_tavily))

        for name, fn in providers:
            try:
                raw_urls = await fn(client, query, num_results, timeout)
            except httpx.HTTPStatusError as exc:
                detail = _format_http_error(exc)
                logger.warning("LinkedIn search — %s failed (%s), trying next provider", name, detail)
                warnings.append(f"{name} search returned {detail} (likely out of credits or rate-limited)")
                continue
            except Exception as exc:
                detail = _format_http_error(exc)
                logger.warning("LinkedIn search — %s failed (%s), trying next provider", name, detail)
                warnings.append(f"{name} search failed: {detail}")
                continue

            for url in _extract_profile_urls(raw_urls):
                if url not in profiles:
                    profiles.append(url)

            if len(profiles) >= num_results:
                break

        if not profiles and not warnings:
            warnings.append("no LinkedIn profiles found for this query")

        return profiles[:num_results], warnings


# ── Firecrawl profile enrichment ─────────────────────────────────────────────


async def _scrape_with_firecrawl(client: httpx.AsyncClient, url: str, timeout: int) -> tuple[dict | None, str | None]:
    """Scrape a single LinkedIn profile page via Firecrawl. Returns (data, warning)."""
    if not settings.firecrawl_api_key:
        return None, "no Firecrawl API key configured"

    try:
        resp = await client.post(
            FIRECRAWL_SCRAPE_ENDPOINT,
            headers={"Authorization": f"Bearer {settings.firecrawl_api_key}", "Content-Type": "application/json"},
            json={
                "url": url,
                "formats": ["markdown"],
                "onlyMainContent": True,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        markdown_text = (data.get("markdown") or "").strip()
        if not markdown_text:
            return None, f"Firecrawl returned empty content for {url}"
        return _parse_profile_markdown(markdown_text, url), None
    except httpx.HTTPStatusError as exc:
        detail = _format_http_error(exc)
        if exc.response.status_code == 402:
            logger.warning("Firecrawl — credits expired for %s", url)
            return None, f"Firecrawl credits expired (HTTP 402) for {url}"
        logger.warning("Firecrawl — HTTP %d for %s", exc.response.status_code, url)
        return None, f"Firecrawl returned {detail}"
    except Exception as exc:
        detail = _format_http_error(exc)
        logger.warning("Firecrawl — %s on %s", detail, url)
        return None, f"Firecrawl failed: {detail}"


def _parse_profile_markdown(md: str, url: str) -> dict:
    """Extract name, headline, about, etc. from Firecrawl markdown output."""
    lines = md.split("\n")
    result: dict[str, Any] = {"linkedin_url": url}
    name_consumed = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# "):
            result["name"] = stripped[2:].strip()
            name_consumed = True
            break
        if stripped.startswith("**") and stripped.endswith("**"):
            result["name"] = stripped.strip("*")
            name_consumed = True
            break

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "![", "|", "http", "©", ">")):
            continue
        if name_consumed and result.get("name") and result["name"].lower() in stripped.lower():
            continue
        result["headline"] = stripped
        break

    in_about = False
    about_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        clean = stripped.lstrip("#").lstrip().lower()
        if clean.startswith("about"):
            in_about = True
            continue
        if in_about:
            if stripped.startswith("#") or stripped.startswith("##"):
                break
            if stripped:
                about_lines.append(stripped)
    if about_lines:
        result["about"] = " ".join(about_lines)[:2000]

    return result


async def enrich_profile_urls(urls: list[str], timeout: int = 30) -> tuple[list[dict], list[str]]:
    """Enrich LinkedIn profile URLs with Firecrawl-scraped data.

    Returns (enriched_profiles, warnings). Degrades gracefully: if Firecrawl
    is down or out of credits, returns bare URL entries + a warning.
    """
    if not urls:
        return [], []

    warnings: list[str] = []

    if not settings.firecrawl_api_key:
        logger.info("Firecrawl — no API key configured, returning bare URLs")
        return [{"linkedin_url": u} for u in urls], ["no Firecrawl API key — profiles returned as bare URLs"]

    async with httpx.AsyncClient() as client:
        results: list[dict] = []
        firecrawl_ok = False

        for url in urls[:15]:
            enriched, warn = await _scrape_with_firecrawl(client, url, timeout)
            if enriched:
                results.append(enriched)
                firecrawl_ok = True
            else:
                results.append({"linkedin_url": url})
                if warn:
                    warnings.append(warn)

        if not firecrawl_ok and results:
            logger.warning("Firecrawl — all enrichment calls failed, returning bare URLs")
            if "Firecrawl unavailable — profiles returned as bare URLs" not in warnings:
                warnings.append("Firecrawl enrichment unavailable — profiles returned as bare URLs")

        return results, warnings


# ── Query builder from user context ──────────────────────────────────────────


def build_query_from_context(facts: list[dict]) -> str:
    """Build a natural-language LinkedIn search query from ZYND context facts."""
    statements = [f.get("statement", "").strip() for f in facts if f.get("statement", "").strip()]
    if not statements:
        return ""

    terms: list[str] = []
    for s in statements:
        s = (s.removeprefix("You are ")
              .removeprefix("You're ")
              .removeprefix("You have ")
              .removeprefix("Your "))
        s = (s.replace("building a ", "")
              .replace("working on ", "")
              .replace("interested in ", "")
              .replace("learning ", "")
              .replace("seeking ", "")
              .replace("open to ", "")
              .replace("experience in ", ""))
        s = s.strip(",.").strip()
        if s:
            terms.append(s)

    seen: set[str] = set()
    unique: list[str] = []
    for t in terms:
        lower = t.lower()
        if lower and lower not in seen:
            seen.add(lower)
            unique.append(t)

    return ", ".join(unique[:12])


# ── Main orchestration: ZYND + Exa + Firecrawl ───────────────────────────────


async def find_linkedin_people(
    pool: asyncpg.Pool,
    user_id: str,
    query: str | None = None,
    num_results: int = 10,
) -> dict:
    """Combined LinkedIn people search — ZYND internal first, then external."""
    num_results = max(1, min(num_results, 25))
    warnings: list[str] = []

    if not query or not query.strip():
        facts = await active_context(pool, user_id, k=20)
        query = build_query_from_context(facts)

    if not query or not query.strip():
        return {"zynd_users": [], "linkedin_profiles": [], "query": "", "warnings": ["no context facts to build a query from"]}

    # 1. ZYND internal search
    zynd_users: list[dict] = await search_by_query(
        pool, user_id, query, cluster_type="full_context", limit=num_results
    )

    # 2. External LinkedIn profile search
    profile_urls, search_warnings = await search_linkedin_profile_urls(query, num_results=num_results)
    warnings.extend(search_warnings)

    linkedin_profiles, enrich_warnings = await enrich_profile_urls(profile_urls)
    warnings.extend(enrich_warnings)

    return {
        "query": query,
        "zynd_users": zynd_users,
        "linkedin_profiles": linkedin_profiles,
        "warnings": warnings if warnings else None,
    }
