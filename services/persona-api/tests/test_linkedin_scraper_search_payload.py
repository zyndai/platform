"""
Regression test: LinkedIn people search always came back empty regardless
of query, because the harvestapi/linkedin-profile-search actor's `takePages`
input has no default — omit it and the actor scrapes zero result pages no
matter what `searchQuery`/`maxItems` say. Confirmed directly against the
actor's real input schema (fetched from Apify's API) and against a live
run showing 0 dataset items with `takePages` unset. This locks in that the
payload always includes a `takePages` derived from `max_items`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.linkedin_scraper import search_people


@pytest.mark.asyncio
async def test_payload_includes_take_pages_covering_max_items():
    with patch("services.linkedin_scraper._run_actor", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = []
        await search_people(query="cybersecurity", max_items=10)

    args, _ = mock_run.call_args
    actor_id, payload = args
    assert payload["takePages"] >= 1
    assert payload["maxItems"] == 10


@pytest.mark.asyncio
async def test_take_pages_scales_past_one_page_of_25():
    with patch("services.linkedin_scraper._run_actor", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = []
        await search_people(query="founder", max_items=20)

    _, payload = mock_run.call_args.args
    # maxItems is clamped to 20 internally; a single page (25) already
    # covers it, so takePages should still be exactly 1, not over-request.
    assert payload["takePages"] == 1


@pytest.mark.asyncio
async def test_query_and_locations_still_forwarded():
    with patch("services.linkedin_scraper._run_actor", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = []
        await search_people(query="AI founder", locations=["Berlin"], max_items=5)

    _, payload = mock_run.call_args.args
    assert payload["searchQuery"] == "AI founder"
    assert payload["locations"] == ["Berlin"]
    assert payload["profileScraperMode"] == "Short"
