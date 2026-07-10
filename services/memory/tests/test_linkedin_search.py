"""Tests for app/services/linkedin_search.py — async Exa / Tavily / Firecrawl integration."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.linkedin_search import (
    _extract_profile_urls,
    _parse_profile_markdown,
    build_query_from_context,
    search_linkedin_profile_urls,
)


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
    # "backend engineer" appears only once
    assert query.lower().count("backend engineer") == 1


def test_build_query_empty():
    assert build_query_from_context([]) == ""
    assert build_query_from_context([{"statement": ""}]) == ""


# ── Exa search (mocked) ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_linkedin_exa_requires_api_key(monkeypatch):
    monkeypatch.setattr("app.services.linkedin_search.settings.exa_api_key", "")
    monkeypatch.setattr("app.services.linkedin_search.settings.tavily_api_key", "")
    result = await search_linkedin_profile_urls("senior engineers fintech", num_results=5)
    assert result == []


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
        result = await search_linkedin_profile_urls("senior engineers fintech", num_results=5)

    assert result == [
        "https://www.linkedin.com/in/jane-doe",
        "https://www.linkedin.com/in/john-smith",
    ]


@pytest.mark.asyncio
async def test_search_linkedin_fallback_to_tavily(monkeypatch):
    monkeypatch.setattr("app.services.linkedin_search.settings.exa_api_key", "fake-exa")
    monkeypatch.setattr("app.services.linkedin_search.settings.tavily_api_key", "fake-tavily")

    # Exa fails, Tavily succeeds
    exa_resp = MagicMock()
    exa_resp.raise_for_status = MagicMock(side_effect=Exception("exa down"))

    tavily_resp = MagicMock()
    tavily_resp.raise_for_status = MagicMock()
    tavily_resp.json.return_value = {
        "results": [{"url": "https://www.linkedin.com/in/carol-t"}]
    }

    call_count = {"count": 0}

    async def mock_post(url, **kwargs):
        call_count["count"] += 1
        if "exa.ai" in url:
            raise Exception("exa down")
        return tavily_resp

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = mock_post

    with patch("app.services.linkedin_search.httpx.AsyncClient", return_value=mock_client):
        result = await search_linkedin_profile_urls("ML researchers", num_results=5)

    assert result == ["https://www.linkedin.com/in/carol-t"]
    assert call_count["count"] >= 2  # Exa tried + Tavily tried
