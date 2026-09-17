"""
Tests for the LinkedIn + X scrapers — Apify HTTP calls mocked.

Run: cd backend && python -m pytest tests/test_scraping.py -v
"""
import asyncio
from unittest.mock import AsyncMock

import pytest

from scraping import linkedin, x


# ═══════════════════════════════════════════════════════════════════════════════
# LinkedIn posts
# ═══════════════════════════════════════════════════════════════════════════════

def test_linkedin_posts_keeps_own_posts_only(monkeypatch):
    items = [
        {
            "type": "post",
            "content": "Alice shipped the API v2 today.",
            "posted_at": "2026-03-15T14:30:00.000Z",
            "post_url": "https://www.linkedin.com/feed/update/urn:li:activity:1/",
            "is_repost": False,
            "author": {"username": "alice", "avatar": "https://media.licdn.com/alice.jpg"},
        },
        {
            "type": "post",
            "content": "Bob's unrelated feed post.",
            "posted_at": "2026-03-14T14:30:00.000Z",
            "author": {"username": "bob"},
        },
        {
            "type": "post",
            "content": "Just resharing this.",
            "posted_at": "2026-03-13T14:30:00.000Z",
            "is_repost": True,
            "author": {"username": "alice"},
        },
        {
            "type": "post",
            "content": "",
            "posted_at": "2026-03-12T14:30:00.000Z",
            "author": {"username": "alice"},
        },
    ]
    monkeypatch.setattr(linkedin, "_run_actor", AsyncMock(return_value=items))

    text, count, avatar, posts = asyncio.run(linkedin._fetch_posts("https://www.linkedin.com/in/alice/"))

    assert "Alice shipped the API v2 today" in text
    assert "[2026-03-15]" in text
    assert "Bob's unrelated" not in text
    assert "Just resharing" not in text
    assert count == 1
    assert avatar == "https://media.licdn.com/alice.jpg"
    assert posts == [{
        "platform": "linkedin",
        "excerpt": "Alice shipped the API v2 today.",
        "url": "https://www.linkedin.com/feed/update/urn:li:activity:1/",
        "posted_at": "2026-03-15",
    }]


def test_linkedin_posts_actor_error_rows_are_skipped(monkeypatch):
    items = [
        {"type": "error", "error_kind": "free_tier_limit", "reason": "cap reached"},
    ]
    monkeypatch.setattr(linkedin, "_run_actor", AsyncMock(return_value=items))

    text, count, avatar, posts = asyncio.run(linkedin._fetch_posts("https://www.linkedin.com/in/alice/"))

    assert text == ""
    assert count == 0
    assert avatar is None
    assert posts == []


def test_linkedin_posts_author_match_is_case_insensitive(monkeypatch):
    items = [
        {
            "type": "post",
            "content": "Alice wrote this herself.",
            "posted_at": "2026-03-15T14:30:00.000Z",
            "author": {"username": "ALICE"},
        },
    ]
    monkeypatch.setattr(linkedin, "_run_actor", AsyncMock(return_value=items))

    text, _, _, _ = asyncio.run(linkedin._fetch_posts("https://linkedin.com/in/alice/"))

    assert "Alice wrote this herself" in text


def test_linkedin_posts_actor_error_returns_empty(monkeypatch):
    monkeypatch.setattr(linkedin, "_run_actor", AsyncMock(side_effect=Exception("boom")))

    text, count, avatar, posts = asyncio.run(linkedin._fetch_posts("https://www.linkedin.com/in/alice/"))

    assert text == ""
    assert count == 0
    assert avatar is None
    assert posts == []


def test_linkedin_posts_handle_from_in_url():
    assert linkedin._handle_from_url("https://www.linkedin.com/in/alice/") == "alice"
    assert linkedin._handle_from_url("https://linkedin.com/in/bob") == "bob"
    assert linkedin._handle_from_url("https://www.linkedin.com/") is None


def test_linkedin_apify_fetch_combines_profile_and_posts(monkeypatch):
    async def fake_profile(url):
        return "Name: Alice\nHeadline: Engineer", {"connections": "500+"}

    async def fake_posts(url):
        return ("Recent LinkedIn posts:\n- [2026-03-15] Alice shipped.", 1,
                "https://media.licdn.com/alice.jpg",
                [{"platform": "linkedin", "excerpt": "Alice shipped.", "url": "https://ln/p/1", "posted_at": "2026-03-15"}])

    monkeypatch.setattr(linkedin, "_fetch_profile", fake_profile)
    monkeypatch.setattr(linkedin, "_fetch_posts", fake_posts)

    text, stats = asyncio.run(linkedin._apify_fetch("https://www.linkedin.com/in/alice/"))

    assert "Name: Alice" in text
    assert "Alice shipped" in text
    assert stats["connections"] == "500+"
    assert stats["posts"] == 1
    assert stats["avatar"] == "https://media.licdn.com/alice.jpg"
    assert stats["posts_raw"] == [{"platform": "linkedin", "excerpt": "Alice shipped.",
                                   "url": "https://ln/p/1", "posted_at": "2026-03-15"}]


def test_linkedin_apify_fetch_falls_back_to_jina_when_actor_empty(monkeypatch):
    async def fake_profile(url):
        return "Name: Alice\nHeadline: Engineer", {"connections": "500+"}

    async def fake_posts(url):
        return "", 0, None, []

    async def fake_jina_posts(url):
        return ("Recent LinkedIn posts:\n- Alice via Jina. https://www.linkedin.com/posts/alice_1",
                1, None,
                [{"platform": "linkedin", "excerpt": "Alice via Jina.", "url": "https://www.linkedin.com/posts/alice_1", "posted_at": ""}])

    monkeypatch.setattr(linkedin, "_fetch_profile", fake_profile)
    monkeypatch.setattr(linkedin, "_fetch_posts", fake_posts)
    monkeypatch.setattr(linkedin, "_fetch_posts_jina", fake_jina_posts)

    text, stats = asyncio.run(linkedin._apify_fetch("https://www.linkedin.com/in/alice/"))

    assert "Alice via Jina" in text
    assert stats["posts"] == 1
    assert len(stats["posts_raw"]) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Jina Activity parser
# ═══════════════════════════════════════════════════════════════════════════════

_JINA_SAMPLE = """## Sign in to view Satya's full profile

# Satya Nadella

## Activity
    *   [Report this post](https://www.linkedin.com/uas/login?...)
[Satya Nadella shared this](https://www.linkedin.com/posts/satyanadella_post-one-activity-111-EJS4)
First post text about AI. Learn more: [https://lnkd.in/xyz](https://lnkd.in/xyz?trk=...)[...more](https://www.linkedin.com/posts/satyanadella_post-one-activity-111-EJS4)
[public_profile__posts](https://www.linkedin.com/posts/satyanadella_post-one-activity-111-EJS4)
[![Image 48](https://www.linkedin.com/in/satyanadella/)![Image 49](https://www.linkedin.com/in/satyanadella/) 2,788](https://www.linkedin.com/signup/cold-join?...)[149 Comments](https://www.linkedin.com/signup/cold-join?...)
[](https://www.linkedin.com/signup/cold-join?...)
    *   [Report this post](https://www.linkedin.com/uas/login?...)
[Satya Nadella reposted this](https://www.linkedin.com/posts/other_repost-activity-222-XyZ)
Reposted content that must be skipped.
[public_profile__posts](https://www.linkedin.com/posts/other_repost-activity-222-XyZ)
[Satya Nadella shared this](https://www.linkedin.com/posts/satyanadella_post-two-activity-333-AbC)
Second post text about LLM optimisation work that is substantive enough to keep.
[public_profile__posts](https://www.linkedin.com/posts/satyanadella_post-two-activity-333-AbC)
"""


def test_parse_jina_activity_extracts_own_posts_and_drops_reposts():
    text, count, posts = linkedin._parse_jina_activity(_JINA_SAMPLE)

    assert count == 2
    assert "First post text about AI" in text
    assert "Second post text about LLM" in text
    assert "Reposted content" not in text
    assert "2,788" not in text
    assert "149 Comments" not in text
    assert "post-one-activity-111" in text
    assert "Report this post" not in text
    assert text.count("\n- ") == 2
    assert [p["platform"] for p in posts] == ["linkedin", "linkedin"]
    assert posts[0]["url"] == "https://www.linkedin.com/posts/satyanadella_post-one-activity-111-EJS4"
    assert posts[0]["excerpt"] == "First post text about AI. Learn more: https://lnkd.in/xyz"


def test_parse_jina_activity_drops_comment_rows_and_short_fragments():
    md = """## Activity
[Alice shared this](https://www.linkedin.com/posts/alice_a)
- [Bob Marley](https://www.linkedin.com/in/bob) 7y https://www.linkedin.com/posts/alice_a
[public_profile__posts](https://www.linkedin.com/posts/alice_a)
[Alice shared this](https://www.linkedin.com/posts/alice_b)
Short post.
[public_profile__posts](https://www.linkedin.com/posts/alice_b)
[Alice shared this](https://www.linkedin.com/posts/alice_c)
A genuinely substantive post about shipping infrastructure at scale this quarter.
[public_profile__posts](https://www.linkedin.com/posts/alice_c)
"""
    text, count, posts = linkedin._parse_jina_activity(md)

    assert count == 1
    assert "Bob Marley" not in text
    assert "Short post." not in text
    assert "substantive post about shipping" in text
    assert posts[0]["url"].endswith("alice_c")


def test_parse_jina_activity_missing_section_returns_empty():
    text, count, posts = linkedin._parse_jina_activity("# Just a profile\n\nNo activity here.")
    assert text == ""
    assert count == 0
    assert posts == []


def test_parse_jina_avatar_extracts_displayphoto():
    md = '![Image 2: Satya Nadella](https://media.licdn.com/dms/image/v2/C5603AQH/profile-displayphoto-shrink_200_200/0/1579726625398?e=2147483647&v=beta&t=abc)'
    assert linkedin._parse_jina_avatar(md) is not None
    assert "media.licdn.com" in linkedin._parse_jina_avatar(md)


def test_parse_jina_avatar_none_when_absent():
    assert linkedin._parse_jina_avatar("no images here") is None


def test_linkedin_profile_parser_sets_stats_avatar():
    text, stats = linkedin._parse_bebity_profile({
        "fullName": "Alice",
        "headline": "Engineer",
        "connections": 300,
        "profilePicture": "https://media.licdn.com/dms/alice.jpg",
    })
    assert stats is not None
    assert stats["avatar"] == "https://media.licdn.com/dms/alice.jpg"
    assert stats["connections"] == "300"
    assert stats["posts"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# X / Twitter tweets
# ═══════════════════════════════════════════════════════════════════════════════

class _FakeResp:
    def __init__(self, items):
        self._items = items

    def raise_for_status(self):
        pass

    def json(self):
        return self._items


class _FakeClient:
    def __init__(self, *args, **kwargs):
        self.calls = []
        self.resp = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *args, **kwargs):
        self.calls.append(kwargs)
        return self.resp


def _run_tweets(items):
    client = _FakeClient()
    client.resp = _FakeResp(items)

    import scraping.x as x_module

    original = x_module.httpx.AsyncClient
    x_module.httpx.AsyncClient = lambda *a, **k: client
    try:
        text, posts = asyncio.run(x_module._fetch_tweets("alice"))
        return text, client.calls, posts
    finally:
        x_module.httpx.AsyncClient = original


def test_x_tweets_newest_first_and_filters_junk():
    items = [
        {
            "text": "Older but substantive tweet about infra.",
            "created_at": "Wed Jan 01 09:00:00 +0000 2025",
            "tweet_id": "1",
            "author": {"screen_name": "alice"},
        },
        {
            "text": "@someone thanks!",
            "created_at": "Wed Dec 30 09:00:00 +0000 2025",
            "tweet_id": "2",
            "author": {"screen_name": "alice"},
        },
        {
            "text": "RT @other shared post",
            "created_at": "Wed Dec 31 09:00:00 +0000 2025",
            "tweet_id": "3",
            "author": {"screen_name": "alice"},
        },
        {
            "text": "👍",
            "created_at": "Thu Jan 02 09:00:00 +0000 2025",
            "tweet_id": "4",
            "author": {"screen_name": "alice"},
        },
        {
            "text": "Newest post shipping the feature.",
            "created_at": "Thu Jan 02 10:00:00 +0000 2025",
            "tweet_id": "5",
            "author": {"screen_name": "alice"},
        },
    ]

    text, calls, posts = _run_tweets(items)

    assert text.index("shipping the feature") < text.index("infra")
    assert "@someone" not in text
    assert "RT @" not in text
    assert "👍" not in text
    assert "[2025-01-02]" in text
    assert "https://x.com/alice/status/5" in text
    assert calls and calls[0]["json"] == {"userId": "alice", "maxPages": 2}
    assert len(posts) == 2
    assert posts[0]["platform"] == "x"
    assert posts[0]["url"] == "https://x.com/alice/status/5"
    assert posts[0]["posted_at"] == "2025-01-02"


def test_x_tweets_drops_rows_from_other_authors():
    items = [
        {
            "text": "Alice's own tweet.",
            "created_at": "Thu Jan 02 10:00:00 +0000 2025",
            "tweet_id": "5",
            "author": {"screen_name": "alice"},
        },
        {
            "text": "Bob's tweet that leaked into the dataset.",
            "created_at": "Thu Jan 02 11:00:00 +0000 2025",
            "tweet_id": "6",
            "author": {"screen_name": "bob"},
        },
    ]

    text, _, posts = _run_tweets(items)

    assert "Alice's own tweet" in text
    assert "Bob's tweet" not in text
    assert len(posts) == 1


def test_x_tweets_author_filter_case_insensitive_and_missing_author_allowed():
    items = [
        {
            "text": "Match despite case difference.",
            "created_at": "Thu Jan 02 10:00:00 +0000 2025",
            "tweet_id": "5",
            "author": {"screen_name": "ALICE"},
        },
        {
            "text": "No author field at all.",
            "created_at": "Thu Jan 02 09:00:00 +0000 2025",
            "tweet_id": "6",
        },
    ]

    text, _, posts = _run_tweets(items)

    assert "Match despite case difference" in text
    assert "No author field at all" in text
    assert len(posts) == 2


def test_x_tweets_empty_dataset_returns_empty_string():
    text, _, posts = _run_tweets([])
    assert text == ""
    assert posts == []


def test_x_tweets_parse_twitter_date():
    dt = x._parse_twitter_date("Wed Dec 18 09:15:22 +0000 2025")
    assert dt is not None
    assert (dt.year, dt.month, dt.day) == (2025, 12, 18)
    assert x._parse_twitter_date("garbage") is None
    assert x._parse_twitter_date(None) is None


def test_x_handle_from_url():
    assert x._handle_from_url("https://x.com/alice") == "alice"
    assert x._handle_from_url("https://twitter.com/alice/status/123") == "alice"
    assert x._handle_from_url("https://x.com/@alice") == "alice"
    assert x._handle_from_url("https://x.com/") is None


def test_x_profile_captures_avatar_in_stats():
    client = _FakeClient()
    client.resp = _FakeResp([{
        "name": "Alice",
        "profile": "alice",
        "desc": "Builder",
        "sub_count": 1200,
        "statuses_count": 300,
        "avatar": "https://pbs.twimg.com/profile_images/alice.jpg",
    }])

    import scraping.x as x_module

    original = x_module.httpx.AsyncClient
    x_module.httpx.AsyncClient = lambda *a, **k: client
    try:
        text, stats = asyncio.run(x_module._fetch_profile("alice"))
    finally:
        x_module.httpx.AsyncClient = original

    assert stats is not None
    assert stats["avatar"] == "https://pbs.twimg.com/profile_images/alice.jpg"
    assert stats["handle"] == "@alice"
    assert "Name: Alice" in text


def test_x_apify_fetch_combines_profile_and_tweets_with_posts_raw(monkeypatch):
    async def fake_profile(handle):
        return "Name: Alice\nBio: Builder", {"handle": "@alice", "followers": "1.2k", "posts": "300", "avatar": "https://pbs.twimg.com/a.jpg"}

    async def fake_tweets(handle):
        return ("Recent posts:\n- [2026-01-02] Hello world.", [
            {"platform": "x", "excerpt": "Hello world.", "url": "https://x.com/alice/status/1", "posted_at": "2026-01-02"},
        ])

    monkeypatch.setattr(x, "_fetch_profile", fake_profile)
    monkeypatch.setattr(x, "_fetch_tweets", fake_tweets)

    text, stats = asyncio.run(x._apify_fetch("https://x.com/alice"))

    assert "Name: Alice" in text
    assert "Hello world" in text
    assert stats["avatar"] == "https://pbs.twimg.com/a.jpg"
    assert len(stats["posts_raw"]) == 1
    assert stats["posts_raw"][0]["platform"] == "x"


def test_fetch_x_profile_falls_back_to_jina_when_apify_empty(monkeypatch):
    monkeypatch.setattr(x.config, "APIFY_API_KEY", "fake-key")
    monkeypatch.setattr(x, "_apify_fetch", AsyncMock(return_value=("", None)))

    async def fake_jina(url):
        return "Jina fallback text for X."

    import scraping.website as website

    monkeypatch.setattr(website, "_jina_fetch", fake_jina)

    text, stats = asyncio.run(x.fetch_x_profile("https://x.com/alice"))

    assert text == "Jina fallback text for X."
    assert stats is None


def test_fetch_linkedin_profile_falls_back_to_jina_when_apify_empty(monkeypatch):
    monkeypatch.setattr(linkedin.config, "APIFY_API_KEY", "fake-key")
    monkeypatch.setattr(linkedin, "_apify_fetch", AsyncMock(return_value=("", None)))

    async def fake_jina(url):
        return "Jina fallback text for LinkedIn, long enough to clear the minimum-length guard " * 2

    import scraping.website as website

    monkeypatch.setattr(website, "_jina_fetch", fake_jina)

    text, stats = asyncio.run(linkedin.fetch_linkedin_profile("https://www.linkedin.com/in/alice/"))

    assert text.startswith("Jina fallback text for LinkedIn")
    assert stats is None


def test_fetch_linkedin_profile_jina_keeps_posts_block_within_cap(monkeypatch):
    """A huge Jina page must not truncate the parsed posts block away."""
    monkeypatch.setattr(linkedin.config, "APIFY_API_KEY", "fake-key")
    monkeypatch.setattr(linkedin, "_apify_fetch", AsyncMock(return_value=("", None)))

    markdown = "Profile filler " * 2000 + "\n## Activity\n[Alice shared this](https://www.linkedin.com/posts/alice_1)\nA substantive post from Alice about distributed systems design.\n[public_profile__posts](https://www.linkedin.com/posts/alice_1)\n"

    import scraping.website as website

    monkeypatch.setattr(website, "_jina_fetch", AsyncMock(return_value=markdown))

    text, stats = asyncio.run(linkedin.fetch_linkedin_profile("https://www.linkedin.com/in/alice/"))

    assert len(text) <= linkedin._MAX_CHARS
    assert "A substantive post from Alice about distributed systems design" in text
    assert "Recent LinkedIn posts:" in text
    assert stats is not None and stats["posts"] == 1
    assert len(stats["posts_raw"]) == 1
    assert stats["posts_raw"][0]["platform"] == "linkedin"


def test_extract_experience_data_slayer_current_role():
    record = {
        "full_name": "Abhinav Gupta",
        "experience": [
            {
                "job_title": "Product Manager",
                "company_name": "Zynd",
                "job_started_on": "3-2026",
                "job_still_working": True,
                "logoUrl": "https://media.licdn.com/zynd.png",
                "location": "United States · Remote",
                "job_description": "Building agent infra.",
            },
            {
                "job_title": "Blockchain Engineer",
                "company_name": "Tokamak Network",
                "job_started_on": "12-2025",
                "job_ended_on": "Mar 2026",
                "job_still_working": False,
            },
        ],
    }
    jobs = linkedin._sort_jobs(linkedin._extract_experience_any(record))
    assert jobs[0]["title"] == "Product Manager"
    assert jobs[0]["company"] == "Zynd"
    assert jobs[0]["end_date"] == "Present"
    assert jobs[0]["start_date"] == "Mar 2026"
    assert jobs[0]["duration"]
    assert jobs[0]["company_logo"] == "https://media.licdn.com/zynd.png"
    assert jobs[1]["title"] == "Blockchain Engineer"


def test_extract_experience_top_level_current_and_website_logo():
    record = {
        "job_title": "Protocol and Research",
        "current_company_name": "Zynd",
        "company_website": "zynd.ai",
        "location": "United States · Remote",
        "experience": [],
    }
    jobs = linkedin._extract_experience_any(record)
    assert jobs[0]["title"] == "Protocol and Research"
    assert jobs[0]["company"] == "Zynd"
    assert jobs[0]["end_date"] == "Present"
    assert "logo.clearbit.com/zynd.ai" in jobs[0]["company_logo"]


def test_extract_experience_dev_fusion_yyyy_mm():
    record = {
        "experiences": [
            {
                "title": "Intern",
                "companyName": "NEAR Protocol",
                "jobStartedOn": "2023-07",
                "jobEndedOn": "2023-09",
                "jobStillWorking": False,
                "jobLocation": "Switzerland",
            }
        ]
    }
    jobs = linkedin._extract_experience_any(record)
    assert jobs[0]["title"] == "Intern"
    assert jobs[0]["start_date"] == "Jul 2023"
    assert jobs[0]["end_date"] == "Sep 2023"
    assert jobs[0]["location"] == "Switzerland"


def test_extract_experience_logo_object_and_date_range():
    record = {
        "experience": [{
            "title": "Engineer",
            "company": "Acme",
            "dateRange": "Jan 2024 – Present",
            "companyLogo": {"url": "https://logo.example/acme.png"},
        }]
    }
    jobs = linkedin._extract_experience_any(record)
    assert jobs[0]["end_date"] == "Present"
    assert jobs[0]["company_logo"] == "https://logo.example/acme.png"