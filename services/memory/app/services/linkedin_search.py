"""LinkedIn people search powered by Exa (semantic) / Tavily (fallback),
with Firecrawl profile enrichment and ZYND internal cross-referencing.

Flow for MCP tools:
  1. Get user's context graph facts via active_context()
  2. Build a natural-language query from those facts
  3. Search ZYND internal users (find_people)   → ranked FIRST
  4. Search LinkedIn externally via Exa/Tavily  → ranked SECOND
  5. Enrich each external LinkedIn URL via Firecrawl (name, headline, about, ...)
"""

import re
from typing import Any

import asyncpg
import httpx

from app.config import settings
from app.services.export import active_context
from app.services.matching import search_by_query

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
) -> list[str]:
    """Semantic search for LinkedIn profile URLs matching `query`.

    Primary: Exa neural search (semantic). Fallback: Tavily keyword search.
    """
    if not query or not query.strip():
        return []
    query = query.strip()
    num_results = max(1, min(num_results, 50))

    if not settings.exa_api_key and not settings.tavily_api_key:
        return []

    async with httpx.AsyncClient() as client:
        profiles: list[str] = []
        last_error: Exception | None = None

        # Try Exa first, then Tavily
        providers: list[tuple[str, Any]] = []
        if settings.exa_api_key:
            providers.append(("exa", _search_exa))
        if settings.tavily_api_key:
            providers.append(("tavily", _search_tavily))

        for _name, fn in providers:
            try:
                raw_urls = await fn(client, query, num_results, timeout)
            except Exception as exc:
                last_error = exc
                continue

            for url in _extract_profile_urls(raw_urls):
                if url not in profiles:
                    profiles.append(url)

            if len(profiles) >= num_results:
                break

        if not profiles and last_error:
            return []  # silent degradation — callers handle empty list

        return profiles[:num_results]


# ── Firecrawl profile enrichment ─────────────────────────────────────────────


async def _scrape_with_firecrawl(client: httpx.AsyncClient, url: str, timeout: int) -> dict | None:
    """Scrape a single LinkedIn profile page via Firecrawl and extract structured info."""
    if not settings.firecrawl_api_key:
        return None
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
            return None
        return _parse_profile_markdown(markdown_text, url)
    except Exception:
        return None


def _parse_profile_markdown(md: str, url: str) -> dict:
    """Extract name, headline, about, etc. from Firecrawl markdown output."""
    lines = md.split("\n")
    result: dict[str, Any] = {"linkedin_url": url}
    name_consumed = False

    # Pass 1: find name from heading or bold
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

    # Pass 2: find headline — first meaningful non-name line (skip headings, images, links)
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

    # Pass 3: extract "About" section
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


async def enrich_profile_urls(urls: list[str], timeout: int = 30) -> list[dict]:
    """Enrich a list of LinkedIn profile URLs with Firecrawl-scraped profile data."""
    if not urls or not settings.firecrawl_api_key:
        return [{"linkedin_url": u} for u in urls]

    async with httpx.AsyncClient() as client:
        results: list[dict] = []
        for url in urls[:15]:  # cap to avoid rate limits
            enriched = await _scrape_with_firecrawl(client, url, timeout)
            results.append(enriched if enriched else {"linkedin_url": url})
        return results


# ── Query builder from user context ──────────────────────────────────────────


def build_query_from_context(facts: list[dict]) -> str:
    """Build a natural-language LinkedIn search query from ZYND context facts.

    Combines role, skills, projects, interests into a search phrase like:
    "backend engineer, AI agents, micro-SaaS, developer tools, San Francisco"
    """
    statements = [f.get("statement", "").strip() for f in facts if f.get("statement", "").strip()]
    if not statements:
        return ""

    # Collect key terms: roles, skills, tools, projects, interests
    terms: list[str] = []
    for s in statements:
        s = s.removeprefix("You are ").removeprefix("You're ").removeprefix("Your ")
        s = s.replace("building a ", "").replace("working on ", "").replace("interested in ", "")
        s = s.replace("learning ", "").replace("seeking ", "").replace("open to ", "")
        terms.append(s.strip(",."))

    # Remove duplicates while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t in terms:
        lower = t.lower()
        if lower and lower not in seen:
            seen.add(lower)
            unique.append(t)

    return ", ".join(unique[:12])  # cap for reasonable search query length


# ── Main orchestration: ZYND + Exa + Firecrawl ───────────────────────────────


async def find_linkedin_people(
    pool: asyncpg.Pool,
    user_id: str,
    query: str | None = None,
    num_results: int = 10,
) -> dict:
    """Combined LinkedIn people search — ZYND internal first, then external.

    Args:
        pool: Database pool
        user_id: ZYND user ID
        query: Natural-language search query (auto-built from context if None)
        num_results: Max results per section

    Returns:
        {"zynd_users": [...], "linkedin_profiles": [...]}

    ZYND users are always ranked first. External LinkedIn profiles (via Exa/Tavily)
    are enriched with Firecrawl and ranked second.
    """
    num_results = max(1, min(num_results, 25))

    # Build query from user context if not provided
    if not query or not query.strip():
        facts = await active_context(pool, user_id, k=20)
        query = build_query_from_context(facts)

    if not query or not query.strip():
        return {"zynd_users": [], "linkedin_profiles": [], "query": ""}

    # 1. ZYND internal search
    zynd_users: list[dict] = await search_by_query(
        pool, user_id, query, cluster_type="full_context", limit=num_results
    )

    # 2. External LinkedIn profile search
    profile_urls = await search_linkedin_profile_urls(query, num_results=num_results)
    linkedin_profiles = await enrich_profile_urls(profile_urls)

    return {
        "query": query,
        "zynd_users": zynd_users,
        "linkedin_profiles": linkedin_profiles,
    }
