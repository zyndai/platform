"""
GitHub sync service — turns the GitHub OAuth token into persona knowledge.

After OAuth (api/oauth_routes.github_callback) stores the token, this
module is what actually uses it:

  1. GET /user                  → identity
  2. GET /user/repos            → all repos the user owns (sorted by push)
  3. GET /repos/{owner}/{repo}/languages → language breakdown for the
     top-scored repos only (rate-limit friendly)
  4. Identify what actually matters (not everything):
       • active repos — pushed in the last 90 days → "currently working on"
       • notable repos — best-scored rest (stars, docs, topics) → "has built"
  5. Persist a raw snapshot to public.github_profiles (diff base for the
     next run).
  6. Wire the IMPORTANT facts into the memory layer:
       • is_working_on per active repo (the focus — declared with
         description)
       • is_building per notable repo
       • has_skill per top language
       • one LLM-composed first-person summary (active work first)
         ingested with source_system="github" for async extraction

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
from services.token_store import get_tokens, save_tokens

logger = logging.getLogger(__name__)

TABLE = "github_profiles"
API_BASE = "https://api.github.com"
GH_ACCEPT = "application/vnd.github+json"
GH_API_VERSION = "2022-11-28"

MAX_REPOS = 100
MAX_LANGUAGE_REPOS = 15
MAX_SKILLS = 8
MAX_PROJECTS = 10
MAX_ACTIVE = 5          # repos declared as "currently working on"
MAX_NOTABLE = 5         # repos declared as "has built"
ACTIVE_WINDOW_DAYS = 90
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


async def _refresh_access_token(user_id: str) -> bool:
    """Rotate an expired GitHub user token.

    GitHub App user tokens live 8 hours; the refresh token lives ~6
    months and ROTATES on every use. save_tokens upserts the new pair so
    the daily loop keeps working. The prod+dev backends both run this —
    if one wins the rotation race, the loser re-reads the fresh token
    from api_tokens and retries (see fetch_github_profile).
    """
    tokens = await asyncio.to_thread(get_tokens, user_id, "github")
    if not tokens or not tokens.get("refresh_token"):
        logger.warning("[github] %s: no refresh_token stored — reconnect required", user_id)
        return False

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=10.0)) as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            json={
                "client_id": config.GITHUB_CLIENT_ID,
                "client_secret": config.GITHUB_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
            },
        )

    if resp.status_code != 200 or not resp.json().get("access_token"):
        logger.warning(
            "[github] %s: refresh failed (%s) — reconnect required", user_id, resp.status_code
        )
        return False

    await asyncio.to_thread(
        save_tokens, user_id, "github", resp.json()
    )
    logger.info("[github] %s: refreshed access token", user_id)
    return True


async def _token_needs_refresh(user_id: str) -> bool:
    """True when the stored access token is expired or about to expire."""
    tokens = await asyncio.to_thread(get_tokens, user_id, "github")
    if not tokens:
        return False
    expires_at = tokens.get("expires_at") or ""
    try:
        expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return (expires_dt - datetime.now(timezone.utc)).total_seconds() < 300
    except (ValueError, TypeError):
        # No expiry info — assume fresh enough and let a 401 trigger refresh.
        return False


def _days_since_pushed(repo: dict) -> int | None:
    """Days since the repo's last push, or None when unparseable."""
    pushed = repo.get("pushed_at") or ""
    try:
        pushed_dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - pushed_dt).days
    except (ValueError, TypeError):
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
    days = _days_since_pushed(repo)
    if days is not None and days <= 90:
        score += max(0, (90 - days) / 9)
    return score


def _select_important(repos: list[dict]) -> tuple[set[str], set[str]]:
    """Pick what the persona should actually remember.

    Returns (active_names, notable_names):
      • active  — top-scored repos pushed within ACTIVE_WINDOW_DAYS,
        i.e. what the user is working on RIGHT NOW (the focus).
      • notable — the best of the rest: the work worth remembering
        ("best repos I've worked on"), regardless of age.
    """
    scored = sorted(
        (r for r in repos if _score_repo(r) > 0),
        key=_score_repo,
        reverse=True,
    )
    active = [
        r for r in scored
        if (_days_since_pushed(r) or 999) <= ACTIVE_WINDOW_DAYS
    ][:MAX_ACTIVE]
    active_names = {r.get("full_name", "") for r in active}
    notable = [
        r for r in scored
        if r.get("full_name", "") not in active_names
    ][:MAX_NOTABLE]
    notable_names = {r.get("full_name", "") for r in notable}
    return active_names, notable_names


async def _fetch_repos(client: httpx.AsyncClient) -> list[dict]:
    """All repos the user owns, newest-pushed first. Forks excluded."""
    data = await _get_json(client, f"/user/repos?per_page={MAX_REPOS}&sort=pushed&type=owner")
    repos = data if isinstance(data, list) else []
    return [r for r in repos if not r.get("fork")][:MAX_REPOS]


async def _fetch_languages(client: httpx.AsyncClient, full_name: str) -> dict[str, int]:
    data = await _get_json(client, f"/repos/{full_name}/languages")
    return data if isinstance(data, dict) else {}


def _derive_profile(
    repos: list[dict],
    languages_by_repo: dict[str, dict[str, int]],
    active_names: set[str] | None = None,
    notable_names: set[str] | None = None,
) -> dict:
    """Build the derived GitHub profile: skills, projects, interests.

    Each project carries `active` / `notable` flags (see _select_important)
    so the memory-write step can decide what's worth declaring. Projects
    are ordered: currently-active first, then notable past work.
    """
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

    if active_names is None or notable_names is None:
        active_names, notable_names = _select_important(repos)

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
                "active": full_name in active_names,
                "notable": full_name in notable_names,
            }
        )
    projects.sort(
        key=lambda p: (not p["active"], not p["notable"], -(p["stars"] or 0))
    )

    return {"skills": skills, "projects": projects, "interests": interests}


async def _pull_profile(client: httpx.AsyncClient) -> tuple[dict | None, list[dict], dict[str, dict[str, int]]]:
    """Fetch identity + repos + languages for the top-scored repos in one pass.

    Returns (me_data, repos, languages_by_repo). me_data is None when the
    token is rejected or the API fails — the caller decides on refresh.
    """
    me_data = await _get_json(client, "/user")
    if me_data is None:
        return None, [], {}

    repos = await _fetch_repos(client)
    if not repos:
        # An empty list is a legitimate state (no owned repos), but could
        # also mean the token lost repo permissions after a re-consent —
        # record it and let the next sync retry.
        logger.info("[github] /user/repos returned no repos")

    scored = sorted(
        (r for r in repos if _score_repo(r) > 0),
        key=_score_repo,
        reverse=True,
    )
    languages_by_repo: dict[str, dict[str, int]] = {}
    for repo in scored[:MAX_LANGUAGE_REPOS]:
        full_name = repo.get("full_name")
        if not full_name:
            continue
        langs = await _fetch_languages(client, full_name)
        if langs:
            languages_by_repo[full_name] = langs

    return me_data, repos, languages_by_repo


async def fetch_github_profile(user_id: str) -> dict | None:
    """Fetch repos/languages from the GitHub API and persist the snapshot.

    Returns the derived profile dict, or None when there is no usable
    token or the API rejects it. Refreshes expired user tokens first and
    retries once on failure (revoked token, or a rotating-token race
    with the other channel's refresh).
    """
    if await _token_needs_refresh(user_id):
        if not await _refresh_access_token(user_id):
            return None

    tokens = await asyncio.to_thread(get_tokens, user_id, "github")
    if not tokens or not tokens.get("access_token"):
        return None

    async with _gh_client(tokens["access_token"]) as client:
        me_data, repos, languages_by_repo = await _pull_profile(client)
        if me_data is None:
            if not await _refresh_access_token(user_id):
                return None
            refreshed = await asyncio.to_thread(get_tokens, user_id, "github")
            if not refreshed or not refreshed.get("access_token"):
                return None
            async with _gh_client(refreshed["access_token"]) as retry_client:
                me_data, repos, languages_by_repo = await _pull_profile(retry_client)
                if me_data is None:
                    return None

    profile: dict = {"skills": [], "projects": [], "interests": [], "username": ""}
    if isinstance(me_data, dict) and me_data.get("login"):
        profile["username"] = me_data["login"]

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


def _project_value(proj: dict) -> str:
    """Compact declarative value for a project fact."""
    value = proj["name"]
    if proj.get("description"):
        value = f"{proj['name']} — {proj['description'][:120]}"
    return value


async def _compose_summary(user_id: str, profile: dict) -> str:
    """LLM-composed first-person memory note, active work first.

    Falls back to a plain template when the LLM is unreachable — the
    summary is a bonus, never a dependency of the sync.
    """
    active = [p for p in profile.get("projects", []) if p.get("active")]
    notable = [p for p in profile.get("projects", []) if p.get("notable")]
    skills = [s["language"] for s in profile.get("skills", [])][:6]

    if active or notable:
        prompt = (
            "Write a private memory note about a person's GitHub activity, "
            "in their own first-person voice. Use only the facts given. "
            "4-6 short declarative sentences. Lead with what they are "
            "CURRENTLY working on (most important), then notable past work, "
            "then main languages. No fluff, no markdown, no bullet lists.\n\n"
            f"Currently working on:\n"
            + "\n".join(f"- {_project_value(p)}" for p in active)
            + "\n\nNotable past work:\n"
            + "\n".join(f"- {_project_value(p)}" for p in notable)
            + f"\n\nMain languages: {', '.join(skills)}"
        )
        try:
            from agent.orchestrator import _get_provider

            provider = _get_provider()
            text, _ = await asyncio.to_thread(
                provider.chat_with_tools,
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Write the note."},
                ],
                [],
            )
            if text and text.strip():
                return text.strip()
        except Exception as exc:
            logger.warning("[github] %s: summary LLM call failed: %s", user_id, exc)

    parts = []
    if active:
        parts.append("I am currently working on: " + "; ".join(
            f"{_project_value(p)}" for p in active
        ) + ".")
    if notable:
        parts.append("I have built: " + "; ".join(
            f"{_project_value(p)}" for p in notable
        ) + ".")
    if skills:
        parts.append("I mainly code in: " + ", ".join(skills) + ".")
    return " ".join(parts)


async def sync_to_memory(user_id: str, profile: dict, previous: dict | None = None) -> dict:
    """Write the IMPORTANT GitHub facts to the memory layer.

    Curated, not everything:
      • is_working_on  — only ACTIVE repos (pushed < 90 days) — the focus
      • is_building    — the best notable repos (stars/docs/topics)
      • has_skill      — top languages
    Plus one LLM-composed summary turn (active work first) ingested with
    source_system="github" for async extraction.

    Diffed against the previous snapshot so the daily cron re-declares
    nothing — new or newly-active repos only.
    """
    from agent.memory_client import declare_fact, ingest_turns

    previous = previous or {}

    prev_skills = {s.get("language") for s in (previous.get("skills") or [])}
    prev_projects = {
        p.get("full_name"): {"active": p.get("active", False), "notable": p.get("notable", False)}
        for p in (previous.get("projects") or [])
        if p.get("full_name")
    }

    new_skills = [
        s["language"] for s in profile.get("skills", [])
        if s.get("language") and s["language"] not in prev_skills
    ]
    new_active = [
        p for p in profile.get("projects", [])
        if p.get("active") and not prev_projects.get(p.get("full_name"), {}).get("active")
    ]
    new_notable = [
        p for p in profile.get("projects", [])
        if p.get("notable")
        and not prev_projects.get(p.get("full_name"), {}).get("notable")
        and not p.get("active")
    ]

    declared = 0
    for lang in new_skills:
        if await declare_fact(user_id, "has_skill", lang, source_system="github"):
            declared += 1
    for proj in new_active:
        if await declare_fact(user_id, "is_working_on", _project_value(proj), source_system="github"):
            declared += 1
    for proj in new_notable:
        if await declare_fact(user_id, "is_building", _project_value(proj), source_system="github"):
            declared += 1

    changed = bool(new_skills or new_active or new_notable)
    if changed and (new_active or new_notable):
        summary = await _compose_summary(user_id, profile)
        if summary:
            await ingest_turns(
                user_id,
                turns=[{"role": "user", "content": summary}],
                source_system="github",
            )

    logger.info(
        "[github] memory sync for %s: %d new skills, %d active, %d notable, %d facts declared",
        user_id, len(new_skills), len(new_active), len(new_notable), declared,
    )
    return {
        "new_skills": new_skills,
        "active_projects": [p["name"] for p in new_active],
        "notable_projects": [p["name"] for p in new_notable],
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
