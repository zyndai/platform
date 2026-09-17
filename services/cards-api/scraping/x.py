"""X / Twitter profile + recent tweets via Apify (data-slayer, no auth).

Profile: data-slayer~twitter-user  — $1.50/1K profiles
Tweets:  data-slayer~twitter-user-tweets — $1.50/1K tweets, capped at 10

Both fetches run concurrently. Falls back to Jina Reader on Apify failure.
Returns tuple[str, dict | None] — (profile_text, x_stats).
"""

import asyncio
import html
import re
from datetime import datetime
from urllib.parse import urlparse

import httpx

import config

_APIFY_BASE = "https://api.apify.com/v2"
_ACTOR_PROFILE = "data-slayer~twitter-user"
_ACTOR_TWEETS  = "data-slayer~twitter-user-tweets"
_MAX_TWEETS = 7
_MAX_CHARS = 12_000


def _handle_from_url(url: str) -> str | None:
    parts = urlparse(url).path.strip("/").split("/")
    handle = parts[0] if parts and parts[0] else None
    if handle and handle.startswith("@"):
        handle = handle[1:]
    return handle


def _compact(n: int | float) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".rstrip("0").rstrip(".")
    if n >= 1_000:
        return f"{n / 1_000:.1f}k".rstrip("0").rstrip(".")
    return str(int(n))


async def fetch_x_profile(url: str) -> tuple[str, dict | None]:
    """Scrape public X/Twitter profile + recent tweets. Returns (text, x_stats)."""
    if config.APIFY_API_KEY:
        try:
            text, stats = await _apify_fetch(url)
            if text:
                return text, stats
        except Exception:
            pass
    from scraping.website import _jina_fetch
    try:
        return (await _jina_fetch(url))[:_MAX_CHARS], None
    except Exception:
        return "", None


async def _apify_fetch(url: str) -> tuple[str, dict | None]:
    handle = _handle_from_url(url)
    if not handle:
        raise ValueError(f"Cannot extract handle from URL: {url!r}")

    profile_result, tweets_result = await asyncio.gather(
        _fetch_profile(handle),
        _fetch_tweets(handle),
        return_exceptions=True,
    )

    parts: list[str] = []
    x_stats: dict | None = None

    if isinstance(profile_result, tuple):
        profile_text, x_stats = profile_result
        if profile_text:
            parts.append(profile_text)
    elif isinstance(profile_result, str) and profile_result:
        parts.append(profile_result)

    if isinstance(tweets_result, tuple) and len(tweets_result) == 2:
        tweets_text, tweets_posts = tweets_result
        if tweets_text:
            parts.append(tweets_text)
        if tweets_posts:
            if x_stats is None:
                x_stats = {}
            x_stats["posts_raw"] = tweets_posts

    return "\n\n".join(parts)[:_MAX_CHARS], x_stats


async def _fetch_profile(handle: str) -> tuple[str, dict | None]:
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            f"{_APIFY_BASE}/acts/{_ACTOR_PROFILE}/run-sync-get-dataset-items",
            params={"token": config.APIFY_API_KEY, "timeout": 60, "memory": 256},
            json={"username": handle},
        )
        resp.raise_for_status()
        items = resp.json()

    if not items:
        return "", None

    user = items[0]
    parts: list[str] = []
    if user.get("name"):
        parts.append(f"Name: {user['name']}")
    if user.get("profile") or handle:
        parts.append(f"Handle: @{user.get('profile') or handle}")
    if user.get("desc"):
        parts.append(f"Bio: {user['desc']}")
    if user.get("location"):
        parts.append(f"Location: {user['location']}")

    followers = user.get("sub_count")
    if followers is not None:
        parts.append(f"Followers: {followers}")

    tweet_count = user.get("statuses_count") or user.get("tweet_count") or user.get("tweets")
    if tweet_count is not None:
        parts.append(f"Tweets: {tweet_count}")

    if user.get("blue_verified"):
        parts.append("Verified: yes")

    x_stats: dict | None = None
    actual_handle = user.get("profile") or user.get("username") or handle
    if followers is not None or tweet_count is not None or user.get("avatar"):
        x_stats = {
            "handle": f"@{actual_handle}",
            "followers": _compact(followers) if followers is not None else "—",
            "posts": _compact(tweet_count) if tweet_count is not None else "—",
            "impressions": "—",
        }
        if user.get("avatar"):
            x_stats["avatar"] = user["avatar"]

    return "\n".join(parts), x_stats


def _parse_twitter_date(value: str | None) -> datetime | None:
    """Twitter's created_at format: 'Wed Dec 18 09:15:22 +0000 2025'."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        return None


async def _fetch_tweets(handle: str) -> tuple[str, list[dict]]:
    """Returns (tweets_text, structured_posts) — posts feed the card's
    writing_samples deterministically so both platforms are always represented."""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{_APIFY_BASE}/acts/{_ACTOR_TWEETS}/run-sync-get-dataset-items",
            params={"token": config.APIFY_API_KEY, "timeout": 90, "memory": 256},
            json={"userId": handle, "maxPages": 2},
        )
        resp.raise_for_status()
        items = resp.json()

    if not items:
        return "", []

    # The actor doesn't guarantee ordering — sort newest first. Tweets with
    # no parsable date sink to the bottom rather than breaking the sort.
    def _ts(tweet) -> float:
        d = _parse_twitter_date(tweet.get("created_at"))
        return d.timestamp() if d else 0.0

    items = sorted(items, key=_ts, reverse=True)

    lines = ["Recent posts:"]
    posts: list[dict] = []
    for tweet in items[:_MAX_TWEETS * 3]:  # over-fetch to compensate for filtering
        # Only the target account's own tweets — rows whose author doesn't
        # match the requested handle are dropped defensively.
        author_screen_name = (tweet.get("author") or {}).get("screen_name")
        if author_screen_name and author_screen_name.lower() != handle.lower():
            continue
        text = (tweet.get("text") or "").strip()
        if not text:
            continue
        # Skip replies, retweets, pure emoji/URL reactions, and junk posts
        if text.startswith("@") or text.startswith("RT "):
            continue
        stripped = text.replace(" ", "").replace("\n", "")
        meaningful = re.sub(r"[^\w]", "", stripped)
        if len(meaningful) < 12:
            continue
        parsed = _parse_twitter_date(tweet.get("created_at"))
        posted = parsed.strftime("%Y-%m-%d") if parsed else ""
        tid = tweet.get("tweet_id")
        url = f" https://x.com/{handle}/status/{tid}" if tid else ""
        lines.append(f"- [{posted}] {text[:600]}{url}" if posted else f"- {text[:600]}{url}")
        posts.append({
            "platform": "x",
            "excerpt": html.unescape(text)[:500],
            "url": f"https://x.com/{handle}/status/{tid}" if tid else "",
            "posted_at": posted,
        })
        if len(posts) >= _MAX_TWEETS:
            break
    return ("\n".join(lines) if len(lines) > 1 else ""), posts
