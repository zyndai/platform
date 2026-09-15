"""
Tests for the People-suggestions generator (backend/services/people_suggestions.py)
— the proactive "Similar people" shortlist behind the People page's section
of that name and the get_suggested_people chat tool.

Supabase and the QuickEnrich HTTP layer are both mocked; search_people_database
itself is mocked wholesale (it already has its own coverage in
test_quickenrich_tools.py) so these tests focus on recipe construction,
merging/dedup/scoring across recipes, self-exclusion, the LLM-planning
fallback, and the read-side grouping shape.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services import people_suggestions


# ── Supabase mocking helpers ─────────────────────────────────────────

class _Resp:
    def __init__(self, data):
        self.data = data


def _make_table(rows):
    chain = MagicMock()
    for method in ("select", "eq", "limit", "order", "in_", "delete", "insert", "upsert"):
        getattr(chain, method).return_value = chain
    chain.execute.return_value = _Resp(rows)
    return chain


def _mock_supabase(tables: dict):
    """`tables` maps table name -> rows to return from .execute(). Any table
    not listed returns an empty result."""
    sb = MagicMock()
    made = {name: _make_table(rows) for name, rows in tables.items()}
    sb.table.side_effect = lambda name: made.get(name, _make_table([]))
    return sb, made


def _person(first, last, linkedin_url, *, company_url="https://acme.com",
            has_email=False, has_phone=False):
    return {
        "name": f"{first} {last}",
        "first_name": first,
        "last_name": last,
        "linkedin_url": linkedin_url,
        "company_url": company_url,
        "has_email": has_email,
        "has_phone": has_phone,
    }


# ── collect_signals ──────────────────────────────────────────────────

def test_collect_signals_merges_persona_and_linkedin_and_derives_city():
    """
    Uses the actual harvestapi profile-actor shape confirmed against a live
    scrape row: experience[0]'s job title is under "position" (not
    "title"), and "location" is a nested {parsed: {city, text, ...},
    linkedinText} object rather than a plain string. Both were silently
    broken before — this fixture guards against regressing either.
    """
    sb, _ = _mock_supabase({
        "persona_agents": [{"profile": {
            "title": "", "organization": "", "location": "",
            "interests": "AI agents, fintech",
        }}],
        "linkedin_profiles": [{
            "profile_url": "https://linkedin.com/in/jane",
            "raw_profile": {
                "experience": [{"position": "CTO", "companyName": "Acme Inc"}],
                "location": {
                    "parsed": {"city": "Austin", "text": "Austin, TX, United States"},
                    "linkedinText": "Greater Austin Area",
                },
                "skills": [{"name": "Python"}, {"name": "LLMs"}],
            },
        }],
    })
    with patch.object(people_suggestions, "_sb", return_value=sb):
        signals = people_suggestions.collect_signals("u1")

    assert signals["title"] == "CTO"
    assert signals["organization"] == "Acme Inc"
    assert signals["location"] == "Austin, TX, United States"
    assert signals["city"] == "Austin"
    assert signals["interests"] == ["AI agents", "fintech"]
    assert signals["skills"] == ["Python", "LLMs"]
    assert signals["own_linkedin_url"] == "https://linkedin.com/in/jane"


def test_location_text_handles_nested_object_plain_string_and_missing():
    nested = {
        "parsed": {"city": "Washington", "text": "Washington, DC, United States"},
        "linkedinText": "Washington DC-Baltimore Area",
    }
    assert people_suggestions._location_text(nested) == "Washington, DC, United States"
    assert people_suggestions._location_text("Austin, TX") == "Austin, TX"
    assert people_suggestions._location_text({"linkedinText": "Bay Area"}) == "Bay Area"
    assert people_suggestions._location_text(None) == ""
    assert people_suggestions._location_text({}) == ""


def test_collect_signals_tolerates_missing_rows():
    sb, _ = _mock_supabase({"persona_agents": [], "linkedin_profiles": []})
    with patch.object(people_suggestions, "_sb", return_value=sb):
        signals = people_suggestions.collect_signals("u1")

    assert signals["title"] == ""
    assert signals["skills"] == []
    assert signals["own_linkedin_url"] == ""


# ── build_recipes ────────────────────────────────────────────────────

def test_build_recipes_from_full_signals():
    signals = {
        "title": "CTO", "organization": "Acme Inc", "location": "Austin, TX",
        "city": "Austin", "interests": [], "skills": [], "own_linkedin_url": "",
    }
    recipes = people_suggestions.build_recipes(signals)
    keys = [r["key"] for r in recipes]

    assert "same_role" in keys
    assert "same_company" in keys
    assert "near_you" in keys
    assert "shared_interests" not in keys  # no interests/skills to plan from

    same_role = next(r for r in recipes if r["key"] == "same_role")
    assert same_role["filters"] == {"titles": ["CTO"]}

    same_company = next(r for r in recipes if r["key"] == "same_company")
    assert same_company["filters"] == {"company_names": ["Acme Inc"]}

    near_you = next(r for r in recipes if r["key"] == "near_you")
    assert near_you["filters"] == {"cities": ["Austin"], "titles": ["CTO"]}


def test_build_recipes_omits_recipes_with_nothing_to_search_on():
    signals = {
        "title": "", "organization": "", "location": "", "city": "",
        "interests": [], "skills": [], "own_linkedin_url": "",
    }
    recipes = people_suggestions.build_recipes(signals)
    assert recipes == []


def test_build_recipes_near_you_without_title():
    signals = {
        "title": "", "organization": "", "location": "Austin, TX",
        "city": "Austin", "interests": [], "skills": [], "own_linkedin_url": "",
    }
    recipes = people_suggestions.build_recipes(signals)
    near_you = next(r for r in recipes if r["key"] == "near_you")
    assert near_you["filters"] == {"cities": ["Austin"]}


# ── shared_interests planning ────────────────────────────────────────

def test_plan_shared_interests_returns_none_without_interests_or_skills():
    signals = {"title": "CTO", "interests": [], "skills": []}
    assert people_suggestions._plan_shared_interests(signals) is None


def test_plan_shared_interests_falls_back_when_llm_unavailable():
    signals = {"title": "CTO", "interests": ["AI agents", "fintech"], "skills": []}
    with patch("agent.orchestrator._get_provider", side_effect=RuntimeError("no provider")):
        recipe = people_suggestions._plan_shared_interests(signals)

    assert recipe is not None
    assert recipe["key"] == "shared_interests"
    assert recipe["filters"]["company_keywords"] == ["AI agents", "fintech"]
    assert recipe["filters"]["titles"] == ["CTO"]
    assert "AI agents" in recipe["reason"]


def test_plan_shared_interests_uses_llm_json_when_available():
    signals = {"title": "CTO", "interests": ["fintech"], "skills": []}
    provider = MagicMock()
    provider.chat_with_tools.return_value = (
        '{"titles": ["Founder", "Head of Product"], "industries": ["Financial Services"], '
        '"company_keywords": ["payments"], "reason": "Also building in fintech"}',
        None,
    )
    with patch("agent.orchestrator._get_provider", return_value=provider):
        recipe = people_suggestions._plan_shared_interests(signals)

    assert recipe["filters"]["titles"] == ["Founder", "Head of Product"]
    assert recipe["filters"]["industries"] == ["Financial Services"]
    assert recipe["filters"]["company_keywords"] == ["payments"]
    assert recipe["reason"] == "Also building in fintech"


def test_plan_shared_interests_falls_back_on_unparseable_llm_output():
    signals = {"title": "CTO", "interests": ["fintech"], "skills": []}
    provider = MagicMock()
    provider.chat_with_tools.return_value = ("not json at all", None)
    with patch("agent.orchestrator._get_provider", return_value=provider):
        recipe = people_suggestions._plan_shared_interests(signals)

    assert recipe["filters"]["company_keywords"] == ["fintech"]


# ── run_for_user ─────────────────────────────────────────────────────

def test_run_for_user_skips_when_not_configured():
    with patch.object(people_suggestions.qe, "is_configured", return_value=False), \
         patch.object(people_suggestions, "_stamp_run") as mock_stamp:
        result = people_suggestions.run_for_user("u1")

    assert result["status"] == "skipped"
    assert result["reason"] == "not_configured"
    mock_stamp.assert_called_once()
    assert mock_stamp.call_args.kwargs["status"] == "skipped"


def test_run_for_user_skips_when_no_signals():
    with patch.object(people_suggestions.qe, "is_configured", return_value=True), \
         patch.object(people_suggestions, "collect_signals", return_value={}), \
         patch.object(people_suggestions, "_stamp_run") as mock_stamp:
        result = people_suggestions.run_for_user("u1")

    assert result["status"] == "skipped"
    assert result["reason"] == "no_signals"
    mock_stamp.assert_called_once()


def test_run_for_user_excludes_self_dedups_across_recipes_and_ranks():
    signals = {
        "title": "CTO", "organization": "Acme Inc", "location": "Austin, TX",
        "city": "Austin", "interests": [], "skills": [],
        "own_linkedin_url": "https://linkedin.com/in/self",
    }

    def fake_search(user_id, **filters):
        filters.pop("limit", None)
        if filters == {"titles": ["CTO"]}:
            return {"status": "success", "results": [
                _person("Jane", "Doe", "https://linkedin.com/in/janedoe", has_email=True),
                _person("Bob", "Lee", "https://linkedin.com/in/boblee"),
            ]}
        if filters == {"company_names": ["Acme Inc"]}:
            # Jane also works at the user's own company — should end up
            # counted once, under the more specific same_company recipe.
            return {"status": "success", "results": [
                _person("Jane", "Doe", "https://linkedin.com/in/janedoe", has_email=True),
            ]}
        if filters == {"cities": ["Austin"], "titles": ["CTO"]}:
            # The user themselves shows up in their own city search.
            return {"status": "success", "results": [
                _person("Self", "Person", "https://linkedin.com/in/self"),
            ]}
        return {"status": "success", "results": []}

    with patch.object(people_suggestions, "collect_signals", return_value=signals), \
         patch.object(people_suggestions.qe, "is_configured", return_value=True), \
         patch.object(people_suggestions, "_replace_suggestions") as mock_replace, \
         patch.object(people_suggestions, "_stamp_run") as mock_stamp, \
         patch("mcp.tools.quickenrich.search_people_database", side_effect=fake_search):
        result = people_suggestions.run_for_user("u1")

    assert result["status"] == "success"
    sections_by_key = {s["key"]: s for s in result["recipes"]}

    # Jane matched both same_role and same_company; same_company wins (higher
    # priority) so she appears there, not under same_role.
    assert "same_company" in sections_by_key
    company_names = [p["first_name"] for p in sections_by_key["same_company"]["items"]]
    assert company_names == ["Jane"]

    assert "same_role" in sections_by_key
    role_names = [p["first_name"] for p in sections_by_key["same_role"]["items"]]
    assert role_names == ["Bob"]  # Jane deduped out of this section

    # The user's own record was excluded entirely — near_you has nothing left.
    assert "near_you" not in sections_by_key

    mock_replace.assert_called_once()
    rows = mock_replace.call_args[0][1]
    assert len(rows) == 2
    assert {r["recipe"] for r in rows} == {"same_company", "same_role"}

    assert mock_stamp.call_args.kwargs["status"] == "ok"


def test_run_for_user_handles_a_recipe_erroring_without_failing_the_others():
    signals = {
        "title": "CTO", "organization": "", "location": "", "city": "",
        "interests": [], "skills": [], "own_linkedin_url": "",
    }

    def fake_search(user_id, **filters):
        raise RuntimeError("boom")

    with patch.object(people_suggestions, "collect_signals", return_value=signals), \
         patch.object(people_suggestions.qe, "is_configured", return_value=True), \
         patch.object(people_suggestions, "_replace_suggestions") as mock_replace, \
         patch.object(people_suggestions, "_stamp_run"), \
         patch("mcp.tools.quickenrich.search_people_database", side_effect=fake_search):
        result = people_suggestions.run_for_user("u1")

    assert result["status"] == "success"
    assert result["count"] == 0
    mock_replace.assert_called_once_with("u1", [])


# ── get_suggestions ──────────────────────────────────────────────────

def test_get_suggestions_groups_by_recipe_and_joins_enriched_contacts():
    suggested_rows = [
        {"cache_key": "li:in/janedoe", "recipe": "same_company",
         "reason": "Colleagues at Acme Inc", "rank": 0},
        {"cache_key": "li:in/boblee", "recipe": "same_role",
         "reason": "Also working as CTO", "rank": 0},
    ]
    contact_rows = [
        {"cache_key": "li:in/janedoe", "data": {
            "first_name": "Jane", "last_name": "Doe",
            "employee_linkedin": "https://linkedin.com/in/janedoe",
            "company_name": "Acme Inc", "has_email": True,
        }},
        {"cache_key": "li:in/boblee", "data": {
            "first_name": "Bob", "last_name": "Lee",
            "employee_linkedin": "https://linkedin.com/in/boblee",
            "company_name": "Other Co", "has_email": False,
        }},
    ]
    run_rows = [{"last_run_at": "2026-09-10T00:00:00+00:00", "status": "ok"}]

    sb, _ = _mock_supabase({
        "suggested_contacts": suggested_rows,
        "enriched_contacts": contact_rows,
        "suggested_contact_runs": run_rows,
    })

    with patch.object(people_suggestions, "_sb", return_value=sb):
        result = people_suggestions.get_suggestions("u1")

    assert result["status"] == "success"
    assert result["generated_at"] == "2026-09-10T00:00:00+00:00"
    sections_by_key = {s["key"]: s for s in result["sections"]}
    assert sections_by_key["same_company"]["items"][0]["name"] == "Jane Doe"
    assert sections_by_key["same_role"]["items"][0]["name"] == "Bob Lee"
    assert sections_by_key["same_company"]["reason"] == "Colleagues at Acme Inc"


def test_get_suggestions_empty_when_nothing_generated():
    sb, _ = _mock_supabase({
        "suggested_contacts": [], "suggested_contact_runs": [],
    })
    with patch.object(people_suggestions, "_sb", return_value=sb):
        result = people_suggestions.get_suggestions("u1")

    assert result["status"] == "empty"
    assert result["sections"] == []
    assert result["can_refresh"] is True


# ── refresh cooldown ─────────────────────────────────────────────────

def test_refresh_cooldown_seconds_zero_when_never_run():
    sb, _ = _mock_supabase({"suggested_contact_runs": []})
    with patch.object(people_suggestions, "_sb", return_value=sb):
        assert people_suggestions.refresh_cooldown_seconds("u1") == 0


def test_refresh_cooldown_seconds_positive_right_after_a_manual_run():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    sb, _ = _mock_supabase({
        "suggested_contact_runs": [{"last_manual_at": now}],
    })
    with patch.object(people_suggestions, "_sb", return_value=sb):
        cooldown = people_suggestions.refresh_cooldown_seconds("u1")

    assert 0 < cooldown <= people_suggestions.MANUAL_COOLDOWN_SECONDS


def test_is_due_true_when_never_run():
    assert people_suggestions.is_due({}, interval_seconds=100) is True


def test_is_due_false_when_recently_run():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    assert people_suggestions.is_due({"last_run_at": now}, interval_seconds=3600) is False
