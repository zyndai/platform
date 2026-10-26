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
    # In India with an investor's title (a Principal at a fund counts), in the provider's order, as close
    # matches (a LinkedIn record cannot show the asked topic, AI); then, loose, the ones abroad, the
    # Principal at a consultancy and the person whose title is not an investor's. The grievance officer,
    # the duplicate and the nameless record are gone.
    assert names[:4] == ["Priya Partner", "Sam", "Gita General", "Pat Principal"]
    assert set(names[4:7]) == {"Anna Angel", "Leo Abroad", "Theo Consultant"} and names[7] == "Sal Sales"
    assert [p["match_quality"] for p in people] == ["close"] * 4 + ["loose"] * 4
    assert all(p["score"] <= 0.45 for p in people[4:])
    by = {p["name"]: p for p in people}
    assert by["Priya Partner"]["score"] == by["Pat Principal"]["score"] == 0.79        # 0.8 (a sure title), capped as close
    assert by["Pat Principal"]["score"] > by["Theo Consultant"]["score"]
    assert by["Anna Angel"]["score"] < by["Priya Partner"]["score"]                     # not in India


async def test_shaping_cleans_what_the_provider_sends_untidily(ranked):
    people, _ = await ranked()
    by = {p["name"]: p for p in people}
    assert by["Priya Partner"]["linkedin_url"] == "https://linkedin.com/in/priya-partner"    # the scheme was missing
    sam = by["Sam"]
    assert (sam["company"], sam["location"]) == ("", "Gurgaon, Haryana, India")             # N/A is nothing; the locality is theirs
    assert by["Gita General"]["location"] == "Bengaluru, India"                              # no locality: the city and the country
    assert by["Leo Abroad"]["location"] == "Los Altos, California, United States"           # not the office, not the company's country
    assert not any(p["location"].endswith("India, India") for p in people)
    assert all(p["linkedin_url"].startswith("https://") for p in people)
    assert all(p["has_email"] in (True, False) and "email" not in p for p in people)         # flags, never values


async def test_every_person_has_a_reason_and_a_quality(ranked):
    people, _ = await ranked()
    by = {p["name"]: p for p in people}
    assert by["Priya Partner"]["why"] == ["Investor (title)", "Pune, Maharashtra, India"]
    assert by["Sam"]["why"][0] == "Investor (headline)"
    assert by["Anna Angel"]["match_quality"] != "exact" and by["Sal Sales"]["match_quality"] == "loose"
    assert all(1 <= len(p["why"]) <= 3 for p in people)


async def test_the_limit_is_applied_after_the_wrong_ones_are_dropped(ranked):
    people, _ = await ranked(limit=2)
    assert [p["name"] for p in people] == ["Priya Partner", "Sam"]


def test_an_investor_request_with_nothing_about_the_company_drops_the_broad_titles():
    from app.services.people_query import ROLE_STRONG_TITLES, ROLE_TITLE_FILTERS, TargetQuery
    body = people_discovery.quickenrich_body(TargetQuery(raw="investor", role="investor"), 10)
    strong = [t for t in ROLE_TITLE_FILTERS["investor"][0] if t in ROLE_STRONG_TITLES["investor"]]
    assert body["title"]["include"] == strong and "Principal" not in strong and "Managing Partner" not in strong


def test_a_us_target_is_not_filtered_by_a_country_word_in_the_locality():
    from app.services.people_query import parse_target_heuristic
    body = people_discovery.quickenrich_body(parse_target_heuristic("seed investor in the USA"), 10)
    assert body["country_code"]["include"] == ["US"] and "locality" not in body   # "Richmond, Virginia" has no country
