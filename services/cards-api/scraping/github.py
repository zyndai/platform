import asyncio

import httpx

import config

GITHUB_API = "https://api.github.com"
_MAX_EVENTS = 30
_MAX_COMMIT_MSG_CHARS = 120


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
        # events may 404 for some accounts — degrade gracefully
        events = events_resp.json() if events_resp.is_success else []

    recent_activity = _parse_events(events)

    return {
        "user": user_resp.json(),
        "repos": repos_resp.json(),
        "recent_activity": recent_activity,
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
