"""
Tests for the new search_linkedin_people MCP tool (backend/mcp/tools/linkedin.py),
which wraps the harvestapi/linkedin-profile-search Apify actor for open-ended
role/keyword discovery on LinkedIn itself — distinct from search_zynd_personas,
which only covers people with a Zynd persona.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from mcp.tools.linkedin import search_linkedin_people


def test_empty_query_is_rejected_without_calling_apify():
    with patch("services.linkedin_scraper.search_people", new_callable=AsyncMock) as mock_search:
        result = search_linkedin_people(user_id="u1", query="   ")
    assert result["status"] == "error"
    assert result["count"] == 0
    mock_search.assert_not_called()


def test_maps_real_actor_output_shape():
    raw_items = [{
        "firstName": "Dana",
        "lastName": "Ortiz",
        "headline": "Founder & CEO at Nimbus AI",
        "location": {"linkedinText": "San Francisco, California"},
        "linkedinUrl": "https://www.linkedin.com/in/dana-ortiz",
        "currentPosition": [{"companyName": "Nimbus AI"}],
    }]

    with patch("services.linkedin_scraper.search_people", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = raw_items
        result = search_linkedin_people(user_id="u1", query="AI founders", location="San Francisco", top_k=5)

    assert result["status"] == "success"
    assert result["count"] == 1
    person = result["results"][0]
    assert person["name"] == "Dana Ortiz"
    assert person["headline"] == "Founder & CEO at Nimbus AI"
    assert person["location"] == "San Francisco, California"
    assert person["profile_url"] == "https://www.linkedin.com/in/dana-ortiz"
    assert person["current_company"] == "Nimbus AI"
    assert "warning" not in result

    # The location filter should have been forwarded to the scraper.
    _, kwargs = mock_search.call_args
    assert kwargs["locations"] == ["San Francisco"]


def test_mostly_empty_results_carry_a_warning():
    # Simulates the field-mapping being wrong against a future actor
    # version — the tool should flag that rather than presenting blanks
    # as confident "no strong candidates" results.
    raw_items = [
        {"someOtherField": "x"},
        {"anotherField": "y"},
    ]
    with patch("services.linkedin_scraper.search_people", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = raw_items
        result = search_linkedin_people(user_id="u1", query="AI founders")

    assert result["status"] == "success"
    assert "warning" in result


def test_apify_failure_returns_friendly_error():
    with patch("services.linkedin_scraper.search_people", new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = RuntimeError("APIFY_API_TOKEN is not configured")
        result = search_linkedin_people(user_id="u1", query="AI founders")

    assert "error" in result
    assert "error_message" in result
