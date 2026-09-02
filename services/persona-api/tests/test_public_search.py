"""
Tests for the public people-search API (backend/api/public_search.py).

Endpoint tested by direct call with mocked search backends and a fake
request object (the repo's tests don't use TestClient). Also unit-tests
search_similar_people's ranking with Supabase/avatars stubbed.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from api.public_search import PeopleSearchRequest, search_people, search_people_get
from mcp.tools.zynd_network import search_similar_people


def _fake_request(ip: str = "1.2.3.4", fwd: str | None = None) -> SimpleNamespace:
    headers = {"x-forwarded-for": fwd} if fwd else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=ip))


def _run(coro):
    return asyncio.run(coro)


# ── Endpoint ──────────────────────────────────────────────────────────


def test_domain_mode_passes_through_to_persona_search():
    fake_result = {"status": "success", "count": 2, "results": [{"name": "Alice", "agent_id": "a1"}]}
    with patch("api.public_search.search_zynd_personas", return_value=fake_result) as mock_search:
        result = _run(search_people(
            PeopleSearchRequest(query="AI founders", mode="domain", limit=5),
            _fake_request(),
        ))
    mock_search.assert_called_once_with("AI founders", 5, "")
    assert result["status"] == "success"
    assert result["mode"] == "domain"
    assert result["limit"] == 5


def test_similar_mode_uses_similar_people_search():
    fake_result = {"status": "success", "count": 1, "results": [{"name": "Bob", "agent_id": "b2"}]}
    with patch("api.public_search.search_similar_people", return_value=fake_result) as mock_search:
        result = _run(search_people(
            PeopleSearchRequest(query="climate tech founder", mode="similar", limit=3),
            _fake_request(),
        ))
    mock_search.assert_called_once_with("climate tech founder", 3)
    assert result["mode"] == "similar"
    assert result["results"][0]["name"] == "Bob"


def test_empty_query_422():
    with pytest.raises(HTTPException) as exc:
        _run(search_people(PeopleSearchRequest(query="   ", mode="domain"), _fake_request()))
    assert exc.value.status_code == 422


def test_invalid_mode_rejected_by_schema():
    with pytest.raises(ValueError):
        PeopleSearchRequest(query="x", mode="banana")


def test_limit_clamped_by_schema():
    with pytest.raises(ValueError):
        PeopleSearchRequest(query="x", limit=999)
    assert PeopleSearchRequest(query="x", limit=40).limit == 40


def test_rate_limit_returns_429():
    import api.public_search as ps

    ps._hits.clear()
    old_max = ps._MAX_PER_WINDOW
    ps._MAX_PER_WINDOW = 2
    try:
        with patch("api.public_search.search_zynd_personas", return_value={"status": "success", "results": []}):
            req = _fake_request()
            _run(search_people(PeopleSearchRequest(query="a"), req))
            _run(search_people(PeopleSearchRequest(query="b"), req))
            with pytest.raises(HTTPException) as exc:
                _run(search_people(PeopleSearchRequest(query="c"), req))
            assert exc.value.status_code == 429
    finally:
        ps._MAX_PER_WINDOW = old_max
        ps._hits.clear()


def test_client_ip_prefers_x_forwarded_for():
    from api.public_search import _client_ip

    assert _client_ip(_fake_request(fwd="9.9.9.9, 10.0.0.1")) == "9.9.9.9"
    assert _client_ip(_fake_request()) == "1.2.3.4"


# ── GET variant ───────────────────────────────────────────────────────


def test_get_variant_domain_passthrough():
    fake_result = {"status": "success", "count": 1, "results": [{"name": "Alice", "agent_id": "a1"}]}
    with patch("api.public_search.search_zynd_personas", return_value=fake_result) as mock_search:
        result = _run(search_people_get(_fake_request(), query="AI founders", mode="domain", limit=5))
    mock_search.assert_called_once_with("AI founders", 5, "")
    assert result["mode"] == "domain"
    assert result["results"][0]["name"] == "Alice"


def test_get_variant_defaults_and_similar_mode():
    fake_result = {"status": "success", "count": 0, "results": []}
    with patch("api.public_search.search_similar_people", return_value=fake_result) as mock_similar, \
         patch("api.public_search.search_zynd_personas", return_value=fake_result) as mock_domain:
        result = _run(search_people_get(_fake_request(), query="climate founder", mode="similar", limit=10))
    mock_similar.assert_called_once_with("climate founder", 10)
    mock_domain.assert_not_called()
    assert result["mode"] == "similar"
    assert result["limit"] == 10


def test_get_variant_empty_query_422():
    with pytest.raises(HTTPException) as exc:
        _run(search_people_get(_fake_request(), query="   "))
    assert exc.value.status_code == 422


def test_get_variant_rate_limited():
    import api.public_search as ps

    ps._hits.clear()
    old_max = ps._MAX_PER_WINDOW
    ps._MAX_PER_WINDOW = 2
    try:
        with patch("api.public_search.search_zynd_personas", return_value={"status": "success", "results": []}):
            req = _fake_request(ip="8.8.8.8")
            _run(search_people_get(req, query="a"))
            _run(search_people_get(req, query="b"))
            with pytest.raises(HTTPException) as exc:
                _run(search_people_get(req, query="c"))
            assert exc.value.status_code == 429
    finally:
        ps._MAX_PER_WINDOW = old_max
        ps._hits.clear()


def test_minimal_schema_exposes_get_and_post():
    from api.public_search import _public_schema

    s = _public_schema("https://dev.persona.zynd.ai")
    path = s["paths"]["/api/public/search/people"]
    assert set(path.keys()) == {"post", "get"}
    assert path["get"]["parameters"][0]["name"] == "query"
    assert path["get"]["parameters"][0]["in"] == "query"
    assert path["post"]["requestBody"]["required"] is True
    assert s["openapi"] == "3.0.2"
    assert s["servers"][0]["url"] == "https://dev.persona.zynd.ai"


# ── search_similar_people ranking ─────────────────────────────────────


def _supabase_stub(rows):
    sb = MagicMock()
    exe = MagicMock()
    exe.data = rows
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value = exe
    return sb


def _persona(agent_id, name, description="", capabilities=None, interests=None):
    profile = {}
    if interests:
        profile["interests"] = interests
    return {
        "agent_id": agent_id,
        "name": name,
        "description": description,
        "capabilities": capabilities or [],
        "profile": profile,
    }


def test_similar_people_ranks_by_interest_coverage():
    rows = [
        _persona("a1", "Alice", "Founder", capabilities=["AI agents"], interests=["startups"]),
        _persona("b2", "Bob", "Designer", capabilities=["UI design"], interests=["climate tech"]),
        _persona("c3", "Carol", "Engineer", capabilities=["backend"], interests=[]),
    ]
    with patch("mcp.tools.zynd_network._get_supabase", return_value=_supabase_stub(rows)), \
         patch("mcp.tools.zynd_network._get_avatar_map", return_value={}):
        result = search_similar_people("AI startup founder", top_k=3)

    assert result["status"] == "success"
    assert result["results"][0]["agent_id"] == "a1"  # matches ai + startup + founder (best coverage)
    assert "similar focus" in result["results"][0]["match_reason"]


def test_similar_people_falls_back_to_text_relevance():
    rows = [
        _persona("a1", "Alice", "building agent tooling", capabilities=[], interests=[]),
        _persona("b2", "Bob", "pianist", capabilities=[], interests=[]),
    ]
    with patch("mcp.tools.zynd_network._get_supabase", return_value=_supabase_stub(rows)), \
         patch("mcp.tools.zynd_network._get_avatar_map", return_value={}):
        result = search_similar_people("infrastructure tooling", top_k=3)

    assert result["results"]
    assert result["results"][0]["agent_id"] == "a1"  # text-matched; Bob dropped
    assert all(r["match_score"] > 0 for r in result["results"])


def test_similar_people_empty_query_returns_empty_success():
    with patch("mcp.tools.zynd_network._get_supabase", return_value=_supabase_stub([])), \
         patch("mcp.tools.zynd_network._get_avatar_map", return_value={}):
        result = search_similar_people("  the  ", top_k=3)
    assert result["status"] == "success"
    assert result["count"] == 0


def test_similar_people_db_error_returns_friendly_error():
    bad_sb = MagicMock()
    bad_sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = Exception("db down")
    with patch("mcp.tools.zynd_network._get_supabase", return_value=bad_sb), \
         patch("mcp.tools.zynd_network._get_avatar_map", return_value={}):
        result = search_similar_people("founders", top_k=3)
    assert result["status"] == "error"
    assert "hint" in result