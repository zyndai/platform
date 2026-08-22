"""
Tests for the new data-control endpoints:

  - DELETE /api/linkedin/data         (delete_linkedin_data)
  - DELETE /api/connections/{p}/data  (delete_provider_data)
  - GET    /api/persona/{id}/export   (export_account)

These mock Supabase and the token store so no live DB is required.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch


class _Resp:
    def __init__(self, data):
        self.data = data


def _mock_supabase(rows=None):
    sb = MagicMock()
    chain = sb.table.return_value
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain
    chain.delete.return_value = chain
    chain.execute.return_value = _Resp(rows if rows is not None else [])
    return sb


# ── B1: delete_linkedin_data ──────────────────────────────────────────


def test_delete_linkedin_data_wipes_profile_and_tokens():
    from api.linkedin import delete_linkedin_data

    sb = _mock_supabase()
    with patch("api.linkedin._get_supabase", return_value=sb), patch(
        "services.token_store.delete_tokens"
    ) as mock_delete_tokens:
        result = asyncio.run(delete_linkedin_data(user={"id": "u1"}))

    assert result == {"status": "deleted"}
    # profile table was targeted
    assert sb.table.call_args_list[0].args == ("linkedin_profiles",)
    mock_delete_tokens.assert_called_once_with(user_id="u1", provider="linkedin")


# ── B2: delete_provider_data ──────────────────────────────────────────


def test_delete_provider_data_linkedin_also_wipes_profile():
    from api.connections import delete_provider_data

    sb = _mock_supabase()
    with patch("api.connections.delete_tokens") as mock_delete_tokens, patch(
        "api.connections.config.get_supabase", return_value=sb
    ):
        result = asyncio.run(
            delete_provider_data(provider="linkedin", user={"id": "u1"})
        )

    assert result == {"status": "deleted", "provider": "linkedin"}
    mock_delete_tokens.assert_called_once_with(user_id="u1", provider="linkedin")
    # linkedin_profiles table delete happened
    table_names = [c.args for c in sb.table.call_args_list]
    assert ("linkedin_profiles",) in table_names


def test_delete_provider_data_google_only_deletes_tokens():
    from api.connections import delete_provider_data

    sb = _mock_supabase()
    with patch("api.connections.delete_tokens") as mock_delete_tokens, patch(
        "api.connections.config.get_supabase", return_value=sb
    ):
        result = asyncio.run(
            delete_provider_data(provider="google", user={"id": "u1"})
        )

    assert result == {"status": "deleted", "provider": "google"}
    mock_delete_tokens.assert_called_once_with(user_id="u1", provider="google")
    # no linkedin_profiles table touched for google
    table_names = [c.args for c in sb.table.call_args_list]
    assert ("linkedin_profiles",) not in table_names


def test_delete_provider_data_unknown_provider():
    from api.connections import delete_provider_data

    with patch("api.connections.delete_tokens") as mock_delete_tokens:
        result = asyncio.run(
            delete_provider_data(provider="bogus", user={"id": "u1"})
        )

    assert result == {"error": "Unknown provider: bogus"}
    mock_delete_tokens.assert_not_called()


# ── B5: export_account ────────────────────────────────────────────────


def test_export_account_shape_and_no_tokens():
    from api.persona import export_account

    sb = _mock_supabase(rows=[])
    status = {"deployed": True, "name": "Ada"}
    brief = {"exists": True, "content": "hello"}

    with patch("api.persona.get_persona_status", return_value=status), patch(
        "api.persona.get_brief", return_value=brief
    ), patch("api.persona.config.get_supabase", return_value=sb), patch(
        "services.token_store.list_connected_providers", return_value=[{"provider": "google"}]
    ):
        result = asyncio.run(export_account(user_id="u1", user={"id": "u1"}))

    assert result["user_id"] == "u1"
    assert result["persona"] == status
    assert result["brief"] == brief
    assert result["chat_messages"] == []
    assert result["connected_providers"] == ["google"]
    # never leak tokens
    dumped = str(result)
    assert "access_token" not in dumped
    assert "refresh_token" not in dumped


def test_export_account_rejects_other_user():
    import pytest
    from fastapi import HTTPException

    from api.persona import export_account

    with pytest.raises(HTTPException, match="Not your account"):
        asyncio.run(export_account(user_id="someone-else", user={"id": "u1"}))
