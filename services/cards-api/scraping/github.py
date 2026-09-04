import asyncio
from datetime import datetime, timedelta, timezone

import httpx

import config

GITHUB_API = "https://api.github.com"
GITHUB_GRAPHQL = "https://api.github.com/graphql"
_MAX_EVENTS = 30
_MAX_COMMIT_MSG_CHARS = 120

_CONTRIB_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            date
          }
        }
      }
    }
  }
}
"""


def _count_to_level(count: int, p75: int, p50: int) -> int:
    if count == 0:
        return 0
    if count >= p75:
        return 4
    if count >= p50:
        return 3
    if count >= 2:
        return 2
    return 1


async def _fetch_contributions(handle: str, headers: dict) -> dict | None:
    if not config.GITHUB_TOKEN:
        return None
    try:
        async with httpx.AsyncClient(headers=headers, timeout=20) as c:
            resp = await c.post(
                GITHUB_GRAPHQL,
                json={"query": _CONTRIB_QUERY, "variables": {"login": handle}},
            )
        if not resp.is_success:
            return None
        body = resp.json()
        cal = (
            body.get("data", {})
            .get("user", {})
            .get("contributionsCollection", {})
            .get("contributionCalendar", {})
        )
        if not cal:
            return None

        total = cal.get("totalContributions", 0)
        days: list[int] = []
        for week in cal.get("weeks", []):
            for day in week.get("contributionDays", []):
                days.append(day.get("contributionCount", 0))

        # Use top quartiles of non-zero days to derive level thresholds
        nonzero = sorted(d for d in days if d > 0)
        if nonzero:
            p50 = nonzero[len(nonzero) // 2]
            p75 = nonzero[int(len(nonzero) * 0.75)]
        else:
            p50, p75 = 2, 5

        levels = [_count_to_level(d, p75, p50) for d in days]
        avg = round(total / 365, 1) if total else 0.0

        return {
            "year": datetime.now(timezone.utc).year,
            "total": total,
            "avg_per_day": avg,
            "levels": levels,
        }
    except Exception:
        return None


async def fetch_github(handle: str) -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"

    async with httpx.AsyncClient(headers=headers, timeout=30) as c:
        user_task   = c.get(f"{GITHUB_API}/users/{handle}")
        repos_task  = c.get(f"{GITHUB_API}/users/{handle}/repos", params={"sort": "updated", "per_page": 30})
        events_task = c.get(f"{GITHUB_API}/users/{handle}/events", params={"per_page": _MAX_EVENTS})

        user_resp, repos_resp, events_resp = await asyncio.gather(
            user_task, repos_task, events_task
        )
        user_resp.raise_for_status()
        repos_resp.raise_for_status()
        events = events_resp.json() if events_resp.is_success else []

    recent_activity = _parse_events(events)
    user_data = user_resp.json()
    repos_data = repos_resp.json()

    cutoff = datetime.now(timezone.utc) - timedelta(days=180)
    active_repos = sum(
        1 for r in repos_data
        if r.get("pushed_at") and
        datetime.fromisoformat(r["pushed_at"].rstrip("Z")).replace(tzinfo=timezone.utc) > cutoff
    )
    top_languages = list(dict.fromkeys(r["language"] for r in repos_data if r.get("language")))[:5]

    contribution_stats = await _fetch_contributions(handle, headers)

    # Total commits approximated as contribution count (includes PRs/issues/reviews — close enough)
    total_commits = contribution_stats["total"] if contribution_stats else None

    return {
        "user": user_data,
        "repos": repos_data,
        "recent_activity": recent_activity,
        "stats": {
            "total_repos": user_data.get("public_repos", 0),
            "active_repos": active_repos,
            "top_languages": top_languages,
            "total_commits": total_commits,
        },
        "contribution_stats": contribution_stats,
    }


def _parse_events(events: list) -> list[dict]:
    """Extract meaningful recent activity: pushes, PRs, issues, releases."""
    out: list[dict] = []
    for ev in events:
        kind = ev.get("type", "")
        repo = (ev.get("repo") or {}).get("name", "")
        payload = ev.get("payload") or {}

        if kind == "PushEvent":
            commits = payload.get("commits") or []
            msgs = [c["message"].split("\n")[0][:_MAX_COMMIT_MSG_CHARS] for c in commits if c.get("message")]
            if msgs:
                out.append({"type": "push", "repo": repo, "commits": msgs[:5]})

        elif kind == "CreateEvent":
            ref_type = payload.get("ref_type", "")
            ref = payload.get("ref", "")
            if ref_type in ("repository", "branch", "tag"):
                out.append({"type": "create", "repo": repo, "ref_type": ref_type, "ref": ref})

        elif kind == "PullRequestEvent":
            action = payload.get("action", "")
            pr = (payload.get("pull_request") or {})
            title = pr.get("title", "")[:_MAX_COMMIT_MSG_CHARS]
            if action in ("opened", "closed", "merged") and title:
                out.append({"type": "pull_request", "repo": repo, "action": action, "title": title})

        elif kind == "IssuesEvent":
            action = payload.get("action", "")
            issue = payload.get("issue") or {}
            title = issue.get("title", "")[:_MAX_COMMIT_MSG_CHARS]
            if action == "opened" and title:
                out.append({"type": "issue", "repo": repo, "title": title})

        elif kind == "ReleaseEvent":
            release = payload.get("release") or {}
            name = (release.get("name") or release.get("tag_name", ""))[:_MAX_COMMIT_MSG_CHARS]
            if name:
                out.append({"type": "release", "repo": repo, "name": name})

        if len(out) >= 20:
            break

    return out
