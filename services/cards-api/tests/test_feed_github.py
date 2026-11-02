"""GitHub activity for the feed: parsing keeps only releases, new repositories and merged pull
requests (with their timestamps), the synthesis parser is untouched, and the cache never makes a
request wait on GitHub."""
import threading

import pytest

from scraping import github
from services import feed_github


def ev(kind, repo="ana/lib", at="2026-10-27T10:00:00Z", **payload):
    return {"id": f"{kind}-{at}", "type": kind, "repo": {"name": repo}, "created_at": at, "payload": payload}


EVENTS = [
    ev("PushEvent", commits=[{"message": "wip"}]),
    ev("ReleaseEvent", action="published", release={"name": "v1.2", "tag_name": "v1.2", "html_url": "https://github.com/ana/lib/releases/tag/v1.2"}),
    ev("CreateEvent", repo="ana/new-thing", ref_type="repository", description="A new thing"),
    ev("CreateEvent", ref_type="branch", ref="feature"),
    ev("CreateEvent", ref_type="tag", ref="v1"),
    ev("IssuesEvent", action="opened", issue={"title": "Bug"}),
    ev("PullRequestEvent", repo="org/proj", action="opened", pull_request={"title": "Open PR", "user": {"login": "ana"}}),
    ev("PullRequestEvent", repo="org/proj", action="closed",
       pull_request={"title": "Closed unmerged", "merged": False, "user": {"login": "ana"}}),
    ev("PullRequestEvent", repo="org/proj", action="closed",
       pull_request={"title": "Fix parser", "merged": True, "user": {"login": "Ana"}, "html_url": "https://github.com/org/proj/pull/9"}),
    ev("PullRequestEvent", repo="org/proj", action="closed",
       pull_request={"title": "Someone else's PR", "merged": True, "user": {"login": "carol"}}),
]


def test_only_releases_new_repos_and_merged_prs_are_kept_with_timestamps_and_links():
    out = github.parse_notable_events(EVENTS, "ana")
    assert [(i["type"], i["repo"], i["title"], i["url"]) for i in out] == [
        ("release", "ana/lib", "v1.2", "https://github.com/ana/lib/releases/tag/v1.2"),
        ("repo", "ana/new-thing", "A new thing", "https://github.com/ana/new-thing"),
        ("pull_request", "org/proj", "Fix parser", "https://github.com/org/proj/pull/9"),
    ]
    assert all(i["at"] == "2026-10-27T10:00:00Z" and i["id"] for i in out)


def test_events_without_a_timestamp_or_a_sane_repo_name_are_skipped():
    bad = [{**EVENTS[1], "created_at": None}, {**EVENTS[1], "repo": {"name": "../../etc"}}, "junk", None]
    assert github.parse_notable_events(bad, "ana") == []
    assert github.parse_notable_events(None) == []


def test_a_link_that_is_not_on_github_falls_back_to_the_repository():
    out = github.parse_notable_events([ev("ReleaseEvent", action="published",
                                          release={"name": "v1", "html_url": "javascript:alert(1)"})])
    assert out[0]["url"] == "https://github.com/ana/lib"


def test_draft_and_unpublished_releases_are_skipped():
    drafts = [ev("ReleaseEvent", action="created", release={"name": "v1"}),
              ev("ReleaseEvent", action="published", release={"name": "v2", "draft": True})]
    assert github.parse_notable_events(drafts) == []


def test_the_synthesis_parser_is_unchanged():
    out = github._parse_events(EVENTS)
    assert {"type": "release", "repo": "ana/lib", "name": "v1.2"} in out
    assert all("at" not in item and "url" not in item for item in out)


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/octocat", "octocat"),
    ("https://www.github.com/octocat/", "octocat"),
    ("github.com/octo-cat/some-repo", "octo-cat"),
    ("https://gitlab.com/octocat", None),
    ("https://github.com/-bad", None),
    ("https://github.com/", None),
    ("", None),
    (None, None),
])
def test_github_handle_from_url(url, expected):
    assert github.github_handle_from_url(url) == expected


# --- The cache ---------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_cache():
    feed_github.clear()
    yield
    feed_github.clear()


def test_get_returns_at_once_and_fills_in_from_a_background_read(monkeypatch):
    release, done = threading.Event(), threading.Event()

    def slow_fetch(handle):
        release.wait(5)               # GitHub is "slow": a request must not wait for this
        done.set()
        return [{"id": "1", "type": "release", "repo": "ana/lib", "title": "v1", "url": "https://github.com/ana/lib", "at": "2026-10-27T10:00:00Z"}]

    monkeypatch.setattr(github, "fetch_notable_activity", slow_fetch)
    assert feed_github.get(["ana"]) == {}              # nothing cached yet, and it returned without waiting
    release.set()
    assert done.wait(5)
    for _ in range(100):
        if feed_github.get(["ana"]):
            break
        threading.Event().wait(0.02)
    assert feed_github.get(["ana"])["ana"][0]["title"] == "v1"


def test_a_handle_is_read_once_while_fresh_and_again_when_stale(monkeypatch):
    calls = []
    monkeypatch.setattr(github, "fetch_notable_activity", lambda h: calls.append(h) or [])
    feed_github.get(["ana"])
    _wait_for(lambda: len(calls) == 1)
    feed_github.get(["ana"])
    feed_github.get(["ana"])
    assert calls == ["ana"]
    monkeypatch.setattr(feed_github, "GITHUB_TTL_SECONDS", -1)
    feed_github.get(["ana"])
    _wait_for(lambda: len(calls) == 2)


def test_stale_items_keep_serving_and_a_failed_refresh_keeps_them(monkeypatch):
    item = {"id": "1", "type": "repo", "repo": "ana/x", "title": "", "url": "https://github.com/ana/x", "at": "2026-10-27T10:00:00Z"}
    results = iter([[item], None])
    calls = []
    monkeypatch.setattr(github, "fetch_notable_activity", lambda h: calls.append(h) or next(results))
    feed_github.get(["ana"])
    _wait_for(lambda: len(calls) == 1 and feed_github.get(["ana"]) != {})
    monkeypatch.setattr(feed_github, "GITHUB_TTL_SECONDS", -1)
    assert feed_github.get(["ana"])["ana"] == [item]               # stale, served while it reloads
    _wait_for(lambda: len(calls) == 2)
    monkeypatch.setattr(feed_github, "GITHUB_TTL_SECONDS", 3600)
    _wait_for(lambda: not feed_github._queued)
    assert feed_github.get(["ana"])["ana"] == [item]               # GitHub failed: the old items stay


def test_one_call_queues_a_bounded_number_of_reads(monkeypatch):
    calls = []
    monkeypatch.setattr(github, "fetch_notable_activity", lambda h: calls.append(h) or [])
    handles = [f"user{i}" for i in range(feed_github.MAX_QUEUED_PER_CALL + 25)]
    feed_github.get(handles)
    _wait_for(lambda: not feed_github._queued)
    assert len(calls) == feed_github.MAX_QUEUED_PER_CALL


def _wait_for(check, tries=200):
    for _ in range(tries):
        if check():
            return
        threading.Event().wait(0.02)
    raise AssertionError("background read did not finish")
