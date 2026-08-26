"""
GitHub MCP Tools

Registered via the ContextAware framework so the agent can:
  - read_github_profile    — read the principal's synced GitHub snapshot
    (repos, languages, projects) from Supabase. Instant — no API calls.
  - refresh_github_profile — pull fresh data from the GitHub API via the
    stored OAuth token (respects rate limits; refreshes expired tokens).

The snapshot is written daily by agent/github_sync_loop.py (and once
immediately after GitHub is connected in the OAuth callback), so the
read tool is the fast path and refresh is the rare explicit fallback.
"""

from __future__ import annotations

import config
from services.github_sync import get_snapshot, sync_user

TABLE = "github_profiles"


def _read_row(user_id: str) -> dict | None:
    """Read the github_profiles snapshot for a user."""
    snapshot = get_snapshot(user_id)
    if snapshot is None:
        return None
    return {
        "username": snapshot.get("username"),
        "skills": snapshot.get("skills") or [],
        "projects": snapshot.get("projects") or [],
        "synced_at": snapshot.get("synced_at"),
    }


async def read_github_profile(user_id: str) -> dict:
    """Read the principal's synced GitHub profile — skills (languages by
    volume), top projects (name, description, URL, languages, topics),
    and GitHub username. Use this when the principal asks about their own
    GitHub work, repos, or what languages they use.

    Data comes from the daily GitHub sync (github_profiles table), so it
    is at most 24h old. If the principal wants fresher data — or the
    snapshot is missing because GitHub isn't connected — call
    refresh_github_profile instead.
    """
    row = _read_row(user_id)
    if row is None:
        return {
            "connected": False,
            "error": (
                "No GitHub profile data found. The user may not have connected "
                "GitHub yet — or the first sync hasn't run. Try refresh_github_profile."
            ),
        }
    return {"connected": True, **row}


async def refresh_github_profile(user_id: str) -> dict:
    """Pull fresh GitHub data now — repos, languages, skills, projects —
    by calling the GitHub API with the principal's stored OAuth token,
    then write any new facts to memory.

    Returns a sync summary (status, username, repo count, new skills and
    projects detected). Fails with a clear message when GitHub isn't
    connected or the token can't be refreshed (user must reconnect).
    """
    try:
        result = await sync_user(user_id)
    except Exception as exc:
        return {"status": "error", "detail": str(exc)[:200]}
    if result.get("status") != "ok":
        return {
            "status": "error",
            "detail": (
                "GitHub sync failed — the user may not have GitHub connected, "
                "or the stored token needs re-consent (ask them to reconnect "
                "GitHub in Settings → Accounts)."
            ),
        }
    return result
