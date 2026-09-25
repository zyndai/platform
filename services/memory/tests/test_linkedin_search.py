"""Tests for app/services/linkedin_search.py — async Exa / Tavily / Firecrawl integration."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.linkedin_search import (
    _extract_profile_urls,
    _parse_profile_markdown,
    build_query_from_context,
    search_linkedin_profile_urls,
    enrich_profile_urls,
    _scrape_with_firecrawl,
)

import httpx


# ── URL extraction ────────────────────────────────────────────────────────────


def test_extract_valid_linkedin_urls():
    urls = [
        "https://www.linkedin.com/in/jane-doe?trk=abc",
        "https://www.linkedin.com/in/john-smith/",
        "https://www.linkedin.com/in/jane-doe",  # dup
        "https://www.linkedin.com/company/acme",  # not a profile
        "https://example.com/not-linkedin",
    ]
    result = _extract_profile_urls(urls)
    assert result == [
        "https://www.linkedin.com/in/jane-doe",
        "https://www.linkedin.com/in/john-smith",
    ]


def test_extract_international_linkedin():
    urls = ["https://uk.linkedin.com/in/alice-w", "https://de.linkedin.com/in/bob-k/"]
    result = _extract_profile_urls(urls)
    assert result == ["https://uk.linkedin.com/in/alice-w", "https://de.linkedin.com/in/bob-k"]


def test_extract_empty():
    assert _extract_profile_urls([]) == []
    assert _extract_profile_urls(["", None, "not-a-url"]) == []


# ── Profile markdown parsing ──────────────────────────────────────────────────


def test_parse_profile_markdown_basic():
    md = """# Jane Doe
    Senior Engineer at Acme Corp

    ## About
    Building AI-powered developer tools. Previously at Google and Stripe.
    Passionate about open source and distributed systems.
    """
    result = _parse_profile_markdown(md, "https://www.linkedin.com/in/jane-doe")
    assert result["name"] == "Jane Doe"
    assert result["headline"] == "Senior Engineer at Acme Corp"
    assert "AI-powered developer tools" in result["about"]
    assert result["linkedin_url"] == "https://www.linkedin.com/in/jane-doe"


def test_parse_profile_markdown_bold_name():
    md = """**John Smith**
    Product Manager | Climate Tech

    About
    Leading product at a Series A climate startup.
    """
    result = _parse_profile_markdown(md, "https://www.linkedin.com/in/john-smith")
    assert result["name"] == "John Smith"
    assert result["headline"] == "Product Manager | Climate Tech"
    assert "Series A climate" in result["about"]


def test_parse_profile_markdown_minimal():
    md = """https://linkedin.com/in/minimal
    Just a headline, no about section.
    """
    result = _parse_profile_markdown(md, "https://www.linkedin.com/in/minimal")
    assert result["linkedin_url"] == "https://www.linkedin.com/in/minimal"
    assert "about" not in result


# ── Query builder ─────────────────────────────────────────────────────────────


def test_build_query_from_context():
    facts = [
        {"statement": "You are a senior backend engineer"},
        {"statement": "You're building a micro-SaaS for developer tools"},
        {"statement": "Your skills include Python, TypeScript, and distributed systems"},
        {"statement": "You're interested in AI agents and LLMs"},
        {"statement": "You're located in San Francisco"},
    ]
    query = build_query_from_context(facts)
    assert "senior backend engineer" in query
    assert "developer tools" in query
    assert "Python" in query
    assert "AI agents" in query or "LLMs" in query
    assert "San Francisco" in query


def test_build_query_deduplicates():
    facts = [
        {"statement": "You are a backend engineer"},
        {"statement": "You're a backend engineer"},  # duplicate concept
    ]
    query = build_query_from_context(facts)
    assert query.lower().count("backend engineer") == 1


def test_build_query_empty():
    assert build_query_from_context([]) == ""
    assert build_query_from_context([{"statement": ""}]) == ""


# ── Exa / Tavily search (mocked) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_linkedin_no_api_keys(monkeypatch):
    monkeypatch.setattr("app.services.linkedin_search.settings.exa_api_key", "")
    monkeypatch.setattr("app.services.linkedin_search.settings.tavily_api_key", "")
    urls, warnings = await search_linkedin_profile_urls("senior engineers fintech", num_results=5)
    assert urls == []
    assert any("no Exa" in w for w in warnings)


@pytest.mark.asyncio
async def test_search_linkedin_exa_happy_path(monkeypatch):
    monkeypatch.setattr("app.services.linkedin_search.settings.exa_api_key", "fake-exa")
    monkeypatch.setattr("app.services.linkedin_search.settings.tavily_api_key", "")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "results": [
            {"url": "https://www.linkedin.com/in/jane-doe?trk=abc"},
            {"url": "https://www.linkedin.com/in/john-smith/"},
            {"url": "https://www.linkedin.com/in/jane-doe"},  # dup
            {"url": "https://www.linkedin.com/company/acme"},  # not profile
        ]
    }

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("app.services.linkedin_search.httpx.AsyncClient", return_value=mock_client):
        urls, warnings = await search_linkedin_profile_urls("senior engineers fintech", num_results=5)

    assert urls == [
        "https://www.linkedin.com/in/jane-doe",
        "https://www.linkedin.com/in/john-smith",
    ]
    assert warnings == []


@pytest.mark.asyncio
async def test_search_linkedin_fallback_to_tavily(monkeypatch):
    monkeypatch.setattr("app.services.linkedin_search.settings.exa_api_key", "fake-exa")
    monkeypatch.setattr("app.services.linkedin_search.settings.tavily_api_key", "fake-tavily")

    call_count = {"count": 0}

    async def mock_post(url, **kwargs):
        call_count["count"] += 1
        if "exa.ai" in url:
            # Raise httpx.HTTPStatusError to hit the specific 402/credits handler
            req = MagicMock()
            req.url = url
            resp = MagicMock()
            resp.status_code = 402
            resp.text = '{"error":"credits_exhausted"}'
            resp.request = req
            raise httpx.HTTPStatusError("credits exhausted", request=req, response=resp)
        # Tavily succeeds
        tavily_resp = MagicMock()
        tavily_resp.raise_for_status = MagicMock()
        tavily_resp.json.return_value = {
            "results": [{"url": "https://www.linkedin.com/in/carol-t"}]
        }
        return tavily_resp

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = mock_post

    with patch("app.services.linkedin_search.httpx.AsyncClient", return_value=mock_client):
        urls, warnings = await search_linkedin_profile_urls("ML researchers", num_results=5)

    assert urls == ["https://www.linkedin.com/in/carol-t"]
    assert call_count["count"] >= 2  # Exa tried + Tavily tried
    assert any("exa" in w.lower() for w in warnings)  # exa failure logged as warning


@pytest.mark.asyncio
async def test_search_linkedin_both_providers_fail(monkeypatch):
    monkeypatch.setattr("app.services.linkedin_search.settings.exa_api_key", "fake-exa")
    monkeypatch.setattr("app.services.linkedin_search.settings.tavily_api_key", "fake-tavily")

    async def mock_post(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "Internal Server Error"
        resp.request = MagicMock()
        raise httpx.HTTPStatusError("server error", request=resp.request, response=resp)

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = mock_post

    with patch("app.services.linkedin_search.httpx.AsyncClient", return_value=mock_client):
        urls, warnings = await search_linkedin_profile_urls("query", num_results=5)

    assert urls == []
    assert len(warnings) == 2  # both providers logged warnings


# ── Firecrawl enrichment (mocked) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enrich_no_api_key(monkeypatch):
    monkeypatch.setattr("app.services.linkedin_search.settings.firecrawl_api_key", "")
    urls = ["https://www.linkedin.com/in/jane-doe"]
    profiles, warnings = await enrich_profile_urls(urls)
    assert profiles == [{"linkedin_url": "https://www.linkedin.com/in/jane-doe"}]
    assert any("no Firecrawl" in w for w in warnings)


@pytest.mark.asyncio
async def test_enrich_empty_urls(monkeypatch):
    monkeypatch.setattr("app.services.linkedin_search.settings.firecrawl_api_key", "fake-key")
    profiles, warnings = await enrich_profile_urls([])
    assert profiles == []
    assert warnings == []


@pytest.mark.asyncio
async def test_enrich_firecrawl_credits_expired(monkeypatch):
    monkeypatch.setattr("app.services.linkedin_search.settings.firecrawl_api_key", "fake-key")

    async def mock_post(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 402
        resp.text = '{"error":"credits_exhausted"}'
        resp.request = MagicMock()
        raise httpx.HTTPStatusError("credits exhausted", request=resp.request, response=resp)

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = mock_post

    with patch("app.services.linkedin_search.httpx.AsyncClient", return_value=mock_client):
        profiles, warnings = await enrich_profile_urls(["https://www.linkedin.com/in/jane-doe"])

    assert profiles == [{"linkedin_url": "https://www.linkedin.com/in/jane-doe"}]
    assert any("credits" in w.lower() for w in warnings)
    assert any("402" in w for w in warnings)
