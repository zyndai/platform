"""The plugin-review demo account is usable through the plugin OAuth flow and nowhere else."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app import oauth, oauth_ui
from app.config import settings
from app.supabase_auth import supabase_identity
from test_oauth_grants import Pool, Redis, USER, request, response_data, signed_request
from test_plugin_oauth import CALLBACK, CLIENT, SCOPES, authorize, pair

REVIEWER = "openai-review@example.test"


def supabase_user(email):
    return {"id": "reviewer-sub", "email": email, "email_confirmed_at": "2026-01-01T00:00:00Z",
            "app_metadata": {"provider": "email"}, "user_metadata": {"full_name": "Reviewer"}}


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings, "plugin_oauth_client_id", CLIENT)
    monkeypatch.setattr(settings, "plugin_oauth_redirect_uris", CALLBACK)
    monkeypatch.setattr(settings, "feature_plugin_consent", True)
    monkeypatch.setattr(settings, "plugin_review_emails", REVIEWER)
    monkeypatch.setattr(settings, "trusted_supabase_projects", "https://sb.example.test|anon-key")


@pytest.fixture
def session():
    """A Supabase session whose verified email can be switched; the real reviewer gate runs."""
    redis, pool, account = Redis(), Pool(), {"email": REVIEWER}

    async def fetch(token):
        return supabase_user(account["email"])

    with patch("app.oauth.get_pool", return_value=pool), \
         patch("app.mcp_http._get_pool", new_callable=AsyncMock, return_value=pool), \
         patch("app.supabase_auth._fetch_user", new_callable=AsyncMock, side_effect=fetch), \
         patch("app.services.users.find_user", new_callable=AsyncMock, return_value=USER), \
         patch("app.services.persona.link_user", new_callable=AsyncMock, return_value=None):
        yield redis, pool, account


async def complete(redis, signed, decision="approve"):
    return await oauth.complete(request(redis), oauth._CompleteRequest(
        req=signed, supabase_token="session", decision=decision))


async def test_reviewer_can_connect_the_plugin(session):
    redis, pool, _ = session
    connected = await pair(redis)
    assert connected["scope"] == SCOPES
    assert len(pool.connections) == 1


async def test_reviewer_is_denied_on_every_other_client(session):
    redis, _, _ = session
    signed = await signed_request()
    with pytest.raises(HTTPException) as error:
        await oauth.consent(oauth._CompleteRequest(req=signed, supabase_token="session"))
    assert error.value.status_code == 401
    with pytest.raises(HTTPException) as error:
        await complete(redis, signed)
    assert error.value.status_code == 401
    assert not any(":code:" in key for key in redis.store)


async def test_reviewer_session_cannot_mint_general_tokens(session):
    from app.main import token_exchange
    with pytest.raises(HTTPException) as error:
        await token_exchange(authorization="Bearer session", body=None)
    assert error.value.status_code == 401


async def test_other_accounts_are_unchanged(session):
    redis, _, account = session
    account["email"] = "owner@example.test"
    result = await complete(redis, await signed_request())
    assert "code=" in response_data(result)["redirect_url"]


async def test_empty_setting_leaves_identity_untouched(session, monkeypatch):
    monkeypatch.setattr(settings, "plugin_review_emails", "")
    assert (await supabase_identity("session"))[0] == REVIEWER


async def test_plugin_review_endpoints_accept_reviewer(session):
    import plugin_review
    pool = type("Pool", (), {"fetchrow": AsyncMock(return_value={"id": USER})})()
    with patch.object(plugin_review, "get_pool", return_value=pool):
        assert await plugin_review._owner("Bearer session") == USER


async def test_login_page_offers_reviewer_form_only_for_the_plugin(session, monkeypatch):
    plugin_page = oauth_ui._render_login(await authorize()).body.decode()
    other_page = oauth_ui._render_login(await signed_request()).body.decode()
    assert 'id="reviewer-form"' in plugin_page
    assert 'id="reviewer-form"' not in other_page
    monkeypatch.setattr(settings, "plugin_review_emails", "")
    assert 'id="reviewer-form"' not in oauth_ui._render_login(await authorize()).body.decode()
    assert 'id="reviewer-form"' not in oauth_ui._render_login("not-a-signed-request").body.decode()
