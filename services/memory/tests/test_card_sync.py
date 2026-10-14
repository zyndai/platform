"""Unit tests for the fire-and-forget cards-api refresh notifier (S02)."""
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.config import settings
from app.services import card_sync


@pytest.mark.asyncio
async def test_post_hits_refresh_endpoint_with_email(monkeypatch):
    monkeypatch.setattr(settings, "memory_service_token", "service-token")
    monkeypatch.setattr(settings, "cards_api_url", "https://cards.example")
    posted = {}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            posted.update(url=url, **kwargs)
            return httpx.Response(200, json={}, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.services.card_sync.httpx.AsyncClient", lambda **kw: Client())
    await card_sync._post("owner@example.com")

    assert posted["url"] == "https://cards.example/internal/refresh-card-memory"
    assert posted["json"] == {"email": "owner@example.com"}
    assert posted["headers"] == {"Authorization": "Bearer service-token"}


@pytest.mark.asyncio
async def test_post_swallows_network_error(monkeypatch):
    monkeypatch.setattr(settings, "memory_service_token", "service-token")
    monkeypatch.setattr(settings, "cards_api_url", "https://cards.example")

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("boom")

    monkeypatch.setattr("app.services.card_sync.httpx.AsyncClient", lambda **kw: Client())
    await card_sync._post("owner@example.com")  # must not raise


@pytest.mark.asyncio
async def test_post_swallows_non_200(monkeypatch):
    monkeypatch.setattr(settings, "memory_service_token", "service-token")
    monkeypatch.setattr(settings, "cards_api_url", "https://cards.example")

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            return httpx.Response(401, json={}, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.services.card_sync.httpx.AsyncClient", lambda **kw: Client())
    await card_sync._post("owner@example.com")  # must not raise


@pytest.mark.asyncio
async def test_notify_noop_when_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "feature_s02_card_sync", False)
    monkeypatch.setattr(settings, "memory_service_token", "service-token")
    pool = MagicMock()
    await card_sync.notify_cards_refresh(pool, "uid")
    pool.fetchval.assert_not_called()


@pytest.mark.asyncio
async def test_notify_noop_when_token_empty(monkeypatch):
    monkeypatch.setattr(settings, "feature_s02_card_sync", True)
    monkeypatch.setattr(settings, "memory_service_token", "")
    pool = MagicMock()
    await card_sync.notify_cards_refresh(pool, "uid")
    pool.fetchval.assert_not_called()


@pytest.mark.asyncio
async def test_notify_resolves_email_and_schedules(monkeypatch):
    monkeypatch.setattr(settings, "feature_s02_card_sync", True)
    monkeypatch.setattr(settings, "memory_service_token", "service-token")
    monkeypatch.setattr(card_sync, "_resolve_email", AsyncMock(return_value="owner@example.com"))
    scheduled = []
    monkeypatch.setattr(card_sync, "_schedule", lambda email: scheduled.append(email))
    await card_sync.notify_cards_refresh(MagicMock(), "uid")
    assert scheduled == ["owner@example.com"]


@pytest.mark.asyncio
async def test_notify_skips_when_no_email(monkeypatch):
    monkeypatch.setattr(settings, "feature_s02_card_sync", True)
    monkeypatch.setattr(settings, "memory_service_token", "service-token")
    monkeypatch.setattr(card_sync, "_resolve_email", AsyncMock(return_value=None))
    scheduled = []
    monkeypatch.setattr(card_sync, "_schedule", lambda email: scheduled.append(email))
    await card_sync.notify_cards_refresh(MagicMock(), "uid")
    assert scheduled == []