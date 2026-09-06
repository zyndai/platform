"""
Tests for the QuickEnrich MCP tools (backend/mcp/tools/quickenrich.py) — the
contact-database people/company discovery the persona uses alongside
search_zynd_personas and search_linkedin_people.

Everything below mocks the service layer, so no live API calls and no
Supabase are needed. The cache module is patched wholesale in most tests
because its real implementation talks to Supabase on every call.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mcp.tools import quickenrich as tools
from services import quickenrich as qe
from services import quickenrich_lookups as lookups


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _configured():
    """Pretend QuickEnrich is configured unless a test says otherwise."""
    with patch.object(tools.qe, "is_configured", return_value=True):
        yield


@pytest.fixture(autouse=True)
def _no_cache_io():
    """Neutralize the Supabase-backed cache; individual tests re-patch as needed."""
    with patch.object(tools.cache, "save_contacts", return_value=0), \
         patch.object(tools.cache, "save_contact", return_value="li:in/x"), \
         patch.object(tools.cache, "save_companies", return_value=0), \
         patch.object(tools.cache, "get_contact", return_value=None), \
         patch.object(tools.cache, "find_contact_by_email", return_value=None):
        yield


@pytest.fixture(autouse=True)
def _clear_lookup_cache():
    lookups.clear_cache()
    yield
    lookups.clear_cache()


CONTACT_FINDER_RESPONSE = {
    "success": True,
    "message": "Contacts fetched",
    "code": 200,
    "data": [
        {
            "first_name": "Jane",
            "last_name": "Doe",
            "title": "Chief Executive Officer",
            "employee_linkedin": "https://linkedin.com/in/janedoe",
            "has_email": True,
            "has_phone": False,
            "company_url": "https://example.com",
            "company_name": "Example Corp",
            "email_domain": "example.com",
            "home_page_email": "info@example.com",
            "city": "San Francisco",
            "locality": "San Francisco Bay Area",
            "country_code": "US",
        }
    ],
    "meta": {
        "page": 1, "per_page": 10, "total": 1, "last_page": 1,
        "credits_used": 0, "remaining_credits": 100,
        "next_cursor": None, "has_more": False,
    },
}


# ── search_people_database ───────────────────────────────────────────

def test_search_requires_at_least_one_filter():
    """contact-finder rejects an empty filter set, so we must not spend the call."""
    with patch.object(tools.qe, "contact_finder") as mock_call:
        result = tools.search_people_database(user_id="u1")

    assert result["status"] == "error"
    assert result["count"] == 0
    mock_call.assert_not_called()


def test_maps_contact_finder_response_to_flat_results():
    with patch.object(tools.qe, "contact_finder", return_value=CONTACT_FINDER_RESPONSE) as mock_call:
        result = tools.search_people_database(user_id="u1", titles=["CEO"], limit=10)

    assert result["status"] == "success"
    assert result["count"] == 1

    person = result["results"][0]
    assert person["name"] == "Jane Doe"
    assert person["linkedin_url"] == "https://linkedin.com/in/janedoe"
    assert person["company_name"] == "Example Corp"
    assert person["has_email"] is True
    assert person["has_phone"] is False
    # Discovery is free and must never leak a contact value it wasn't given.
    assert result["credits_used"] == 0
    assert "email" not in person

    body = mock_call.call_args[0][0]
    assert body["title"] == {"include": ["CEO"], "exclude": []}
    assert body["per_page"] == 10


def test_exclude_titles_land_in_the_exclude_list():
    with patch.object(tools.qe, "contact_finder", return_value=CONTACT_FINDER_RESPONSE) as mock_call:
        tools.search_people_database(user_id="u1", titles=["CEO"], exclude_titles=["Intern"])

    assert mock_call.call_args[0][0]["title"] == {"include": ["CEO"], "exclude": ["Intern"]}


def test_comma_separated_string_is_accepted_for_a_list_param():
    """Models pass arrays usually, but a comma string often enough to handle."""
    with patch.object(tools.qe, "contact_finder", return_value=CONTACT_FINDER_RESPONSE) as mock_call:
        tools.search_people_database(user_id="u1", titles="CEO, CTO")

    assert mock_call.call_args[0][0]["title"]["include"] == ["CEO", "CTO"]


def test_empty_result_set_gets_an_explanatory_note():
    empty = {"data": [], "meta": {"total": 0, "credits_used": 0}}
    with patch.object(tools.qe, "contact_finder", return_value=empty):
        result = tools.search_people_database(user_id="u1", titles=["Wizard"])

    assert result["status"] == "success"
    assert result["count"] == 0
    assert "note" in result


def test_not_configured_returns_a_clean_message_without_calling_out():
    with patch.object(tools.qe, "is_configured", return_value=False), \
         patch.object(tools.qe, "contact_finder") as mock_call:
        result = tools.search_people_database(user_id="u1", titles=["CEO"])

    assert result["status"] == "error"
    mock_call.assert_not_called()


# ── Enum resolution ──────────────────────────────────────────────────

def test_fuzzy_enum_values_are_rewritten_to_exact_ones():
    """'software' → 'Computer Software' and '50-200' → '51-200', or the API 422s."""
    def fake_lookup(path, params=None):
        if "industries" in path:
            return ["Computer Software", "Financial Services", "Marketing and Advertising"]
        if "employee-ranges" in path:
            return ["11-50", "51-200", "201-500"]
        if "country-codes" in path:
            return ["US", "GB", "DE"]
        return []

    with patch.object(lookups, "_lookup", side_effect=fake_lookup), \
         patch.object(tools.qe, "contact_finder", return_value=CONTACT_FINDER_RESPONSE) as mock_call:
        result = tools.search_people_database(
            user_id="u1",
            titles=["CEO"],
            industries=["software"],
            employee_ranges=["50-200"],
            countries=["us"],
        )

    body = mock_call.call_args[0][0]
    assert body["industry_linkedin"]["include"] == ["Computer Software"]
    assert body["number_of_employees"]["include"] == ["51-200"]
    assert body["country_code"]["include"] == ["US"]
    # The rewrites are reported so the persona can say what it actually searched.
    assert result["normalized_filters"]["industries"] == ["Computer Software"]


def test_unresolvable_enum_is_reported_with_suggestions_not_raised():
    def fake_lookup(path, params=None):
        if "industries" in path:
            return ["Computer Software", "Financial Services"]
        return []

    with patch.object(lookups, "_lookup", side_effect=fake_lookup), \
         patch.object(tools.qe, "contact_finder", return_value=CONTACT_FINDER_RESPONSE) as mock_call:
        result = tools.search_people_database(
            user_id="u1", titles=["CEO"], industries=["Underwater Basket Weaving"]
        )

    # The search still runs — we just drop the filter we couldn't map and say so.
    assert result["status"] == "success"
    assert result["unresolved_filters"][0]["value"] == "Underwater Basket Weaving"
    assert "industry_linkedin" not in mock_call.call_args[0][0]


def test_unreachable_lookup_passes_the_value_through():
    """A dead lookup endpoint must not block the search — let the API judge."""
    with patch.object(lookups, "_lookup", side_effect=RuntimeError("lookup down")), \
         patch.object(tools.qe, "contact_finder", return_value=CONTACT_FINDER_RESPONSE) as mock_call:
        tools.search_people_database(user_id="u1", titles=["CEO"], industries=["Computer Software"])

    assert mock_call.call_args[0][0]["industry_linkedin"]["include"] == ["Computer Software"]


def test_422_is_turned_into_an_actionable_message():
    with patch.object(
        tools.qe, "contact_finder",
        side_effect=qe.QuickEnrichValidationError("bad filter", status=422, body="{}"),
    ):
        result = tools.search_people_database(user_id="u1", titles=["CEO"])

    assert result["status"] == "error"
    assert "list_people_filter_values" in result["hint"]


# ── Enrichment ───────────────────────────────────────────────────────

EMAIL_RESPONSE = {
    "success": True,
    "data": {
        "first_name": "John",
        "last_name": "Doe",
        "title": "Senior Software Engineer",
        "email": "john.doe@company.com",
        "employee_phone": "+1-555-0123",
        "employee_linkedin": "https://linkedin.com/in/johndoe",
        "company_name": "Tech Corp",
        "company_url": "https://techcorp.com",
    },
    "meta": {"credits_used": 1, "remaining_credits": 99},
}


def test_email_lookup_needs_a_usable_identity():
    with patch.object(tools.qe, "employee_search") as mock_call:
        result = tools.get_email_for_person(user_id="u1", first_name="John")

    assert result["status"] == "error"
    mock_call.assert_not_called()


def test_email_lookup_returns_the_address_and_records_the_credit():
    with patch.object(tools.qe, "employee_search", return_value=EMAIL_RESPONSE):
        result = tools.get_email_for_person(
            user_id="u1", linkedin_url="https://linkedin.com/in/johndoe"
        )

    assert result["status"] == "success"
    assert result["cached"] is False
    assert result["credits_used"] == 1
    assert result["person"]["email"] == "john.doe@company.com"


def test_cache_hit_skips_the_paid_call():
    cached_row = {"email": "john.doe@company.com", "data": EMAIL_RESPONSE["data"]}
    with patch.object(tools.cache, "get_contact", return_value=cached_row), \
         patch.object(tools.qe, "employee_search") as mock_call:
        result = tools.get_email_for_person(
            user_id="u1", linkedin_url="https://linkedin.com/in/johndoe"
        )

    assert result["cached"] is True
    assert result["credits_used"] == 0
    assert result["person"]["email"] == "john.doe@company.com"
    mock_call.assert_not_called()


def test_no_records_is_a_clean_not_found_not_an_error():
    """A miss is a 200 with data: [] and credits_used: 0 — never an error."""
    miss = {"success": True, "data": [], "meta": {"credits_used": 0, "reason": "EMAIL_NOT_FOUND"}}
    with patch.object(tools.qe, "employee_search", return_value=miss):
        result = tools.get_email_for_person(
            user_id="u1", linkedin_url="https://linkedin.com/in/nobody"
        )

    assert result["status"] == "not_found"
    assert result["credits_used"] == 0


def test_reverse_lookup_rejects_a_non_email():
    with patch.object(tools.qe, "reverse_email_lookup") as mock_call:
        result = tools.identify_person_by_email(user_id="u1", email="not-an-email")

    assert result["success"] is False
    mock_call.assert_not_called()


# ── list_people_at_company ───────────────────────────────────────────

def test_company_contacts_require_a_domain():
    with patch.object(tools.qe, "dataset_search") as mock_call:
        result = tools.list_people_at_company(user_id="u1", company_url="  ")

    assert result["status"] == "error"
    mock_call.assert_not_called()


def test_company_contacts_pass_titles_through_as_a_comma_string():
    payload = {"data": [], "meta": {"page": 1, "last_page": 1, "credits_used": 0}}
    with patch.object(tools.qe, "dataset_search", return_value=payload) as mock_call:
        tools.list_people_at_company(user_id="u1", company_url="acme.com", titles=["CEO", "CFO"])

    assert mock_call.call_args.kwargs["title"] == "CEO, CFO"


# ── Field hygiene ────────────────────────────────────────────────────

def test_na_sentinel_is_treated_as_missing():
    """QuickEnrich writes the literal string 'N/A' rather than null."""
    shaped = tools._shape_person({
        "first_name": "Ann", "last_name": "Lee",
        "employee_phone": "N/A", "employee_phone_type": "N/A", "email": "ann@x.com",
    })

    assert "phone" not in shaped
    assert shaped["has_phone"] is False
    assert shaped["has_email"] is True


# ── list_people_filter_values ────────────────────────────────────────

def test_filter_values_accepts_plural_aliases():
    with patch.object(lookups, "_lookup", return_value=["Computer Software", "Financial Services"]):
        result = tools.list_people_filter_values(user_id="u1", dimension="industries")

    assert result["status"] == "success"
    assert result["dimension"] == "industry"
    assert "Computer Software" in result["values"]


def test_filter_values_rejects_an_unknown_dimension():
    result = tools.list_people_filter_values(user_id="u1", dimension="favourite_colour")
    assert result["status"] == "error"
    assert result["count"] == 0


# ── Cache key normalization ──────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://www.linkedin.com/in/janedoe/",
    "http://linkedin.com/in/janedoe",
    "linkedin.com/in/JaneDoe?utm=x",
])
def test_linkedin_urls_collapse_onto_one_cache_key(url):
    from services.quickenrich_cache import contact_key
    assert contact_key(linkedin_url=url) == "li:in/janedoe"


def test_contact_key_falls_back_through_email_then_name_and_company():
    from services.quickenrich_cache import contact_key
    assert contact_key(email="Jane@Acme.com") == "em:jane@acme.com"
    assert contact_key(
        company_url="https://www.acme.com/about", first_name="Jane", last_name="Doe"
    ) == "nc:acme.com|jane|doe"
    # Nothing stable to key on → not cacheable.
    assert contact_key(first_name="Jane") == ""


# ── Tool registration ────────────────────────────────────────────────

def test_all_seven_tools_are_registered_with_descriptions():
    """
    The LLM-facing text must live in the register() call — ContextAware
    truncates docstrings at 'Args:', so a missing description means the model
    sees an empty tool.
    """
    from mcp.server import mcp_server

    caps = {t["name"]: t for t in mcp_server.get_capabilities()["tools"]}
    expected = [
        "search_people_database", "search_companies_database", "list_people_at_company",
        "get_email_for_person", "get_phone_for_person", "identify_person_by_email",
        "list_people_filter_values",
    ]
    for name in expected:
        assert name in caps, f"{name} is not registered"
        assert len(caps[name]["description"]) > 80, f"{name} has no usable description"
        # user_id must be a declared param or the orchestrator can't inject it.
        assert "user_id" in [p["name"] for p in caps[name]["parameters"]]


def test_no_tool_declares_a_dict_param():
    """
    dict → a property-less JSON Schema `object`, which strict function-calling
    backends reject. The nested include/exclude shape is flattened instead.
    """
    from mcp.server import mcp_server

    caps = {t["name"]: t for t in mcp_server.get_capabilities()["tools"]}
    for name in ("search_people_database", "search_companies_database"):
        for param in caps[name]["parameters"]:
            assert param["type"] != "dict", f"{name}.{param['name']} is a dict"
