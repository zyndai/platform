from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.config import settings
from app.tools.card_status import get_owner_status


@pytest.mark.asyncio
async def test_status_flag_off_never_reads_database(monkeypatch):
    monkeypatch.setattr(settings, "feature_s10_home", False)
    pool = MagicMock()
    assert (await get_owner_status(pool, "uid"))["ok"] is False
    pool.fetchval.assert_not_called()


@pytest.mark.asyncio
async def test_owner_is_derived_from_authenticated_memory_uid(monkeypatch):
    monkeypatch.setattr(settings, "feature_s10_home", True)
    monkeypatch.setattr(settings, "memory_service_token", "service-test-token")
    monkeypatch.setattr(settings, "cards_api_url", "https://cards.example")
    pool = MagicMock(fetchval=AsyncMock(return_value="owner@example.com"))
    posted = {}
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            posted.update(url=url, **kwargs)
            return httpx.Response(200, json={"handle": "owner", "completeness": {"actions": []}}, request=httpx.Request("POST", url))
    monkeypatch.setattr("app.tools.card_status.httpx.AsyncClient", lambda **kwargs: Client())
    result = await get_owner_status(pool, "11111111-1111-4111-8111-111111111111")
    assert result["ok"] is True and result["data"]["handle"] == "owner"
    assert posted["json"] == {"email": "owner@example.com"}
    pool.fetchval.assert_awaited_once_with("SELECT email FROM users WHERE id = $1::uuid", "11111111-1111-4111-8111-111111111111")


@pytest.mark.asyncio
async def test_service_errors_do_not_expose_email_or_token(monkeypatch):
    monkeypatch.setattr(settings, "feature_s10_home", True)
    monkeypatch.setattr(settings, "memory_service_token", "private-test-secret")
    pool = MagicMock(fetchval=AsyncMock(return_value="private@example.com"))
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): raise httpx.ConnectError("private@example.com private-test-secret")
    monkeypatch.setattr("app.tools.card_status.httpx.AsyncClient", lambda **kwargs: Client())
    result = await get_owner_status(pool, "uid")
    assert result == {"ok": False, "error": "Owner card status temporarily unavailable"}
