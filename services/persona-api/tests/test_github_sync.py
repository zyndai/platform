"""
Tests for the GitHub sync service (backend/services/github_sync.py).

Pure functions (_score_repo, _derive_profile, _select_important) are
tested directly; the token-refresh flow is tested with httpx/PostgREST
stubbed out so no network or Supabase access is needed; sync_to_memory
is tested with the memory client stubbed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from services.github_sync import (
    _derive_profile,
    _score_repo,
    _select_important,
    _refresh_access_token,
    _token_needs_refresh,
    sync_to_memory,
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


def test_select_important_separates_active_from_notable():
    active = {
        "full_name": "a/current", "description": "current work",
        "topics": ["ai"], "stargazers_count": 3,
        "pushed_at": "2026-08-20T00:00:00Z",
    }
    old_starred = {
        "full_name": "a/legacy", "description": "big past project",
        "topics": ["blockchain"], "stargazers_count": 30,
        "pushed_at": "2024-01-01T00:00:00Z",
    }
    empty = {
        "full_name": "a/empty", "description": "",
        "topics": [], "stargazers_count": 0,
        "pushed_at": "2020-01-01T00:00:00Z",
    }
    active_names, notable_names = _select_important([active, old_starred, empty])
    assert "a/current" in active_names
    assert "a/legacy" in notable_names
    assert "a/legacy" not in active_names
    assert "a/empty" not in active_names and "a/empty" not in notable_names


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
            "language": "Python",
            "topics": [],
            "stargazers_count": 0,
            "pushed_at": "2020-01-01T00:00:00Z",
        },
    ]
    langs = {"a/foo": {"Python": 1000, "TypeScript": 500}, "a/bar": {"Python": 400, "TypeScript": 300}}
    profile = _derive_profile(repos, langs)

    assert [s["language"] for s in profile["skills"]] == ["Python", "TypeScript"]
    assert profile["skills"][0]["bytes"] == 1400 and profile["skills"][0]["repos"] == 2
    assert profile["skills"][0]["share"] == 0.636
    assert "ai" in profile["interests"]
    assert profile["projects"][0]["name"] == "foo"
    assert profile["projects"][0]["languages"] == ["Python", "TypeScript"]
    assert profile["projects"][0]["active"] is True
    assert profile["projects"][1]["name"] == "bar"
    assert profile["projects"][1]["active"] is False
    assert profile["projects"][1]["notable"] is False


# ── Which languages count as skills (docs/plans/ZYND_MEMORY_QUALITY_PLAN.md, Phase 3) ──


def _repo(name, **extra):
    return {"name": name, "full_name": f"a/{name}", "description": name, "pushed_at": "2026-08-20T00:00:00Z",
            "topics": [], **extra}


def _skills(languages_by_repo, **repo_extras):
    repos = [_repo(n, **repo_extras.get(n, {})) for n in languages_by_repo]
    return [s["language"] for s in _derive_profile(repos, {f"a/{n}": l for n, l in languages_by_repo.items()})["skills"]]


def test_markup_config_and_template_languages_are_not_skills():
    skills = _skills({
        "web": {"Python": 5000, "HTML": 90_000, "CSS": 40_000, "Shell": 9_000, "Dockerfile": 500, "Makefile": 300},
        "api": {"Python": 4000, "HTML": 50_000, "Jinja": 10_000},
    })
    assert skills == ["Python"]


def test_a_language_needs_a_real_share_and_to_appear_in_two_repos():
    skills = _skills({
        "a": {"Python": 10_000, "Go": 600},        # Go is 4% of the code
        "b": {"Python": 8_000, "Rust": 3_000},     # Rust is real but lives in one repo
        "c": {"Python": 6_000, "TypeScript": 5_000},
        "d": {"TypeScript": 4_000},
    })
    assert skills == ["Python", "TypeScript"]


def test_a_user_with_one_repo_is_held_to_the_share_only():
    assert _skills({"solo": {"Rust": 9_000, "Python": 4_000, "C": 100}}) == ["Rust", "Python"]


def test_archived_repos_do_not_count():
    skills = _skills(
        {"live1": {"Python": 5_000}, "live2": {"Python": 4_000}, "old": {"Perl": 90_000}, "old2": {"Perl": 90_000}},
        old={"archived": True}, old2={"archived": True},
    )
    assert skills == ["Python"]


def test_a_vendored_build_in_one_repo_is_not_a_skill():
    # A Python project that commits a compiled JS frontend (2 MB), next to ordinary Python repos
    # with a sliver of JS elsewhere: the JS is that one repo's vendored bundle.
    skills = _skills({
        "app": {"Python": 30_000, "JavaScript": 2_000_000},
        "lib1": {"Python": 40_000, "JavaScript": 600},
        "lib2": {"Python": 35_000},
    })
    assert skills == ["Python"]


def test_a_language_used_across_repos_is_kept_even_when_one_repo_dominates_it():
    skills = _skills({
        "big": {"Go": 80_000, "Python": 1_000},
        "small": {"Go": 12_000, "Python": 20_000},
        "tool": {"Go": 9_000, "Python": 15_000},
    })
    assert skills == ["Go", "Python"]          # Go elsewhere is 28% of the other repos, not a vendored blob


def test_skills_are_capped_at_five():
    six = {k: 5_000 for k in "ABCDEF"}            # six languages at 16.7% each: all clear the share
    assert _skills({"a": dict(six), "b": dict(six)}) == list("ABCDE")


def test_no_language_data_means_no_skills():
    assert _derive_profile([_repo("x")], {})["skills"] == []
    assert _derive_profile([_repo("x")], {"a/x": {"HTML": 100}})["skills"] == []


# ── Memory wiring ────────────────────────────────────────────────────


def _project(name, active=False, notable=False, description=""):
    return {
        "name": name,
        "full_name": f"a/{name}",
        "description": description,
        "active": active,
        "notable": notable,
    }


def test_sync_to_memory_declares_active_notable_and_skills():
    profile = {
        "skills": [{"language": "Python"}, {"language": "Rust"}],
        "projects": [
            _project("current", active=True, description="current thing"),
            _project("legacy", notable=True, description="past hit"),
            _project("filler"),
        ],
    }
    declared = []

    async def fake_declare(user_id, predicate, value, source_system="user_confirmed"):
        declared.append((predicate, value))
        return True

    async def run():
        with patch("agent.memory_client.declare_fact", side_effect=fake_declare), \
             patch("agent.memory_client.ingest_turns", new=AsyncMock()), \
             patch("services.github_sync._compose_summary", new=AsyncMock(return_value="summary")):
            return await sync_to_memory("u1", profile, previous=None)

    result = asyncio.run(run())
    predicates = {p for p, _ in declared}
    assert "has_skill" in predicates
    assert "is_working_on" in predicates
    assert "is_building" in predicates
    # Active repo → is_working_on; notable repo → is_building; filler → nothing.
    working = [v for p, v in declared if p == "is_working_on"]
    built = [v for p, v in declared if p == "is_building"]
    assert any(v.startswith("current") for v in working)
    assert any(v.startswith("legacy") for v in built)
    assert not any(v.startswith("filler") for _, v in declared)
    assert result["active_projects"] == ["current"]
    assert result["notable_projects"] == ["legacy"]


def test_sync_to_memory_diff_skips_unchanged():
    profile = {
        "skills": [{"language": "Python"}],
        "projects": [_project("current", active=True)],
    }
    previous = {
        "skills": [{"language": "Python"}],
        "projects": [_project("current", active=True)],
    }
    declared = []

    async def fake_declare(user_id, predicate, value, source_system="user_confirmed"):
        declared.append((predicate, value))
        return True

    async def run():
        with patch("agent.memory_client.declare_fact", side_effect=fake_declare), \
             patch("agent.memory_client.ingest_turns", new=AsyncMock()) as ingest, \
             patch("services.github_sync._compose_summary", new=AsyncMock(return_value="x")):
            return await sync_to_memory("u1", profile, previous=previous)

    result = asyncio.run(run())
    assert declared == []
    assert result["facts_declared"] == 0


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
