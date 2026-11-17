from datetime import datetime, timezone

import httpx
import pytest

import config
from scraping import github_recaps as github

START = datetime(2026, 10, 1, tzinfo=timezone.utc)
END = datetime(2026, 11, 1, tzinfo=timezone.utc)


def release(**patch):
    return {"tag_name": "v1", "name": "First release", "author": {"login": "alice"},
            "draft": False, "prerelease": False, "published_at": "2026-10-12T12:00:00Z", **patch}


def pr(**patch):
    return {"title": "Useful change", "user": {"login": "alice"}, "merged_at": "2026-10-15T12:00:00Z",
            "base": {"repo": {"private": False}}, **patch}


def repo(name="alice/tool", **patch):
    return {"full_name": name, "private": False, **patch}


@pytest.fixture
def mock_api(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(config, "GITHUB_TOKEN", "")
    def install(handler):
        monkeypatch.setattr(github.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    return install


@pytest.mark.asyncio
async def test_uses_actual_public_release_and_merge_dates_and_deduplicates(mock_api):
    requests = []
    def handler(request):
        requests.append(request)
        path = request.url.path
        if path.endswith("/repos"):
            data = [repo(), repo("alice/private", private=True), repo("other/nope")]
        elif path.endswith("/releases"):
            data = [release(), release(), release(tag_name="old", published_at="2026-09-30T23:59:59Z"),
                    release(tag_name="future", published_at="2026-11-01T00:00:00Z"), release(draft=True),
                    release(prerelease=True), release(author={"login": "bob"}), release(published_at=None)]
        elif path == "/search/issues":
            assert "is:public" in request.url.params["q"] and "author:alice" in request.url.params["q"]
            data = {"items": [{"html_url": f"https://github.com/team/project/pull/{i}"} for i in range(1, 6)]}
        else:
            number = path.rsplit("/", 1)[-1]
            data = {"1": pr(), "2": pr(user={"login": "bob"}), "3": pr(base={"repo": {"private": True}}),
                    "4": pr(merged_at=None), "5": pr(merged_at="2026-11-01T00:00:00Z")}[number]
        return httpx.Response(200, json=data)
    mock_api(handler)
    result = await github.fetch_period_activity("alice", START, END)
    assert result["releases"] == result["pull_requests"] == "complete"
    assert {h["kind"] for h in result["items"]} == {"release", "pull_request"}
    assert len(result["items"]) == 2
    assert result["items"][0]["date"] == "2026-10-15"
    assert all(h["source"] == "github" for h in result["items"])
    assert not any("private" in str(r.url) or "nope" in str(r.url) for r in requests)
    assert all("authorization" not in r.headers for r in requests)


@pytest.mark.asyncio
async def test_release_pagination_does_not_stop_on_old_creation_order(mock_api):
    def handler(request):
        if request.url.path.endswith("/repos"):
            data = [repo()]
        elif request.url.path.endswith("/releases"):
            data = ([release(tag_name=f"old-{i}", published_at="2025-01-01T00:00:00Z") for i in range(100)]
                    if request.url.params["page"] == "1" else [release()])
        else:
            data = {"items": []}
        return httpx.Response(200, json=data)
    mock_api(handler)
    result = await github.fetch_period_activity("alice", START, END)
    assert result["releases"] == "complete"
    assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_partial_coverage_and_private_search_links_are_not_followed(mock_api, monkeypatch):
    monkeypatch.setattr(github, "REPOSITORY_LIMIT", 1)
    monkeypatch.setattr(github, "PAGE_SIZE", 1)
    monkeypatch.setattr(github, "PR_PAGES", 2)
    pages = []
    def handler(request):
        if request.url.path.endswith("/repos"):
            data = [repo(), repo("alice/another")]
        elif request.url.path.endswith("/releases"):
            return httpx.Response(403, json={"message": "rate limit"})
        elif request.url.path == "/search/issues":
            pages.append(request.url.params["page"])
            data = {"total_count": 3, "incomplete_results": True,
                    "items": [{"html_url": "https://evil.example/steal-token"}]}
        else:
            pytest.fail(f"Unexpected request {request.url}")
        return httpx.Response(200, json=data)
    mock_api(handler)
    result = await github.fetch_period_activity("alice", START, END)
    assert result == {"items": [], "releases": "partial", "pull_requests": "partial"}
    assert pages == ["1", "2"]


@pytest.mark.asyncio
async def test_unavailable_is_distinct_from_no_activity(mock_api):
    mock_api(lambda r: httpx.Response(429, json={"message": "slow down"}))
    result = await github.fetch_period_activity("alice", START, END)
    assert result == {"items": [], "releases": "unavailable", "pull_requests": "unavailable"}


@pytest.mark.asyncio
async def test_timezone_filter_uses_merge_time_not_search_date(mock_api):
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("Asia/Kolkata")
    start, end = datetime(2026, 10, 1, tzinfo=zone), datetime(2026, 11, 1, tzinfo=zone)
    def handler(request):
        if request.url.path.endswith("/repos"):
            data = []
        elif request.url.path == "/search/issues":
            assert "2026-09-30..2026-10-31" in request.url.params["q"]
            data = {"items": [{"html_url": "https://github.com/team/repo/pull/1"}]}
        else:
            data = pr(merged_at="2026-09-30T20:00:00Z")
        return httpx.Response(200, json=data)
    mock_api(handler)
    result = await github.fetch_period_activity("alice", start, end)
    assert result["items"][0]["date"] == "2026-10-01"


@pytest.mark.asyncio
async def test_timeouts_preserve_successful_source_without_hanging(mock_api, monkeypatch):
    import asyncio
    monkeypatch.setattr(github, "SCAN_TIMEOUT_SECONDS", 0.05)
    async def handler(request):
        if request.url.path == "/search/issues":
            await asyncio.sleep(1)
            return httpx.Response(200, json={"items": []})
        data = [repo()] if request.url.path.endswith("/repos") else [release()]
        return httpx.Response(200, json=data)
    mock_api(handler)
    result = await github.fetch_period_activity("alice", START, END)
    assert result["releases"] == "complete" and result["pull_requests"] == "unavailable"
    assert len(result["items"]) == 1
