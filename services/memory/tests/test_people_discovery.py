"""find_people covers Zynd users, claimed/unclaimed cards, and QuickEnrich."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import app.mcp_http as m
from app.services import people_discovery as discovery


@pytest.mark.asyncio
async def test_find_people_merges_cards_and_quickenrich():
    zynd = [{"user_id": "u1", "display_name": "Ada"}]
    cards = [{"source": "zynd_card", "handle": "ada", "claimed": True, "name": "Ada"}]
    prospects = [{"source": "quickenrich", "name": "Grace", "linkedin_url": "https://www.linkedin.com/in/grace"}]
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=MagicMock())), \
         patch("app.mcp_http.search_by_query", AsyncMock(return_value=zynd)), \
         patch("app.mcp_http.search_cards", AsyncMock(return_value=(cards, None))), \
         patch("app.mcp_http.search_quickenrich", AsyncMock(return_value=(prospects, None))):
        result = await m.find_people("ai founder", k=5, uid="caller")

    assert result["zynd_users"][0]["connection_eligible"] is True
    assert result["zynd_users"][0]["source"] == "zynd"
    assert result["cards"][0]["claimed"] is True
    assert result["quickenrich"][0]["name"] == "Grace"
    assert "warnings" not in result


@pytest.mark.asyncio
async def test_find_people_sources_filter_skips_external():
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=MagicMock())), \
         patch("app.mcp_http.search_by_query", AsyncMock(return_value=[])), \
         patch("app.mcp_http.search_cards", AsyncMock()) as cards, \
         patch("app.mcp_http.search_quickenrich", AsyncMock()) as qe:
        result = await m.find_people("investor", sources="zynd", uid="caller")
    cards.assert_not_awaited()
    qe.assert_not_awaited()
    assert result["sources"] == ["zynd"]


@pytest.mark.asyncio
async def test_find_people_keeps_other_sources_when_zynd_fails():
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=MagicMock())), \
         patch("app.mcp_http.search_by_query", AsyncMock(side_effect=RuntimeError("db"))), \
         patch("app.mcp_http.search_cards", AsyncMock(return_value=([{"handle": "sam", "claimed": False}], None))), \
         patch("app.mcp_http.search_quickenrich", AsyncMock(return_value=([], "quickenrich_unavailable"))):
        result = await m.find_people("designer", uid="caller")
    assert result["zynd_users"] == []
    assert result["cards"][0]["claimed"] is False
    assert result["warnings"] == ["zynd_unavailable", "quickenrich_unavailable"]


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
async def test_search_quickenrich_unconfigured_is_empty(monkeypatch):
    monkeypatch.setattr(discovery.settings, "quickenrich_base_url", "")
    monkeypatch.setattr(discovery.settings, "quickenrich_api_key", "")
    rows, warning = await discovery.search_quickenrich("founder", 3)
    assert rows == []
    assert warning is None


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
