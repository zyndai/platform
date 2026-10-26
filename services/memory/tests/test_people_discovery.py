"""find_people covers Zynd users, claimed/unclaimed cards, and QuickEnrich."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import app.mcp_http as m
from app.services import people_discovery as discovery


@pytest.mark.asyncio
async def test_search_cards_keeps_claimed_and_unclaimed(monkeypatch):
    monkeypatch.setattr(discovery.settings, "cards_api_base_url", "http://cards.test")
    monkeypatch.setattr(discovery.settings, "cards_site_base_url", "https://cards.zynd.ai")
    payload = {"results": [
        {"handle": "jane", "claimed": True, "name": "Jane", "headline": "Founder", "url": "https://evil.example/p/jane"},
        {"handle": "scraped", "claimed": False, "name": "Sam", "email": "sam@example.com"},
        {"handle": "../bad", "claimed": True, "name": "Nope"},
    ]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params):
            assert params["include_unclaimed"] == "true"
            resp = MagicMock()
            resp.json.return_value = payload
            resp.raise_for_status.return_value = None
            return resp

    monkeypatch.setattr(discovery.httpx, "AsyncClient", FakeClient)
    rows, warning = await discovery.search_cards("founder", 5)
    assert warning is None
    assert [row["handle"] for row in rows] == ["jane", "scraped"]
    assert rows[0]["url"] == "https://cards.zynd.ai/p/jane"
    assert rows[0]["claimed"] is True
    assert rows[1]["claimed"] is False
    assert "email" not in rows[1]


@pytest.mark.asyncio
async def test_search_quickenrich_strips_contact_values(monkeypatch):
    monkeypatch.setattr(discovery.settings, "quickenrich_base_url", "https://qe.example")
    monkeypatch.setattr(discovery.settings, "quickenrich_api_key", "k")
    monkeypatch.setattr(discovery.settings, "quickenrich_auth_header", "Authorization")
    captured = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json, headers):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"data": [{
                "first_name": "Grace",
                "last_name": "Hopper",
                "title": "CTO",
                "company_name": "Navy",
                "employee_linkedin": "https://www.linkedin.com/in/grace",
                "email": "grace@example.com",
                "employee_phone": "555",
                "has_email": True,
                "has_phone": False,
            }]}
            return resp

    monkeypatch.setattr(discovery.httpx, "AsyncClient", FakeClient)
    rows, warning = await discovery.search_quickenrich("seed investor in dev-tools", 3)
    assert warning is None
    assert captured["url"].endswith("/api/employees/contact-finder")
    assert captured["json"]["bio_li"]["include"]
    assert captured["headers"]["Authorization"] == "Bearer k"
    assert rows[0]["linkedin_url"] == "https://www.linkedin.com/in/grace"
    assert rows[0]["has_email"] is True
    assert "email" not in rows[0]
    assert "phone" not in rows[0]


@pytest.mark.asyncio
async def test_search_quickenrich_unconfigured_says_so(monkeypatch):
    monkeypatch.setattr(discovery.settings, "quickenrich_base_url", "")
    monkeypatch.setattr(discovery.settings, "quickenrich_api_key", "")
    rows, warning = await discovery.search_quickenrich("founder", 3)
    assert rows == []
    assert warning == "quickenrich_not_configured"   # never a silent empty list


@pytest.mark.asyncio
async def test_cards_http_error_is_a_warning(monkeypatch):
    monkeypatch.setattr(discovery.settings, "cards_api_base_url", "http://cards.test")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params):
            raise httpx.ConnectError("down")

    monkeypatch.setattr(discovery.httpx, "AsyncClient", FakeClient)
    rows, warning = await discovery.search_cards("founder", 3)
    assert rows == []
    assert warning == "cards_unavailable"


# ── Parsed filters, why, and the external fallback (F1, F3, F9) ────────────────────

def test_cards_search_params_carry_the_parsed_filters():
    from app.services.people_query import parse_target_heuristic
    q = parse_target_heuristic("seed-stage investor who backs AI dev tools in India")
    params = discovery.cards_search_params("seed-stage investor who backs AI dev tools in India", 10, q)
    assert params["q"].startswith("seed-stage investor")
    assert params["role"] == "investor" and params["location"] == "India"
    assert params["topics"] == "AI dev tools" and "skills" not in params     # a guess, not a requirement
    assert params["relax"] == "true" and params["include_unclaimed"] == "true"
    assert "as_handle" not in params
    assert discovery.cards_search_params("investor", 10, q, "me")["as_handle"] == "me"


@pytest.mark.asyncio
async def test_search_cards_returns_match_reasons_as_why(monkeypatch):
    monkeypatch.setattr(discovery.settings, "cards_api_base_url", "http://cards.test")
    payload = {"results": [{
        "handle": "kim", "claimed": True, "name": "Kim", "match_score": 0.7,
        "match_reasons": ["Strong overall match for your query", {"type": "memory", "text": "Backs dev tools"},
                          "Based in Pune", "Skills: ai", "Industry: AI", 42],
    }]}
    seen = {}

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params):
            seen.update(params)
            resp = MagicMock()
            resp.json.return_value = payload
            resp.raise_for_status.return_value = None
            return resp

    monkeypatch.setattr(discovery.httpx, "AsyncClient", FakeClient)
    rows, _ = await discovery.search_cards("investor in Pune", 5)
    assert rows[0]["why"] == [
        "Strong overall match for your query", "Approved fact: Backs dev tools", "Based in Pune", "Skills: ai"]
    assert seen["role"] == "investor" and seen["location"] == "Pune"


@pytest.mark.asyncio
async def test_quickenrich_query_too_vague_is_a_warning_not_silence(monkeypatch):
    monkeypatch.setattr(discovery.settings, "quickenrich_base_url", "https://qe.example")
    monkeypatch.setattr(discovery.settings, "quickenrich_api_key", "k")
    rows, warning = await discovery.search_quickenrich("people in India", 3)
    assert rows == [] and warning == "quickenrich_query_too_vague"


# ── A slow Cards call: the exact-match pass instead of nothing ─────────────────────

def _cards_client(monkeypatch, outcomes):
    """A Cards client that answers each call from `outcomes` (an exception is raised); returns the params it saw."""
    monkeypatch.setattr(discovery.settings, "cards_api_base_url", "http://cards.test")
    monkeypatch.setattr(discovery.settings, "cards_site_base_url", "https://cards.zynd.ai")
    seen: list[dict] = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params):
            seen.append(dict(params))
            outcome = outcomes[len(seen) - 1]
            if isinstance(outcome, Exception):
                raise outcome
            resp = MagicMock()
            resp.json.return_value = outcome
            resp.raise_for_status.return_value = None
            return resp

    monkeypatch.setattr(discovery.httpx, "AsyncClient", FakeClient)
    return seen


@pytest.mark.asyncio
async def test_a_timed_out_relaxed_search_is_retried_without_relaxing(monkeypatch):
    seen = _cards_client(monkeypatch, [httpx.ReadTimeout(""), {"results": [{"handle": "jane", "claimed": True, "name": "Jane"}]}])
    rows, warning = await discovery.search_cards("founders in the USA", 5, search_id="sid-1")
    assert [row["handle"] for row in rows] == ["jane"]
    assert warning == discovery.CARDS_SLOW_WARNING and warning.startswith("cards_slow:")
    assert seen[0]["relax"] == "true" and "relax" not in seen[1]
    assert seen[1]["q"] == seen[0]["q"] and seen[1]["search_id"] == "sid-1"     # the same search, just not loosened


@pytest.mark.asyncio
async def test_a_search_that_times_out_twice_is_unavailable(monkeypatch):
    seen = _cards_client(monkeypatch, [httpx.ReadTimeout(""), httpx.ConnectTimeout("")])
    rows, warning = await discovery.search_cards("founders in the USA", 5)
    assert rows == [] and warning == "cards_unavailable" and len(seen) == 2


@pytest.mark.asyncio
async def test_a_search_with_pinned_filters_is_not_retried(monkeypatch):
    seen = _cards_client(monkeypatch, [httpx.ReadTimeout("")])
    rows, warning = await discovery.search_cards("engineer", 5, extra={"role": "engineer", "location": "Pune"})
    assert rows == [] and warning == "cards_unavailable" and len(seen) == 1 and "relax" not in seen[0]


@pytest.mark.asyncio
async def test_an_error_that_is_not_a_timeout_is_not_retried(monkeypatch):
    seen = _cards_client(monkeypatch, [httpx.ConnectError("down")])
    rows, warning = await discovery.search_cards("founders in the USA", 5)
    assert rows == [] and warning == "cards_unavailable" and len(seen) == 1


@pytest.mark.asyncio
async def test_a_failed_cards_call_logs_the_kind_of_error_not_just_its_message(monkeypatch, caplog):
    _cards_client(monkeypatch, [httpx.ReadTimeout(""), httpx.ReadTimeout("")])
    await discovery.search_cards("founders in the USA", 5)
    assert "ReadTimeout" in caplog.text      # an httpx timeout has an empty message: the type is all there is
