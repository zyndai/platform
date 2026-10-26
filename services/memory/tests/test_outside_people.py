"""POST /v1/service/outside-people: the one QuickEnrich client, used by Cards' suggestions."""
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.config import settings
from app.main import app
from app.services.people_query import query_from_filters

TOKEN = "service-token-for-tests"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(settings, "memory_service_token", TOKEN)

    async def call(body, token=TOKEN):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.post("/v1/service/outside-people", json=body, headers=headers)
    return call


async def test_requires_the_shared_service_token(api):
    assert (await api({"titles": ["Founder"]}, token=None)).status_code == 401
    assert (await api({"titles": ["Founder"]}, token="wrong")).status_code == 401


async def test_builds_the_search_from_structured_filters(api):
    people = [{"source": "quickenrich", "name": "Pat", "title": "Founder", "company": "Acme",
               "linkedin_url": "https://linkedin.com/in/pat"}]
    with patch("app.services.people_discovery.search_quickenrich", AsyncMock(return_value=(people, None))) as search:
        resp = await api({"titles": ["Founder", "Investor"], "keywords": ["AI"], "location": "Pune, India", "limit": 3})
    assert resp.status_code == 200 and resp.json()["warning"] is None
    (pat,) = resp.json()["people"]
    assert {k: pat[k] for k in people[0]} == people[0]            # the provider's fields are all still there
    (_, fetched), kwargs = search.await_args.args, search.await_args.kwargs
    assert fetched == 6                                            # twice the limit, room to drop wrong-role titles
    query = kwargs["query"]
    assert query.titles == ("Founder", "Investor") and query.topics == ("AI",)
    assert (query.country_code, query.locality) == ("IN", "Pune") and query.company_hint


QE_ROWS = [
    {"source": "quickenrich", "name": "Ivan Grievance", "title": "Investor Grievance Officer", "company": "Dayco Securities",
     "linkedin_url": "https://linkedin.com/in/ivan", "location": "Mumbai, India", "city": "Mumbai", "country_code": "IN"},
    {"source": "quickenrich", "name": "Anna Angel", "title": "Angel Investor", "company": "Self",
     "linkedin_url": "https://linkedin.com/in/anna", "location": "Berlin, Germany", "city": "Berlin", "country_code": "DE"},
    {"source": "quickenrich", "name": "Priya Partner", "title": "Venture Partner", "company": "Seed Fund",
     "linkedin_url": "https://linkedin.com/in/priya", "location": "Pune, India", "city": "Pune", "country_code": "IN"},
]


async def test_outside_people_are_ordered_by_fit_and_explain_themselves(api):
    with patch("app.services.people_discovery.search_quickenrich", AsyncMock(return_value=(QE_ROWS, None))):
        resp = await api({"titles": ["Investor"], "keywords": ["AI"], "location": "India", "limit": 5})
    people = resp.json()["people"]
    assert [p["name"] for p in people] == ["Priya Partner", "Anna Angel"]    # the grievance officer is not an investor
    priya, anna = people
    assert priya["score"] > anna["score"] > 0                                # in India beats not in India
    assert priya["location"] == "Pune, India" and priya["match_quality"] in ("exact", "close")
    assert priya["why"] and all(isinstance(w, str) for w in priya["why"]) and len(priya["why"]) <= 3
    assert priya["why"] == ["Investor (title)", "Pune, India"]       # a Venture Partner is an investor by title
    assert anna["why"] == ["Investor (headline)"]


async def test_titles_that_name_no_role_are_not_filtered_by_exclusions(api):
    rows = [{**QE_ROWS[0], "title": "Healthcare Grievance Lead"}]
    with patch("app.services.people_discovery.search_quickenrich", AsyncMock(return_value=(rows, None))):
        people = (await api({"titles": ["Healthcare"]})).json()["people"]
    assert [p["name"] for p in people] == ["Ivan Grievance"]


async def test_the_limit_applies_after_ranking(api):
    with patch("app.services.people_discovery.search_quickenrich", AsyncMock(return_value=(QE_ROWS, None))):
        people = (await api({"titles": ["Investor"], "location": "India", "limit": 1})).json()["people"]
    assert [p["name"] for p in people] == ["Priya Partner"]


async def test_an_empty_result_always_explains_itself(api, monkeypatch):
    monkeypatch.setattr(settings, "quickenrich_base_url", "")
    monkeypatch.setattr(settings, "quickenrich_api_key", "")
    resp = await api({"titles": ["Founder"]})
    assert resp.json() == {"people": [], "warning": "quickenrich_not_configured"}


async def test_rejects_oversized_or_unknown_input(api):
    assert (await api({"titles": ["a"] * 6})).status_code == 422
    assert (await api({"limit": 50})).status_code == 422
    assert (await api({"location": "x" * 200})).status_code == 422


def test_query_from_filters_resolves_places_and_trims():
    q = query_from_filters(titles=[" Founder ", "", 5], keywords=["AI", "  "], location="Bangalore")
    assert q.titles == ("Founder",) and q.topics == ("AI",)
    assert (q.location, q.country_code, q.locality) == ("Bengaluru", "IN", "Bengaluru")
    assert query_from_filters().country_code == "" and query_from_filters(location="nowhere-ville").country_code == ""


def test_a_title_that_names_a_role_gets_that_roles_title_filters():
    """People search Phase 2.5: Cards sends {"titles": ["Investor"]}; the request must use the
    investor row (include and exclude), or "Investor Grievance" officers come back."""
    from app.services.people_discovery import quickenrich_body
    from app.services.people_query import ROLE_TITLE_FILTERS

    q = query_from_filters(titles=["Investor"], keywords=["AI"])
    assert q.role == "investor"
    body = quickenrich_body(q, 4)
    assert body["title"] == {"include": list(ROLE_TITLE_FILTERS["investor"][0]),
                             "exclude": list(ROLE_TITLE_FILTERS["investor"][1])}
    assert "Grievance" in body["title"]["exclude"]
    assert query_from_filters(titles=["Machine Learning Engineer"]).role == "ml"
    assert query_from_filters(titles=["Developer Advocate"]).role == "devrel"
    # A title that names no known role keeps the titles as given, with nothing excluded.
    plain = query_from_filters(titles=["Healthcare"])
    assert plain.role == "" and quickenrich_body(plain, 4)["title"] == {"include": ["Healthcare"], "exclude": []}
