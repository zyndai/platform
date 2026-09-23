"""
GitHub read-only MCP tools.

Live, on-demand reads of (any repo the token can see) via the stored
GitHub OAuth user token — repo code, issues, pull requests, and account
activity. Complements the snapshot-based tools in mcp/tools/github.py
(which serve the daily-synced profile). All tools are read-only and
principal-private: they are registered on the MCP server but never added
to the external/group allowlists, so foreign agents cannot reach them.

Token handling is delegated to services/github_api.py (fresh-token
resolution, 401 → refresh → retry, rate-limit warnings).

Privacy contract: reads are scoped to what the user's GitHub token can
see. Repo code, issues, and PRs require the GitHub App to grant
Contents/Issues/Pull requests Read; activity endpoints work off the
user token. Nothing is ever written.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone

from mcp.tools.error_utils import friendly_error_message
from services.github_api import api_get
from services.github_sync import get_snapshot

logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 100_000
MAX_TREE_ENTRIES = 1_000


def _err(operation: str, status: int | None, payload) -> dict:
    """Uniform error dict for a failed GitHub call."""
    if status is None:
        return friendly_error_message(
            operation,
            "no token stored — GitHub not connected or token revoked",
            hint="Connect GitHub in Settings → Accounts and try again.",
        )
    detail = ""
    if isinstance(payload, dict):
        detail = payload.get("message") or ""
    msg = f"github returned status {status}: {detail}".strip(": ")
    return friendly_error_message(operation, msg)


def _decode_base64(content: str | None) -> str:
    """Best-effort base64 → UTF-8 decode, truncating to a safe size."""
    if not content:
        return ""
    try:
        text = base64.b64decode(content).decode("utf-8", errors="replace")
    except Exception:
        return ""
    return text[:MAX_CONTENT_CHARS]


def _branch_param(branch: str | None) -> dict:
    return {"ref": branch} if branch else {}


async def _resolve_username(user_id: str) -> str | None:
    """Username from the synced snapshot, else the identity endpoint."""
    snapshot = get_snapshot(user_id)
    if snapshot and snapshot.get("username"):
        return snapshot["username"]
    status, me = await api_get(user_id, "/user")
    if status == 200 and isinstance(me, dict) and me.get("login"):
        return me["login"]
    return None


# ── Repo code ─────────────────────────────────────────────────────────


async def get_repo_contents(user_id: str, repo: str, path: str = "", branch: str | None = None) -> dict:
    """List a directory or read a single file in any repo the GitHub
    token can access. `repo` is `owner/name`. When `path` points at a
    directory, returns its entries; when it points at a file, returns the
    decoded text content (capped at ~100k chars). Pass `branch` for a
    non-default branch. Use when the principal asks what's in a repo or
    wants to see a specific file ('show me the code for X')."""
    url = f"/repos/{repo}/contents/{path.lstrip('/')}" if path else f"/repos/{repo}/contents"
    status, payload = await api_get(user_id, url, _branch_param(branch))
    if status != 200:
        return _err("read that repo path", status, payload)

    if isinstance(payload, list):
        return {
            "success": True,
            "repo": repo,
            "kind": "directory",
            "path": path or "/",
            "entries": [
                {"name": e.get("name"), "type": e.get("type"), "size": e.get("size", 0)}
                for e in payload
            ],
        }

    if isinstance(payload, dict):
        if payload.get("type") == "file":
            content = _decode_base64(payload.get("content"))
            return {
                "success": True,
                "repo": repo,
                "kind": "file",
                "path": payload.get("path", path),
                "size": payload.get("size", 0),
                "content": content,
                "truncated": len(content) == MAX_CONTENT_CHARS,
            }
        if payload.get("type") == "dir":
            status, sub = await api_get(user_id, f"/repos/{repo}/contents", _branch_param(branch))
            if status == 200 and isinstance(sub, list):
                return {
                    "success": True,
                    "repo": repo,
                    "kind": "directory",
                    "path": payload.get("path", path or "/"),
                    "entries": [
                        {"name": e.get("name"), "type": e.get("type"), "size": e.get("size", 0)}
                        for e in sub
                    ],
                }
    return _err("read that repo path", 404, None)


async def get_repo_tree(user_id: str, repo: str, branch: str | None = None, recursive: bool = True) -> dict:
    """Get the full file tree of a repo (`owner/name`) — every file path
    and its type, capped at 1000 entries. `recursive=True` walks the whole
    tree; `recursive=False` returns only the top level. Use when the
    principal wants a map of a repo's structure without pulling file
    bodies."""
    ref = branch or "HEAD"
    url = f"/repos/{repo}/git/trees/{ref}"
    params: dict = {}
    if recursive:
        params["recursive"] = "1"
    status, payload = await api_get(user_id, url, params)
    if status != 200:
        return _err("get that repo's file tree", status, payload)

    tree = payload.get("tree", []) if isinstance(payload, dict) else []
    truncated = len(tree) > MAX_TREE_ENTRIES
    return {
        "success": True,
        "repo": repo,
        "branch": branch or "default",
        "truncated": truncated,
        "path_count": len(tree),
        "paths": [
            {"path": t.get("path"), "type": t.get("type"), "size": t.get("size", 0)}
            for t in tree[:MAX_TREE_ENTRIES]
        ],
    }


async def read_repo_readme(user_id: str, repo: str, branch: str | None = None) -> dict:
    """Read the README of any repo the token can access (`owner/name`),
    rendered as text. Use when the principal asks 'what is this repo
    about' or wants the docs — the README is the fastest orientation."""
    url = f"/repos/{repo}/readme"
    status, payload = await api_get(user_id, url, _branch_param(branch))
    if status != 200:
        return _err("read that repo's README", status, payload)

    return {
        "success": True,
        "repo": repo,
        "path": payload.get("path"),
        "content": _decode_base64(payload.get("content")),
    }


async def list_recent_commits(user_id: str, repo: str, branch: str | None = None, limit: int = 20) -> dict:
    """List the most recent commits in a repo (`owner/name`), newest
    first, with author, date, and message. `limit` defaults to 20 (max
    100). Use when the principal wants to know what's happening in a repo
    — recent activity, who pushed what, or what changed."""
    params = _branch_param(branch)
    params["per_page"] = min(max(limit, 1), 100)
    status, payload = await api_get(user_id, f"/repos/{repo}/commits", params)
    if status != 200:
        return _err("list commits in that repo", status, payload)

    commits = payload if isinstance(payload, list) else []
    return {
        "success": True,
        "repo": repo,
        "commits": [
            {
                "sha": c.get("sha", "")[:10],
                "message": (c.get("commit") or {}).get("message", "").splitlines()[0] if (c.get("commit") or {}).get("message") else "",
                "author": ((c.get("commit") or {}).get("author") or {}).get("name", ""),
                "date": ((c.get("commit") or {}).get("author") or {}).get("date", ""),
                "url": c.get("html_url", ""),
            }
            for c in commits
        ],
    }


async def search_repositories(user_id: str, query: str, limit: int = 10) -> dict:
    """Search GitHub repositories by keyword (`query`), returning matching
    repos with description, language, stars, and URL. Use when the
    principal wants to find a repo — theirs or anyone's — by name, topic,
    or technology."""
    params = {"q": query, "per_page": str(min(max(limit, 1), 50))}
    status, payload = await api_get(user_id, "/search/repositories", params)
    if status != 200:
        return _err("search repositories", status, payload)

    items = payload.get("items", []) if isinstance(payload, dict) else []
    return {
        "success": True,
        "query": query,
        "total_count": (payload or {}).get("total_count", 0),
        "repositories": [
            {
                "full_name": r.get("full_name", ""),
                "description": (r.get("description") or "").strip(),
                "language": r.get("language"),
                "stars": r.get("stargazers_count", 0),
                "html_url": r.get("html_url", ""),
            }
            for r in items
        ],
    }


# ── Issues & pull requests ───────────────────────────────────────────


def _is_pull_request(issue: dict) -> bool:
    return bool(issue.get("pull_request"))


async def list_repo_issues(user_id: str, repo: str, state: str = "open", limit: int = 20) -> dict:
    """List issues in a repo (`owner/name`), newest first. `state` is
    'open', 'closed', or 'all'; pull requests are excluded (see
    list_repo_pull_requests). Requires the GitHub App to have 'Issues:
    Read'. Use to triage what's open, what people are reporting, or what
    needs attention."""
    if state not in ("open", "closed", "all"):
        state = "open"
    params = {"state": state, "per_page": str(min(max(limit, 1), 100))}
    status, payload = await api_get(user_id, f"/repos/{repo}/issues", params)
    if status != 200:
        return _err("list issues in that repo", status, payload)

    issues = [i for i in (payload if isinstance(payload, list) else []) if not _is_pull_request(i)]
    return {
        "success": True,
        "repo": repo,
        "state": state,
        "count": len(issues),
        "issues": [
            {
                "number": i.get("number"),
                "title": i.get("title", ""),
                "state": i.get("state"),
                "labels": [l.get("name") for l in (i.get("labels") or [])],
                "created_at": i.get("created_at", ""),
                "comments": i.get("comments", 0),
                "url": i.get("html_url", ""),
            }
            for i in issues
        ],
    }


async def get_issue_details(user_id: str, repo: str, number: int) -> dict:
    """Get full details of one issue — title, state, body, labels,
    assignees, comments count, and created date. Use when the principal
    asks 'what is issue #N' or wants the full text of a specific issue."""
    status, payload = await api_get(user_id, f"/repos/{repo}/issues/{number}")
    if status != 200:
        return _err("read that issue", status, payload)
    if not isinstance(payload, dict) or _is_pull_request(payload):
        return _err("read that issue", 404, {"message": "not an issue (or not found)"})

    return {
        "success": True,
        "repo": repo,
        "number": payload.get("number"),
        "title": payload.get("title", ""),
        "state": payload.get("state"),
        "body": payload.get("body") or "",
        "labels": [l.get("name") for l in (payload.get("labels") or [])],
        "assignees": [a.get("login") for a in (payload.get("assignees") or [])],
        "comments": payload.get("comments", 0),
        "created_at": payload.get("created_at", ""),
        "url": payload.get("html_url", ""),
    }


async def list_repo_pull_requests(user_id: str, repo: str, state: str = "open", limit: int = 20) -> dict:
    """List pull requests in a repo (`owner/name`), newest first. `state`
    is 'open', 'closed', or 'all'. Requires the GitHub App to have
    'Pull requests: Read'. Use to see open PRs, what's awaiting review,
    or review history."""
    if state not in ("open", "closed", "all"):
        state = "open"
    params = {"state": state, "per_page": str(min(max(limit, 1), 100))}
    status, payload = await api_get(user_id, f"/repos/{repo}/pulls", params)
    if status != 200:
        return _err("list pull requests in that repo", status, payload)

    prs = payload if isinstance(payload, list) else []
    return {
        "success": True,
        "repo": repo,
        "state": state,
        "count": len(prs),
        "pull_requests": [
            {
                "number": p.get("number"),
                "title": p.get("title", ""),
                "state": p.get("state"),
                "draft": p.get("draft", False),
                "merged": bool(p.get("merged_at")),
                "author": (p.get("user") or {}).get("login", ""),
                "created_at": p.get("created_at", ""),
                "url": p.get("html_url", ""),
            }
            for p in prs
        ],
    }


async def get_pull_request_details(user_id: str, repo: str, number: int) -> dict:
    """Get full details of one pull request — title, body, author, merge
    status, branch targets, and review state. Use when the principal asks
    'what is PR #N' or wants the details of a specific PR."""
    status, payload = await api_get(user_id, f"/repos/{repo}/pulls/{number}")
    if status != 200:
        return _err("read that pull request", status, payload)
    if not isinstance(payload, dict):
        return _err("read that pull request", 404, {"message": "not found"})

    return {
        "success": True,
        "repo": repo,
        "number": payload.get("number"),
        "title": payload.get("title", ""),
        "state": payload.get("state"),
        "body": payload.get("body") or "",
        "author": (payload.get("user") or {}).get("login", ""),
        "draft": payload.get("draft", False),
        "merged": bool(payload.get("merged_at")),
        "mergeable": payload.get("mergeable"),
        "head": (payload.get("head") or {}).get("ref", ""),
        "base": (payload.get("base") or {}).get("ref", ""),
        "url": payload.get("html_url", ""),
    }


# ── Activity & notifications ──────────────────────────────────────────


async def get_my_recent_activity(user_id: str, days: int = 7, limit: int = 50) -> dict:
    """Summarize the principal's recent GitHub activity (pushes, PRs,
    issues, releases, stars) over the last `days` (default 7). Reads the
    user's public event feed. Use when the principal asks 'what did I do
    on GitHub this week' or wants a recap of their activity."""
    username = await _resolve_username(user_id)
    if not username:
        return friendly_error_message(
            "summarize your GitHub activity",
            "couldn't determine the GitHub username",
            hint="Connect GitHub in Settings → Accounts and try again.",
        )

    status, payload = await api_get(
        user_id, f"/users/{username}/events", {"per_page": str(min(max(limit, 1), 100))}
    )
    if status != 200:
        return _err("read your GitHub activity", status, payload)

    events = payload if isinstance(payload, list) else []
    cutoff = datetime.now(timezone.utc).timestamp() - (max(days, 1) * 86400)

    interesting: list[dict] = []
    summaries = {
        "PushEvent": "pushed",
        "CreateEvent": "created",
        "DeleteEvent": "deleted",
        "PullRequestEvent": "opened/updated a PR",
        "IssuesEvent": "opened/updated an issue",
        "IssueCommentEvent": "commented on an issue or PR",
        "PullRequestReviewEvent": "reviewed a PR",
        "ReleaseEvent": "released",
        "WatchEvent": "starred",
        "ForkEvent": "forked",
        "PublicEvent": "made public",
    }
    for e in events:
        try:
            ts = datetime.fromisoformat((e.get("created_at") or "").replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            continue
        if ts < cutoff:
            continue
        etype = e.get("type", "")
        if etype not in summaries:
            continue
        repo = (e.get("repo") or {}).get("name", "")
        payload_obj = e.get("payload") or {}
        action = payload_obj.get("action", "")
        interesting.append(
            {
                "date": (e.get("created_at") or "")[:10],
                "type": etype,
                "action": action,
                "summary": f"{summaries[etype]}",
                "repo": repo,
                "url": f"https://github.com/{repo}",
            }
        )

    return {
        "success": True,
        "username": username,
        "days": days,
        "events": interesting[:limit],
    }


async def list_my_notifications(user_id: str, limit: int = 20, unread_only: bool = True) -> dict:
    """List the principal's GitHub notifications — unread by default.
    `unread_only=False` includes read ones. Use when the principal asks
    what needs their attention on GitHub (mentions, reviews, issue
    updates they're watching)."""
    params = {"per_page": str(min(max(limit, 1), 100))}
    if unread_only:
        params["all"] = "false"
    status, payload = await api_get(user_id, "/notifications", params)
    if status != 200:
        return _err("read your GitHub notifications", status, payload)

    notifs = payload if isinstance(payload, list) else []
    return {
        "success": True,
        "unread_only": unread_only,
        "count": len(notifs),
        "notifications": [
            {
                "reason": n.get("reason", ""),
                "unread": n.get("unread", False),
                "updated_at": n.get("updated_at", ""),
                "type": (n.get("subject") or {}).get("type", ""),
                "title": (n.get("subject") or {}).get("title", ""),
                "url": (n.get("subject") or {}).get("url", ""),
            }
            for n in notifs
        ],
    }


async def list_starred_repos(user_id: str, limit: int = 30) -> dict:
    """List repos the principal has starred, newest first, with language
    and stars. Use when the principal asks what they've starred, wants to
    recall a repo they saved, or is curating their favorites."""
    params = {"per_page": str(min(max(limit, 1), 100)), "sort": "created", "direction": "desc"}
    status, payload = await api_get(user_id, "/user/starred", params)
    if status != 200:
        return _err("read your starred repos", status, payload)

    repos = payload if isinstance(payload, list) else []
    return {
        "success": True,
        "count": len(repos),
        "repositories": [
            {
                "full_name": r.get("full_name", ""),
                "description": (r.get("description") or "").strip(),
                "language": r.get("language"),
                "stars": r.get("stargazers_count", 0),
                "html_url": r.get("html_url", ""),
            }
            for r in repos
        ],
    }


async def list_my_orgs(user_id: str) -> dict:
    """List GitHub organizations the principal belongs to, with their
    role and description. Use when the principal asks what orgs they're
    in or which GitHub accounts/groups they belong to."""
    status, payload = await api_get(user_id, "/user/orgs", {"per_page": "100"})
    if status != 200:
        return _err("read your organizations", status, payload)

    orgs = payload if isinstance(payload, list) else []
    return {
        "success": True,
        "count": len(orgs),
        "organizations": [
            {"login": o.get("login", ""), "description": o.get("description") or ""}
            for o in orgs
        ],
    }