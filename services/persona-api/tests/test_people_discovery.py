"""Mock-only tests for independent, read-only people discovery."""

from unittest.mock import Mock, patch

import requests

from mcp.tools import people_discovery as discovery


def test_cards_request_claimed_canonical_handles_and_no_trusted_api_url():
    response = Mock()
    response.json.return_value = {"results": [
        {"agent_id": "card-1", "handle": "jane-doe", "claimed": True, "name": "Jane", "url": "https://evil.example/p/jane",
         "match_score": 0.9, "location": "Austin", "skills": ["AI", "Strategy"],
         "match_reasons": [{"type": "memory", "text": "Builds AI products"}, "Matches your search terms"]},
        {"agent_id": "card-2", "handle": "unclaimed", "claimed": False},
        {"agent_id": "card-3", "handle": "../bad", "claimed": True},
        {"agent_id": "card-4", "handle": "jane-doe", "claimed": True},
    ]}
    with patch.object(discovery.requests, "get", return_value=response) as get:
        result = discovery.search_zynd_cards("founders", limit=2)
    get.assert_called_once_with(
        "https://api.zynd.ai/v1/agents/search",
        params={"q": "founders", "limit": 10, "include_unclaimed": "false"}, timeout=8,
    )
    assert result["status"] == "success"
    assert result["count"] == 1
    assert result["results"][0]["public_url"] == "https://cards.zynd.ai/p/jane-doe"
    assert result["results"][0]["source_id"] == "card-1"
    assert result["results"][0]["connection_eligible"] is False
    assert result["results"][0]["match_score"] == 0.9
    assert result["results"][0]["location"] == "Austin"
    assert result["results"][0]["skills"] == ["AI", "Strategy"]
    assert result["results"][0]["match_reasons"] == [
        {"type": "memory", "text": "Builds AI products"}, "Matches your search terms",
    ]


def test_cards_config_override_and_failures():
    with patch.object(discovery.config, "CARDS_API_BASE_URL", "https://cards-api.example/"), \
         patch.object(discovery.requests, "get", side_effect=requests.Timeout) as get:
        assert discovery.search_zynd_cards("people")["status"] == "timeout"
        assert get.call_args.args[0] == "https://cards-api.example/v1/agents/search"
    with patch.object(discovery.requests, "get", side_effect=requests.HTTPError):
        assert discovery.search_zynd_cards("people")["status"] == "unavailable"
    with patch.object(discovery.requests, "get", return_value=Mock(**{"json.return_value": {"results": {}}})):
        assert discovery.search_zynd_cards("people")["status"] == "bad_response"


def test_cards_invalid_query_never_calls_http():
    with patch.object(discovery.requests, "get") as get:
        assert discovery.search_zynd_cards(" ")["status"] == "error"
        assert discovery.search_zynd_cards("AI", limit=11)["status"] == "error"
    get.assert_not_called()


def test_composite_searches_each_source_once_even_with_network_hits():
    network = {"status": "success", "results": [{
        "agent_id": "persona-1", "name": "Jane", "webhook_url": "https://host.example/a2a",
        "match_reason": "founder", "match_score": 0.95, "public_url": "http://localhost:8080/internal",
    }]}
    cards = {"status": "success", "count": 1, "results": [{"source_id": "card-1", "name": "Jane", "public_url": "https://cards.zynd.ai/p/jane"}]}
    external = {"status": "success", "results": [{
        "name": "Jane", "title": "Founder", "linkedin_url": "https://linkedin.com/in/jane",
        "email": "secret@example.org", "phone": "123", "company_url": "https://host.example/webhook",
        "has_email": True, "has_phone": False, "city": "Austin", "locality": "Central Texas",
        "country": "US", "industry": "Software", "company_size": "51-200",
    }], "normalized_filters": {"industries": ["Software"]}, "unresolved_filters": [{"value": "unknown"}], "total": 1}
    with patch.object(discovery, "search_zynd_personas", return_value=network) as personas, \
         patch.object(discovery, "search_zynd_cards", return_value=cards) as search_cards, \
         patch.object(discovery, "search_people_database", return_value=external) as people:
        result = discovery.discover_people("user-1", "AI founders", {"titles": ["Founder"]})
    personas.assert_called_once_with("AI founders", top_k=8, user_id="user-1")
    search_cards.assert_called_once_with("AI founders", limit=8)
    people.assert_called_once_with("user-1", titles=["Founder"], limit=8)
    assert result["zynd_network"]["results"][0]["connection_eligible"] is True
    assert result["zynd_network"]["results"][0]["agent_id"] == "persona-1"
    assert result["zynd_network"]["results"][0]["source_id"] == "persona-1"
    assert result["zynd_network"]["results"][0]["match_score"] == 0.95
    assert result["zynd_network"]["results"][0]["public_url"] is None
    assert result["zynd_cards"]["count"] == 1
    prospect = result["external_prospects"]["results"][0]
    assert prospect["public_url"] == "https://linkedin.com/in/jane"
    assert prospect["connection_eligible"] is False
    assert prospect["has_email"] is True
    assert prospect["has_phone"] is False
    assert (prospect["city"], prospect["locality"], prospect["country"]) == ("Austin", "Central Texas", "US")
    assert (prospect["industry"], prospect["company_size"]) == ("Software", "51-200")
    assert "secret@example.org" not in str(result)
    assert "phone': '123'" not in str(result)
    assert "webhook" not in str(result)
    assert result["external_prospects"]["unresolved_filters"] == [{"value": "unknown"}]


def test_missing_criteria_and_network_only_do_not_call_external():
    with patch.object(discovery, "search_zynd_personas", return_value={"status": "success", "results": []}) as network, \
         patch.object(discovery, "search_zynd_cards", return_value={"status": "success", "results": []}) as cards, \
         patch.object(discovery, "search_people_database") as external:
        missing = discovery.discover_people("u", "AI", {"exclude_titles": ["Intern"]})
        restricted = discovery.discover_people("u", "AI", {"titles": ["CEO"]}, network_only=True)
    assert missing["external_prospects"]["status"] == "needs_criteria"
    assert restricted["external_prospects"]["status"] == "skipped"
    assert restricted["zynd_cards"]["status"] == "skipped"
    assert network.call_count == 2
    assert cards.call_count == 1
    external.assert_not_called()


def test_rejects_invalid_inputs_before_any_call():
    with patch.object(discovery, "search_zynd_personas") as network, \
         patch.object(discovery, "search_zynd_cards") as cards, \
         patch.object(discovery, "search_people_database") as external:
        for kwargs in ({"query": ""}, {"query": "AI", "limit": 11},
                       {"query": "AI", "people_filters": {"has_email": True}},
                       {"query": "AI", "people_filters": {"titles": "CEO"}}):
            assert discovery.discover_people("u", **kwargs)["status"] == "error"
    network.assert_not_called()
    cards.assert_not_called()
    external.assert_not_called()


def test_source_failures_remain_independent_and_unresolved_preserved():
    with patch.object(discovery, "search_zynd_personas", side_effect=RuntimeError("secret endpoint")), \
         patch.object(discovery, "search_zynd_cards", return_value={"status": "timeout", "count": 0, "results": []}), \
         patch.object(discovery, "search_people_database", return_value={
             "status": "error", "results": [], "error": "invalid filter", "unresolved_filters": [{"dimension": "industry"}],
         }):
        result = discovery.discover_people("u", "AI", {"industries": ["wrong"]})
    assert result["zynd_network"]["status"] == "unavailable"
    assert result["zynd_cards"]["status"] == "timeout"
    assert result["external_prospects"]["unresolved_filters"] == [{"dimension": "industry"}]


def test_upstream_errors_without_results_keep_original_status_and_message():
    with patch.object(discovery, "search_zynd_personas", return_value={
        "status": "error", "error_message": "Registry unavailable",
    }), patch.object(discovery, "search_zynd_cards", return_value={
        "status": "success", "count": 0, "results": [],
    }), patch.object(discovery, "search_people_database", return_value={
        "status": "not_configured", "error_message": "QuickEnrich not configured", "hint": "Configure service",
    }):
        result = discovery.discover_people("u", "AI", {"titles": ["CTO"]})
    assert result["zynd_network"]["status"] == "error"
    assert result["zynd_network"]["error"] == "Registry unavailable"
    assert result["external_prospects"]["status"] == "not_configured"
    assert result["external_prospects"]["error"] == "QuickEnrich not configured"
    assert result["external_prospects"]["hint"] == "Configure service"


def test_public_urls_reject_internal_links_and_operational_paths():
    for url in ("javascript:alert(1)", "http://localhost/profile", "http://10.0.0.1/p/a",
                "https://example.com/a2a/v1", "https://example.com/api/contacts",
                "https://user:pass@example.com/p/a", "https://example.com:8080/p/a"):
        assert discovery._public_url(url) is None
    assert discovery._public_url("https://linkedin.com/in/jane") == "https://linkedin.com/in/jane"
    assert discovery._public_text("Jane https://example.com/webhook secret") == "Jane  secret"
