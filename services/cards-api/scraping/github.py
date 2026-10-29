import asyncio
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

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
        if user_resp.status_code == 404:
            return {}
        if user_resp.status_code == 403:
            # Rate-limited / token missing — skip GitHub rather than fail onboard.
            return {}
        user_resp.raise_for_status()
        if not repos_resp.is_success:
            repos_data = []
        else:
            repos_data = repos_resp.json()
        events = events_resp.json() if events_resp.is_success else []

    recent_activity = _parse_events(events)
    user_data = user_resp.json()

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


# --- Notable activity for the feed -------------------------------------------------------------
# _parse_events above drops event timestamps and links because card synthesis only needs a summary.
# The feed needs to say WHEN something happened and link to it, so it reads the same public events
# again through these two functions. They are separate on purpose: _parse_events' output feeds the
# synthesis prompt and must not change shape.

_HANDLE_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")
_GITHUB_WEB = "https://github.com/"
_FEED_TITLE_CHARS = 140
_FEED_EVENTS = 50              # one page of public events
_FEED_TIMEOUT_SECONDS = 10


def github_handle_from_url(url: str | None) -> str | None:
    """The username in a profile link such as https://github.com/octocat, or None when the link is
    not a plain github.com profile. Checked against GitHub's username rules, so it is safe to put
    into an API path."""
    if not isinstance(url, str) or not url.strip():
        return None
    raw = url.strip()
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    if (parsed.hostname or "").lower().removeprefix("www.") != "github.com":
        return None
    first = parsed.path.strip("/").split("/")[0]
    return first if _HANDLE_RE.match(first) else None


def _web_url(candidate, fallback: str) -> str:
    """A GitHub web link from the event, or the fallback: the feed renders it as an <a href>."""
    return candidate if isinstance(candidate, str) and candidate.startswith(_GITHUB_WEB) else fallback


def parse_notable_events(events: list, handle: str = "") -> list[dict]:
    """Releases, new public repositories and merged pull requests from a user's public events, each
    with its timestamp and link: [{"id", "type": "release"|"repo"|"pull_request", "repo", "title",
    "url", "at"}], in the order GitHub returns them (newest first).

    Pushes, branches, tags and issues are noise in a feed and are skipped. A pull request counts for
    the person who wrote it: the events of a maintainer who merges someone else's pull request carry
    the same "closed + merged" payload, so with a `handle` the pull request's author must match.
    """
    out: list[dict] = []
    for ev in events if isinstance(events, list) else []:
        if not isinstance(ev, dict):
            continue
        at = ev.get("created_at")
        repo = (ev.get("repo") or {}).get("name", "")
        if not at or not isinstance(repo, str) or not _REPO_RE.match(repo):
            continue
        payload = ev.get("payload") or {}
        repo_url = _GITHUB_WEB + repo
        kind = ev.get("type")
        item = None

        if kind == "ReleaseEvent" and payload.get("action") == "published":
            release = payload.get("release") or {}
            title = release.get("name") or release.get("tag_name") or ""
            if title and not release.get("draft"):
                item = {"type": "release", "title": title, "url": _web_url(release.get("html_url"), repo_url)}

        elif kind == "CreateEvent" and payload.get("ref_type") == "repository":
            item = {"type": "repo", "title": payload.get("description") or "", "url": repo_url}

        elif kind == "PublicEvent":
            item = {"type": "repo", "title": "", "url": repo_url}

        elif kind == "PullRequestEvent" and payload.get("action") == "closed":
            pr = payload.get("pull_request") or {}
            author = ((pr.get("user") or {}).get("login") or "").lower()
            if pr.get("merged") and pr.get("title") and (not handle or author == handle.lower()):
                item = {"type": "pull_request", "title": pr["title"], "url": _web_url(pr.get("html_url"), repo_url)}

        if item:
            item["title"] = " ".join(str(item["title"]).split())[:_FEED_TITLE_CHARS]
            out.append({"id": str(ev.get("id") or f"{kind}:{repo}:{at}"), "repo": repo, "at": at, **item})
    return out


def fetch_notable_activity(handle: str) -> list[dict] | None:
    """The person's recent notable GitHub activity (see parse_notable_events), read with a blocking
    call because it runs on a feed background thread, never on a request. None when GitHub could
    not be read (rate limit, unknown user, network): the caller keeps what it had and tries later."""
    if not _HANDLE_RE.match(handle or ""):
        return None
    headers = {"Accept": "application/vnd.github+json"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    try:
        resp = httpx.get(f"{GITHUB_API}/users/{handle}/events/public", params={"per_page": _FEED_EVENTS},
                         headers=headers, timeout=_FEED_TIMEOUT_SECONDS)
        if not resp.is_success:
            return None
        return parse_notable_events(resp.json(), handle)
    except Exception:  # noqa: BLE001 — a feed refresh must never raise into its thread
        return None
