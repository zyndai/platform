"""
Tests for the GitHub read-only MCP tools (backend/mcp/tools/github_read.py).

All tools go through services.github_api.api_get + services.github_sync.
get_snapshot, so we stub those out: no network, no Supabase.

Focused on:
  - success shape per tool (file vs dir, tree, readme, commits, search)
  - issues/PR list filtering (PRs excluded from issues)
  - error paths (non-200, no token → friendly error dict)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from mcp.tools.github_read import (
    get_repo_contents,
    get_repo_tree,
    read_repo_readme,
    list_recent_commits,
    search_repositories,
    list_repo_issues,
    get_issue_details,
    list_repo_pull_requests,
    get_pull_request_details,
    get_my_recent_activity,
    list_my_notifications,
    list_starred_repos,
    list_my_orgs,
)


def _run(coro):
    return asyncio.run(coro)


def _fake_api_get(responses_by_path):
    """Build an AsyncMock whose side_effect returns (status, payload) per
    URL-path prefix match (exact match wins, else first containing)."""
    async def _get(user_id, path, params=None):
        for prefix, (status, payload) in sorted(responses_by_path.items(), key=lambda kv: -len(kv[0])):
            if path.startswith(prefix):
                return status, payload
        return 404, {"message": "faked: no route"}
    return _get


# ── Repo code ─────────────────────────────────────────────────────────


def test_get_repo_contents_reads_file():
    import base64
    content = base64.b64encode(b"print('hello')").decode()
    responses = {"/repos/a/foo/contents": (200, {"type": "file", "path": "a/foo/main.py", "size": 15, "content": content})}
    with patch("mcp.tools.github_read.api_get", new=AsyncMock(side_effect=_fake_api_get(responses))):
        result = _run(get_repo_contents("u1", "a/foo", "main.py"))
    assert result["success"] is True
    assert result["kind"] == "file"
    assert result["content"] == "print('hello')"
    assert result["path"] == "a/foo/main.py"


def test_get_repo_contents_lists_directory():
    responses = {
        "/repos/a/foo/contents": (
            200,
            [
                {"name": "README.md", "type": "file", "size": 10},
                {"name": "src", "type": "dir", "size": 0},
            ],
        )
    }
    with patch("mcp.tools.github_read.api_get", new=AsyncMock(side_effect=_fake_api_get(responses))):
        result = _run(get_repo_contents("u1", "a/foo"))
    assert result["success"] is True
    assert result["kind"] == "directory"
    names = [e["name"] for e in result["entries"]]
    assert "README.md" in names and "src" in names


def test_get_repo_tree_recursive():
    responses = {
        "/repos/a/foo/git/trees": (
            200,
            {"tree": [{"path": "main.py", "type": "blob", "size": 15}, {"path": "src", "type": "tree", "size": 0}]},
        )
    }
    with patch("mcp.tools.github_read.api_get", new=AsyncMock(side_effect=_fake_api_get(responses))):
        result = _run(get_repo_tree("u1", "a/foo"))
    assert result["success"] is True
    assert result["path_count"] == 2
    assert result["paths"][0]["path"] == "main.py"


def test_read_repo_readme_decodes():
    import base64
    encoded = base64.b64encode(b"# Foo\nA test repo.").decode()
    responses = {"/repos/a/foo/readme": (200, {"path": "README.md", "content": encoded})}
    with patch("mcp.tools.github_read.api_get", new=AsyncMock(side_effect=_fake_api_get(responses))):
        result = _run(read_repo_readme("u1", "a/foo"))
    assert result["success"] is True
    assert "# Foo" in result["content"]


def test_list_recent_commits():
    responses = {
        "/repos/a/foo/commits": (
            200,
            [
                {
                    "sha": "abc123def",
                    "commit": {"message": "fix: thing\n\nbody", "author": {"name": "A", "date": "2026-08-30T00:00:00Z"}},
                    "html_url": "https://github.com/a/foo/commit/abc",
                }
            ],
        )
    }
    with patch("mcp.tools.github_read.api_get", new=AsyncMock(side_effect=_fake_api_get(responses))):
        result = _run(list_recent_commits("u1", "a/foo"))
    assert result["success"] is True
    assert result["commits"][0]["sha"] == "abc123def"
    assert result["commits"][0]["message"] == "fix: thing"


def test_search_repositories():
    responses = {
        "/search/repositories": (
            200,
            {"total_count": 1, "items": [{"full_name": "a/foo", "description": "d", "language": "Python", "stargazers_count": 5, "html_url": "u"}]},
        )
    }
    with patch("mcp.tools.github_read.api_get", new=AsyncMock(side_effect=_fake_api_get(responses))):
        result = _run(search_repositories("u1", "agent"))
    assert result["success"] is True
    assert result["repositories"][0]["full_name"] == "a/foo"


# ── Issues & pull requests ────────────────────────────────────────────


def test_list_repo_issues_excludes_pull_requests():
    responses = {
        "/repos/a/foo/issues": (
            200,
            [
                {"number": 1, "title": "real issue", "state": "open", "labels": [{"name": "bug"}]},
                {"number": 2, "title": "a PR", "state": "open", "pull_request": {"url": "p"}},
            ],
        )
    }
    with patch("mcp.tools.github_read.api_get", new=AsyncMock(side_effect=_fake_api_get(responses))):
        result = _run(list_repo_issues("u1", "a/foo"))
    assert result["count"] == 1
    assert result["issues"][0]["title"] == "real issue"


def test_get_issue_details_rejects_pr():
    responses = {
        "/repos/a/foo/issues/5": (200, {"number": 5, "title": "t", "pull_request": {"url": "p"}})
    }
    with patch("mcp.tools.github_read.api_get", new=AsyncMock(side_effect=_fake_api_get(responses))):
        result = _run(get_issue_details("u1", "a/foo", 5))
    assert result["success"] is False


def test_list_repo_pull_requests():
    responses = {
        "/repos/a/foo/pulls": (
            200,
            [{"number": 3, "title": "add feature", "state": "open", "draft": False, "merged_at": None, "user": {"login": "b"}}],
        )
    }
    with patch("mcp.tools.github_read.api_get", new=AsyncMock(side_effect=_fake_api_get(responses))):
        result = _run(list_repo_pull_requests("u1", "a/foo"))
    assert result["success"] is True
    assert result["pull_requests"][0]["title"] == "add feature"
    assert result["pull_requests"][0]["merged"] is False


def test_get_pull_request_details():
    responses = {
        "/repos/a/foo/pulls/3": (
            200,
            {
                "number": 3, "title": "add feature", "state": "open", "body": "desc",
                "user": {"login": "b"}, "draft": False, "merged_at": None,
                "mergeable": True, "head": {"ref": "feat"}, "base": {"ref": "main"},
            },
        )
    }
    with patch("mcp.tools.github_read.api_get", new=AsyncMock(side_effect=_fake_api_get(responses))):
        result = _run(get_pull_request_details("u1", "a/foo", 3))
    assert result["success"] is True
    assert result["mergeable"] is True
    assert result["head"] == "feat" and result["base"] == "main"


# ── Activity & notifications ──────────────────────────────────────────


def test_get_my_recent_activity_uses_snapshot_username():
    events = [
        {"type": "PushEvent", "created_at": "2026-08-29T10:00:00Z", "repo": {"name": "a/foo"}, "payload": {}},
        {"type": "WatchEvent", "created_at": "2026-01-01T00:00:00Z", "repo": {"name": "a/old"}, "payload": {}},
    ]
    responses = {"/users/alice/events": (200, events)}
    with patch("mcp.tools.github_read.api_get", new=AsyncMock(side_effect=_fake_api_get(responses))), \
         patch("mcp.tools.github_read.get_snapshot", return_value={"username": "alice"}):
        result = _run(get_my_recent_activity("u1", days=7))
    assert result["success"] is True
    assert result["username"] == "alice"
    assert result["events"][0]["summary"] == "pushed"
    assert len(result["events"]) == 1  # old event filtered out


def test_list_my_notifications():
    responses = {
        "/notifications": (
            200,
            [{"id": "1", "reason": "review_requested", "unread": True, "updated_at": "2026-08-29T00:00:00Z", "subject": {"type": "PullRequest", "title": "look at this", "url": "u"}}],
        )
    }
    with patch("mcp.tools.github_read.api_get", new=AsyncMock(side_effect=_fake_api_get(responses))):
        result = _run(list_my_notifications("u1"))
    assert result["success"] is True
    assert result["notifications"][0]["title"] == "look at this"


def test_list_starred_repos():
    responses = {
        "/user/starred": (200, [{"full_name": "x/y", "description": "d", "language": "Rust", "stargazers_count": 9, "html_url": "u"}])
    }
    with patch("mcp.tools.github_read.api_get", new=AsyncMock(side_effect=_fake_api_get(responses))):
        result = _run(list_starred_repos("u1"))
    assert result["success"] is True
    assert result["repositories"][0]["full_name"] == "x/y"


def test_list_my_orgs():
    responses = {"/user/orgs": (200, [{"login": "acme", "description": "Acme Inc"}])}
    with patch("mcp.tools.github_read.api_get", new=AsyncMock(side_effect=_fake_api_get(responses))):
        result = _run(list_my_orgs("u1"))
    assert result["success"] is True
    assert result["organizations"][0]["login"] == "acme"


# ── Error paths ───────────────────────────────────────────────────────


def test_readme_404_returns_friendly_error():
    responses = {"/repos/a/foo/readme": (404, {"message": "Not Found"})}
    with patch("mcp.tools.github_read.api_get", new=AsyncMock(side_effect=_fake_api_get(responses))):
        result = _run(read_repo_readme("u1", "a/foo"))
    assert result["success"] is False
    assert "not found" in result["error"].lower() or "wasn't found" in result["error"].lower()


def test_no_token_returns_friendly_error():
    responses = {"/repos/a/foo/readme": (None, None)}
    with patch("mcp.tools.github_read.api_get", new=AsyncMock(side_effect=_fake_api_get(responses))):
        result = _run(read_repo_readme("u1", "a/foo"))
    assert result["success"] is False
    assert "hint" in result


def test_activity_with_no_username_returns_friendly_error():
    with patch("mcp.tools.github_read.get_snapshot", return_value=None), \
         patch("mcp.tools.github_read.api_get", new=AsyncMock(return_value=(404, {"message": "Not Found"}))):
        result = _run(get_my_recent_activity("u1"))
    assert result["success"] is False