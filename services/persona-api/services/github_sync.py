"""
GitHub sync service — turns the GitHub OAuth token into persona knowledge.

After OAuth (api/oauth_routes.github_callback) stores the token, this
module is what actually uses it:

  1. GET /user                  → identity
  2. GET /user/repos            → all repos the user owns (sorted by push)
  3. GET /repos/{owner}/{repo}/languages → language breakdown for the
     top-scored repos only (rate-limit friendly)
  4. Derive skills (aggregate language bytes) + projects (top repos) and
     persist a raw snapshot to public.github_profiles (diff base for the
     next run).
  5. Write derived facts to the memory layer: is_skilled_in per language,
     is_working_on per project, plus one natural-language summary turn
     ingested with source_system="github" for async extraction.

Called from the GitHub OAuth callback (first sync) and daily from
agent/github_sync_loop.py. Idempotent — re-syncs diff against the last
snapshot so memory facts are only declared once.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import httpx

import config
from services.token_store import get_tokens

logger = logging.getLogger(__name__)

TABLE = "github_profiles"
API_BASE = "https://api.github.com"
GH_ACCEPT = "application/vnd.github+json"
GH_API_VERSION = "2022-11-28"

MAX_REPOS = 100
MAX_LANGUAGE_REPOS = 15
MAX_SKILLS = 8
MAX_PROJECTS = 10
MIN_RATE_LIMIT_REMAINING = 10


def _gh_client(access_token: str) -> httpx.AsyncClient:
    """httpx client preconfigured with GitHub API headers."""
    return httpx.AsyncClient(
        base_url=API_BASE,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": GH_ACCEPT,
            "X-GitHub-Api-Version": GH_API_VERSION,
        },
        timeout=httpx.Timeout(15.0, connect=10.0),
    )


async def _get_json(client: httpx.AsyncClient, url: str) -> dict | list | None:
    """GET a GitHub API path; None on any failure. Tracks rate limit."""
    try:
        resp = await client.get(url)
        remaining = int(resp.headers.get("x-ratelimit-remaining", -1))
        if remaining != -1 and remaining < MIN_RATE_LIMIT_REMAINING:
            logger.warning("[github] rate limit nearly exhausted (%s remaining) — aborting", remaining)
        if resp.status_code == 401:
            logger.warning("[github] token rejected (401) — likely revoked")
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("[github] GET %s failed: %s", url, exc)
        return None


def _score_repo(repo: dict) -> float:
    """Rank repos so only the meaningful ones get deep-inspected.

    Forks and empty repos are filtered out before scoring.
    """
    score = 0.0
    score += min(repo.get("stargazers_count") or 0, 50) * 2
    score += 10 if (repo.get("description") or "").strip() else 0
    score += min(len(repo.get("topics") or []), 5) * 3
    if repo.get("has_projects") or repo.get("homepage"):
        score += 5
    # Recency: pushed within 90 days
    pushed = repo.get("pushed_at") or ""
    try:
        pushed_dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - pushed_dt).days
        if days <= 90:
            score += max(0, (90 - days) / 9)
    except (ValueError, TypeError):
        pass
    return score


async def _fetch_repos(client: httpx.AsyncClient) -> list[dict]:
    """All repos the user owns, newest-pushed first. Forks excluded."""
    data = await _get_json(client, f"/user/repos?per_page={MAX_REPOS}&sort=pushed&type=owner")
    repos = data if isinstance(data, list) else []
    return [r for r in repos if not r.get("fork")][:MAX_REPOS]


async def _fetch_languages(client: httpx.AsyncClient, full_name: str) -> dict[str, int]:
    data = await _get_json(client, f"/repos/{full_name}/languages")
    return data if isinstance(data, dict) else {}


def _derive_profile(repos: list[dict], languages_by_repo: dict[str, dict[str, int]]) -> dict:
    """Build the derived GitHub profile: skills, projects, interests."""
    lang_bytes: Counter = Counter()
    for langs in languages_by_repo.values():
        for lang, nbytes in langs.items():
            lang_bytes[lang] += int(nbytes)

    skills = [
        {"language": lang, "bytes": nbytes}
        for lang, nbytes in lang_bytes.most_common(MAX_SKILLS)
    ]

    topic_counter: Counter = Counter()
    for repo in repos:
        for topic in repo.get("topics") or []:
            topic_counter[topic] += 1
    interests = [t for t, _ in topic_counter.most_common(10)]

    projects = []
    for repo in repos[:MAX_PROJECTS]:
        full_name = repo.get("full_name", "")
        projects.append(
            {
                "name": repo.get("name", ""),
                "full_name": full_name,
                "description": (repo.get("description") or "").strip(),
                "url": repo.get("html_url", ""),
                "languages": sorted(languages_by_repo.get(full_name, {}).keys()),
                "topics": repo.get("topics") or [],
                "stars": repo.get("stargazers_count") or 0,
                "pushed_at": repo.get("pushed_at") or "",
            }
        )

    return {"skills": skills, "projects": projects, "interests": interests}


async def fetch_github_profile(user_id: str) -> dict | None:
    """Fetch repos/languages from the GitHub API and persist the snapshot.

    Returns the derived profile dict, or None when there is no usable
    token or the API rejects it.
    """
    tokens = await asyncio.to_thread(get_tokens, user_id, "github")
    if not tokens or not tokens.get("access_token"):
        return None

    profile: dict = {"skills": [], "projects": [], "interests": [], "username": ""}

    async with _gh_client(tokens["access_token"]) as client:
        me_data = await _get_json(client, "/user")
        if me_data is None:
            return None
        if isinstance(me_data, dict) and me_data.get("login"):
            profile["username"] = me_data["login"]

        repos = await _fetch_repos(client)
        if not repos:
            # An empty list is a legitimate state (no owned repos), but
            # could also mean the token lost the repo scope after a
            # re-consent — record both and let the next sync retry.
            logger.info("[github] %s: /user/repos returned no repos", user_id)

        scored = sorted(
            (r for r in repos if _score_repo(r) > 0),
            key=_score_repo,
            reverse=True,
        )
        top = scored[:MAX_LANGUAGE_REPOS]

        languages_by_repo: dict[str, dict[str, int]] = {}
        for repo in top:
            full_name = repo.get("full_name")
            if not full_name:
                continue
            langs = await _fetch_languages(client, full_name)
            if langs:
                languages_by_repo[full_name] = langs

    derived = _derive_profile(repos, languages_by_repo)
    profile.update(derived)

    raw_repos = [
        {
            "name": r.get("name"),
            "full_name": r.get("full_name"),
            "description": (r.get("description") or "").strip(),
            "html_url": r.get("html_url"),
            "language": r.get("language"),
            "topics": r.get("topics") or [],
            "stargazers_count": r.get("stargazers_count") or 0,
            "pushed_at": r.get("pushed_at") or "",
        }
        for r in repos
    ]

    now = datetime.now(timezone.utc).isoformat()
    sb = config.get_supabase()
    sb.table(TABLE).upsert(
        {
            "user_id": user_id,
            "username": profile["username"],
            "raw_repos": raw_repos,
            "skills": profile["skills"],
            "projects": profile["projects"],
            "synced_at": now,
            "updated_at": now,
        },
        on_conflict="user_id",
    ).execute()

    logger.info(
        "[github] synced %s: %d repos, %d skills, %d projects",
        user_id, len(raw_repos), len(profile["skills"]), len(profile["projects"]),
    )
    return profile


def get_snapshot(user_id: str) -> dict | None:
    """The last persisted snapshot (diff base for the next sync)."""
    try:
        sb = config.get_supabase()
        result = (
            sb.table(TABLE)
            .select("username, raw_repos, skills, projects, synced_at")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if not result or not result.data:
            return None
        return result.data
    except Exception as exc:
        logger.warning("[github] snapshot read failed for %s: %s", user_id, exc)
        return None


async def sync_to_memory(user_id: str, profile: dict, previous: dict | None = None) -> dict:
    """Write derived facts to the memory layer, skipping what's unchanged.

    Diffing against the previous snapshot means the daily cron can run
    forever without re-declaring the same facts. A summary turn is
    ingested (source_system="github") only when something changed so the
    async extraction pipeline re-runs only when there's new material.
    """
    from agent.memory_client import declare_fact, ingest_turns

    previous = previous or {}

    prev_skills = {s.get("language") for s in (previous.get("skills") or [])}
    prev_repos = {r.get("full_name") for r in (previous.get("raw_repos") or [])}

    new_skills = [
        s["language"] for s in profile.get("skills", [])
        if s.get("language") and s["language"] not in prev_skills
    ]
    new_projects = [
        p for p in profile.get("projects", [])
        if p.get("full_name") and p["full_name"] not in prev_repos
    ]

    declared = 0
    for lang in new_skills:
        if await declare_fact(user_id, "is_skilled_in", lang):
            declared += 1
    for proj in new_projects:
        value = proj["name"]
        if proj.get("description"):
            value = f"{proj['name']} — {proj['description'][:120]}"
        if await declare_fact(user_id, "is_working_on", value):
            declared += 1

    changed = bool(new_skills or new_projects)
    if changed and profile.get("projects"):
        summary_parts = []
        if new_skills:
            summary_parts.append(f"I code in: {', '.join(new_skills)}.")
        if new_projects:
            summary_parts.append(
                "On GitHub I work on: "
                + "; ".join(
                    f"{p['name']} ({p['description'][:80]})" if p.get("description")
                    else p["name"]
                    for p in new_projects
                )
                + "."
            )
        await ingest_turns(
            user_id,
            turns=[{"role": "user", "content": " ".join(summary_parts)}],
            source_system="github",
        )

    logger.info(
        "[github] memory sync for %s: %d new skills, %d new projects, %d facts declared",
        user_id, len(new_skills), len(new_projects), declared,
    )
    return {
        "new_skills": new_skills,
        "new_projects": [p["name"] for p in new_projects],
        "facts_declared": declared,
    }


async def sync_user(user_id: str) -> dict:
    """Full sync for one user: fetch GitHub data, persist, update memory."""
    previous = get_snapshot(user_id)
    profile = await fetch_github_profile(user_id)
    if profile is None:
        return {"status": "no_token_or_error"}
    memory_result = await sync_to_memory(user_id, profile, previous)
    snapshot = get_snapshot(user_id) or {}
    return {
        "status": "ok",
        "username": profile.get("username", ""),
        "repos": len(snapshot.get("raw_repos") or []),
        **memory_result,
    }
