"""Multi-project trust for _fetch_user: a token only validates against the
Supabase project that issued it, so each trusted project is tried in turn."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.supabase_auth import _fetch_user


def _mock_client(get_side_effect):
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=get_side_effect)
    return mock_client


@pytest.mark.asyncio
async def test_falls_through_to_second_trusted_project(monkeypatch):
    monkeypatch.setattr(
        settings, "trusted_supabase_projects",
        "https://xmfj.example|xmfj-anon,https://aafo.example|aafo-anon",
    )

    unauthorized = MagicMock(status_code=401)
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"id": "u1", "email": "a@example.com"}

    mock_client = _mock_client([unauthorized, ok])

    with patch("app.supabase_auth.httpx.AsyncClient", return_value=mock_client):
        user = await _fetch_user("some-token")

    assert user == {"id": "u1", "email": "a@example.com"}
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_no_trusted_project_accepts_returns_none(monkeypatch):
    monkeypatch.setattr(
        settings, "trusted_supabase_projects",
        "https://xmfj.example|xmfj-anon,https://aafo.example|aafo-anon",
    )
    mock_client = _mock_client([MagicMock(status_code=401), MagicMock(status_code=401)])

    with patch("app.supabase_auth.httpx.AsyncClient", return_value=mock_client):
        user = await _fetch_user("bad-token")

    assert user is None


@pytest.mark.asyncio
async def test_single_project_default_unchanged(monkeypatch):
    """No trusted_supabase_projects set — falls back to supabase_url/anon_key alone."""
    monkeypatch.setattr(settings, "trusted_supabase_projects", "")
    monkeypatch.setattr(settings, "supabase_url", "https://aafo.example")
    monkeypatch.setattr(settings, "supabase_anon_key", "aafo-anon")

    ok = MagicMock(status_code=200)
    ok.json.return_value = {"id": "u1"}
    mock_client = _mock_client([ok])

    with patch("app.supabase_auth.httpx.AsyncClient", return_value=mock_client):
        user = await _fetch_user("token")

    assert user == {"id": "u1"}
    assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_empty_access_token_returns_none_without_network():
    assert await _fetch_user("") is None
