"""LinkedIn people as the provider returns them, through the same steps the service endpoint uses
(people search plan 3.5: raw records -> shaped -> ranked by fit -> specific reasons)."""
import json
import pathlib
from unittest.mock import AsyncMock, patch

import pytest

from app.services import people_discovery, people_search
from app.services.people_query import query_from_filters

RECORDS = json.loads((pathlib.Path(__file__).parent / "fixtures" / "quickenrich_records.json").read_text())["records"]


@pytest.fixture
def ranked():
    """What POST /v1/service/outside-people returns for Investors in India who work on AI."""
    async def run(limit=10):
        query = query_from_filters(titles=["Investor"], keywords=["AI"], location="India")
        shaped = people_discovery._shape_qe(RECORDS)
        with patch("app.services.people_discovery._quickenrich_rows", AsyncMock(return_value=(shaped, None))), \
                patch.object(people_discovery.settings, "quickenrich_base_url", "https://qe.test"), \
                patch.object(people_discovery.settings, "quickenrich_api_key", "key"):
            return await people_search.outside(query, limit)
    return run


async def test_the_raw_records_come_out_in_the_order_of_how_well_they_fit(ranked):
    people, warning = await ranked()
    assert warning is None
    names = [p["name"] for p in people]
    # In India with a title the request asked for, in the provider's order; then the one abroad; then the
    # person whose title is not an investor's. The grievance officer, the duplicate and the nameless
    # record are gone.
    assert names == ["Priya Partner", "Sam", "Gita General", "Anna Angel", "Sal Sales"]
    scores = [p["score"] for p in people]
    assert scores == sorted(scores, reverse=True) and len(set(scores[:3])) <= 3
    assert people[0]["score"] > people[3]["score"] > people[4]["score"] > 0


async def test_shaping_cleans_what_the_provider_sends_untidily(ranked):
    people, _ = await ranked()
    by = {p["name"]: p for p in people}
    assert by["Priya Partner"]["linkedin_url"] == "https://linkedin.com/in/priya-partner"    # the scheme was missing
    sam = by["Sam"]
    assert (sam["company"], sam["location"]) == ("", "Gurgaon, India")                      # N/A is nothing; a locality is a place
    assert by["Gita General"]["location"] == "Bengaluru, India"                              # a city, and a country by name
    assert all(p["linkedin_url"].startswith("https://") for p in people)
    assert all(p["has_email"] in (True, False) and "email" not in p for p in people)         # flags, never values


async def test_every_person_has_a_reason_and_a_quality(ranked):
    people, _ = await ranked()
    by = {p["name"]: p for p in people}
    assert by["Priya Partner"]["why"] == ["Investor (title)", "Pune, India"]
    assert by["Sam"]["why"][0] == "Investor (headline)"
    assert by["Anna Angel"]["match_quality"] != "exact" and by["Sal Sales"]["match_quality"] == "loose"
    assert all(1 <= len(p["why"]) <= 3 for p in people)


async def test_the_limit_is_applied_after_the_wrong_ones_are_dropped(ranked):
    people, _ = await ranked(limit=2)
    assert [p["name"] for p in people] == ["Priya Partner", "Sam"]
