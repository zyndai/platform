from datetime import datetime, timezone

import httpx
import pytest

import config
from scraping import github_recaps as github

START = datetime(2026, 10, 1, tzinfo=timezone.utc)
END = datetime(2026, 11, 1, tzinfo=timezone.utc)


def repo(name="alice/tool", **patch):
    return {"full_name": name, "private": False, "created_at": "2026-10-12T12:00:00Z", **patch}


@pytest.fixture
def mock_api(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(config, "GITHUB_TOKEN", "")
    def install(handler):
        monkeypatch.setattr(github.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    return install


@pytest.mark.asyncio
async def test_only_new_owned_public_repos_using_creation_dates(mock_api):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.path == "/users/alice/repos"
        assert request.url.params["sort"] == "created" and request.url.params["direction"] == "desc"
        return httpx.Response(200, json=[repo(), repo(), repo("alice/private", private=True), repo("other/nope"),
            repo("alice/old", created_at="2026-09-30T23:59:59Z", pushed_at="2026-10-15T00:00:00Z"),
            repo("alice/next", created_at="2026-11-01T00:00:00Z"), repo("alice/no-date", created_at=None),
            repo("alice/fork", fork=True)])
    mock_api(handler)
    result = await github.fetch_period_activity("alice", START, END)
    assert result["repositories"] == "partial"  # Missing date is not silently treated as zero activity.
    assert {h["title"] for h in result["items"]} == {"alice/tool", "alice/fork"}
    assert all(h["kind"] == "repository" and h["date"] == "2026-10-12" for h in result["items"])
    assert len(requests) == 1 and "authorization" not in requests[0].headers


@pytest.mark.asyncio
async def test_paginates_then_stops_at_older_repositories(mock_api, monkeypatch):
    monkeypatch.setattr(github, "PAGE_SIZE", 1)
    pages = []
    def handler(request):
        page = int(request.url.params["page"])
        pages.append(page)
        rows = {1: [repo("alice/newer", created_at="2026-11-01T00:00:00Z")],
                2: [repo()], 3: [repo("alice/old", created_at="2026-09-01T00:00:00Z")]}
        return httpx.Response(200, json=rows[page])
    mock_api(handler)
    result = await github.fetch_period_activity("alice", START, END)
    assert result["repositories"] == "complete"
    assert len(result["items"]) == 1 and pages == [1, 2, 3]


@pytest.mark.asyncio
async def test_scan_limit_and_outage_report_partial_and_preserve_fetched_items(mock_api, monkeypatch):
    monkeypatch.setattr(github, "PAGE_SIZE", 1)
    monkeypatch.setattr(github, "REPOSITORY_PAGES", 1)
    mock_api(lambda r: httpx.Response(200, json=[repo()]))
    assert (await github.fetch_period_activity("alice", START, END))["repositories"] == "partial"
    monkeypatch.setattr(github, "REPOSITORY_PAGES", 2)
    mock_api(lambda r: httpx.Response(200, json=[repo()]) if r.url.params["page"] == "1" else httpx.Response(403))
    result = await github.fetch_period_activity("alice", START, END)
    assert result["repositories"] == "partial" and len(result["items"]) == 1


@pytest.mark.asyncio
async def test_unavailable_is_distinct_from_no_new_repositories(mock_api):
    mock_api(lambda r: httpx.Response(429))
    assert await github.fetch_period_activity("alice", START, END) == {"items": [], "repositories": "unavailable"}
    mock_api(lambda r: httpx.Response(200, json=[]))
    assert await github.fetch_period_activity("alice", START, END) == {"items": [], "repositories": "complete"}


@pytest.mark.asyncio
async def test_timezone_uses_exact_creation_timestamp(mock_api):
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("Asia/Kolkata")
    start, end = datetime(2026, 10, 1, tzinfo=zone), datetime(2026, 11, 1, tzinfo=zone)
    mock_api(lambda r: httpx.Response(200, json=[repo(created_at="2026-09-30T20:00:00Z")]))
    result = await github.fetch_period_activity("alice", start, end)
    assert result["items"][0]["date"] == "2026-10-01"


@pytest.mark.asyncio
async def test_timeout_does_not_hang_refresh(mock_api, monkeypatch):
    import asyncio
    monkeypatch.setattr(github, "SCAN_TIMEOUT_SECONDS", 0.05)
    async def handler(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=[])
    mock_api(handler)
    assert await github.fetch_period_activity("alice", START, END) == {"items": [], "repositories": "unavailable"}
