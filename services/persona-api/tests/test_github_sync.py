"""
Tests for the GitHub sync service (backend/services/github_sync.py).

Pure functions (_score_repo, _derive_profile) are tested directly; the
token-refresh flow is tested with httpx/PostgREST stubbed out so no
network or Supabase access is needed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from services.github_sync import (
    _derive_profile,
    _score_repo,
    _refresh_access_token,
    _token_needs_refresh,
)


# ── Pure functions ───────────────────────────────────────────────────


def test_score_repo_prefers_active_descriptive_repos():
    good = {
        "description": "AI agent framework",
        "topics": ["ai", "agents"],
        "stargazers_count": 12,
        "pushed_at": "2026-08-20T00:00:00Z",
        "has_projects": True,
    }
    bare = {
        "description": "",
        "topics": [],
        "stargazers_count": 0,
        "pushed_at": "2020-01-01T00:00:00Z",
    }
    assert _score_repo(good) > 0
    assert _score_repo(bare) == 0


def test_derive_profile_aggregates_languages_and_projects():
    repos = [
        {
            "name": "foo",
            "full_name": "a/foo",
            "description": "AI agent framework",
            "html_url": "https://github.com/a/foo",
            "language": "Python",
            "topics": ["ai", "agents"],
            "stargazers_count": 12,
            "pushed_at": "2026-08-20T00:00:00Z",
        },
        {
            "name": "bar",
            "full_name": "a/bar",
            "description": "",
            "html_url": "https://github.com/a/bar",
            "language": "Go",
            "topics": [],
            "stargazers_count": 0,
            "pushed_at": "2020-01-01T00:00:00Z",
        },
    ]
    langs = {"a/foo": {"Python": 1000, "TypeScript": 500}, "a/bar": {"Go": 100}}
    profile = _derive_profile(repos, langs)

    assert [s["language"] for s in profile["skills"]] == ["Python", "TypeScript", "Go"]
    assert profile["skills"][0]["bytes"] == 1000
    assert "ai" in profile["interests"]
    assert profile["projects"][0]["name"] == "foo"
    assert profile["projects"][0]["languages"] == ["Python", "TypeScript"]


# ── Token refresh ────────────────────────────────────────────────────


def _fake_httpx_response(status: int, payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    return resp


def test_refresh_access_token_rotates_and_saves():
    tokens = {"access_token": "old", "refresh_token": "rt1", "expires_at": "2026-08-25T05:53:46+00:00"}
    new_pair = {
        "access_token": "new",
        "refresh_token": "rt2",  # rotating refresh token
        "expires_in": 28800,
        "refresh_token_expires_in": 15897600,
        "token_type": "bearer",
    }
    post_mock = AsyncMock(return_value=_fake_httpx_response(200, new_pair))
    save_mock = AsyncMock()

    async def run():
        with patch("services.github_sync.get_tokens", return_value=tokens), \
             patch("services.github_sync.save_tokens", new=save_mock), \
             patch("httpx.AsyncClient.post", new=post_mock):
            return await _refresh_access_token("u1")

    assert asyncio.run(run()) is True
    # The rotated pair (incl. new refresh_token) must be persisted.
    saved = save_mock.call_args.args
    assert saved[0] == "u1" and saved[1] == "github"
    assert saved[2]["access_token"] == "new"
    assert saved[2]["refresh_token"] == "rt2"


def test_refresh_access_token_returns_false_on_rejection():
    post_mock = AsyncMock(return_value=_fake_httpx_response(401, {"error": "bad_verification_code"}))

    async def run():
        with patch("services.github_sync.get_tokens",
                   return_value={"access_token": "old", "refresh_token": "rt1"}), \
             patch("httpx.AsyncClient.post", new=post_mock):
            return await _refresh_access_token("u1")

    assert asyncio.run(run()) is False


def test_refresh_requires_stored_refresh_token():
    async def run():
        with patch("services.github_sync.get_tokens", return_value={"access_token": "old"}):
            return await _refresh_access_token("u1")

    assert asyncio.run(run()) is False


def test_token_needs_refresh_near_expiry():
    expired = {"access_token": "a", "expires_at": "2026-01-01T00:00:00+00:00"}

    async def run_expired():
        with patch("services.github_sync.get_tokens", return_value=expired):
            return await _token_needs_refresh("u1")

    async def run_no_expiry():
        with patch("services.github_sync.get_tokens", return_value={"access_token": "a"}):
            return await _token_needs_refresh("u1")

    assert asyncio.run(run_expired()) is True
    assert asyncio.run(run_no_expiry()) is False
