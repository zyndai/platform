"""LinkedIn profile + recent posts via Apify actors (no cookies).

Profile: atomus~linkedin-profile-scraper (primary)     — nested under 'profile' key
         bebity~…-profiles-scraper-pay-per-result (fb)  — flat response, widely reliable
Posts:   atomus~linkedin-posts-scraper-pro           — own posts only, newest first, capped at 7
         Jina Reader Activity section                — free fallback when the posts actor
                                                       is unavailable (billing caps, errors)

Both profile and posts fetches run concurrently. Falls back to Jina Reader on Apify failure.
Returns tuple[str, dict | None] — (profile_text, linkedin_stats).
"""

import asyncio
import re
from urllib.parse import urlparse

import httpx

import config

_APIFY_BASE = "https://api.apify.com/v2"
# bebity~linkedin-profile-scraper was renamed; the atomus actor is now primary.
_ACTOR_PROFILE_PRIMARY  = "atomus~linkedin-profile-scraper"
_ACTOR_PROFILE_FALLBACK = "bebity~best-cheapest-linkedin-profiles-scraper-pay-per-result"
_ACTOR_POSTS = "atomus~linkedin-posts-scraper-pro"
_MAX_POSTS = 7
_MAX_CHARS = 12_000

# "[Satya Nadella shared this](https://www.linkedin.com/posts/…)" — how Jina's
# markdown renders every entry in the public-profile Activity section.
_JINA_MARKER = re.compile(
    r"^\[[^\]]*? (shared|reposted) this\]\((https://www\.linkedin\.com/posts/[^)]+)\)"
)
_JINA_MORE = re.compile(r"\[\.\.\.more\]\([^)]+\)")


def _handle_from_url(url: str) -> str | None:
    """Extract the profile handle. LinkedIn URLs are /in/{handle}."""
    parts = urlparse(url).path.strip("/").split("/")
    if not parts or not parts[0]:
        return None
    if len(parts) >= 2 and parts[0] == "in":
        return parts[1]
    return parts[0]


def _compact_connections(n: int | str | None) -> str:
    if n is None:
        return "500+"
    try:
        v = int(str(n).replace(",", "").replace("+", "").strip())
        if v >= 500:
            return "500+"
        return str(v)
    except (ValueError, TypeError):
        return str(n)


def _skill_name(s) -> str:
    if isinstance(s, str):
        return s
    if isinstance(s, dict):
        return s.get("name") or s.get("skill") or ""
    return ""


def _parse_bebity_profile(record: dict) -> tuple[str, dict | None]:
    """Parse flat bebity~linkedin-profile-scraper response."""
    parts: list[str] = []

    full_name = (
        record.get("fullName")
        or f"{record.get('firstName', '')} {record.get('lastName', '')}".strip()
    )
    if full_name:
        parts.append(f"Name: {full_name}")
    if record.get("headline"):
        parts.append(f"Headline: {record['headline']}")

    about = record.get("summary") or record.get("about") or record.get("description") or ""
    if about:
        parts.append(f"About: {about}")

    loc = record.get("location") or ""
    if isinstance(loc, dict):
        loc = loc.get("default") or loc.get("name") or ""
    if loc:
        parts.append(f"Location: {loc}")

    pic = (
        record.get("profilePicture")
        or record.get("pictureUrl")
        or record.get("profilePicUrl")
        or record.get("imgUrl")
        or ""
    )
    if pic and pic.startswith("http"):
        parts.append(f"Avatar URL: {pic}")

    skills = record.get("skills") or []
    skill_names = [n for n in (_skill_name(s) for s in skills) if n]
    if skill_names:
        parts.append(f"Skills: {', '.join(skill_names[:30])}")

    experience = record.get("experience") or record.get("positions") or []
    for exp in experience[:3]:
        if not isinstance(exp, dict):
            continue
        title = exp.get("title") or exp.get("position") or ""
        company = exp.get("companyName") or exp.get("company") or ""
        if isinstance(company, dict):
            company = company.get("name") or ""
        if title or company:
            entry = f"{title} at {company}".strip(" at")
            parts.append(f"Experience: {entry}")

    connections_raw = (
        record.get("connections")
        or record.get("connectionsCount")
        or record.get("connectionCount")
        or record.get("connections_count")
    )
    linkedin_stats: dict | None = None
    if connections_raw is not None or pic:
        linkedin_stats = {
            "connections": _compact_connections(connections_raw) if connections_raw is not None else "500+",
            "posts": 0,
        }
        if pic:
            linkedin_stats["avatar"] = pic

    return "\n".join(parts), linkedin_stats


def _parse_atomus_profile(record: dict) -> tuple[str, dict | None]:
    """Parse atomus~linkedin-profile-scraper response — nested under 'profile' key.
    Does NOT check 'status' field — extracts whatever data is present."""
    profile = record.get("profile") or {}

    # If no nested profile object, the actor may have returned a flat structure
    if not profile and (record.get("headline") or record.get("fullName")):
        return _parse_bebity_profile(record)

    parts: list[str] = []
    if profile.get("full_name"):
        parts.append(f"Name: {profile['full_name']}")
    if profile.get("title"):
        parts.append(f"Title: {profile['title']}")
    if profile.get("headline"):
        parts.append(f"Headline: {profile['headline']}")
    if profile.get("summary"):
        parts.append(f"About: {profile['summary']}")

    loc = profile.get("location") or {}
    if isinstance(loc, dict) and loc.get("default"):
        parts.append(f"Location: {loc['default']}")
    elif isinstance(loc, str) and loc:
        parts.append(f"Location: {loc}")

    if profile.get("industry"):
        parts.append(f"Industry: {profile['industry']}")

    pic = (
        record.get("picture_url") or record.get("pictureUrl")
        or profile.get("picture_url") or profile.get("pictureUrl") or ""
    )
    if pic and pic.startswith("http"):
        parts.append(f"Avatar URL: {pic}")

    bg = (
        profile.get("background_url") or profile.get("backgroundUrl")
        or record.get("background_url") or ""
    )
    if bg and bg.startswith("http"):
        parts.append(f"Avatar BG URL: {bg}")

    skills = profile.get("skills") or []
    skill_names = [n for n in (_skill_name(s) for s in skills) if n]
    if skill_names:
        parts.append(f"Skills: {', '.join(skill_names[:30])}")

    for group in (profile.get("position_groups") or [])[:3]:
        company = (group.get("company") or {}).get("name") or ""
        for pos in (group.get("profile_positions") or [])[:1]:
            title = pos.get("title") or ""
            if title or company:
                parts.append(f"Experience: {title} at {company}".strip(" at"))

    connections_raw = (
        profile.get("connections_count") or profile.get("connectionsCount")
        or record.get("connections_count")
        or profile.get("followersCount") or profile.get("followers_count")
    )
    linkedin_stats: dict | None = None
    if connections_raw is not None or pic:
        linkedin_stats = {
            "connections": _compact_connections(connections_raw) if connections_raw is not None else "500+",
            "posts": 0,
        }
        if pic:
            linkedin_stats["avatar"] = pic

    return "\n".join(parts), linkedin_stats


async def _run_actor(actor: str, payload: dict, timeout_secs: int = 90) -> list:
    async with httpx.AsyncClient(timeout=timeout_secs + 30) as client:
        resp = await client.post(
            f"{_APIFY_BASE}/acts/{actor}/run-sync-get-dataset-items",
            params={"token": config.APIFY_API_KEY, "timeout": timeout_secs, "memory": 256},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def _fetch_profile(url: str) -> tuple[str, dict | None]:
    # Primary: bebity actor
    try:
        items = await _run_actor(_ACTOR_PROFILE_PRIMARY, {"profileUrls": [url]})
        if items and isinstance(items, list):
            text, stats = _parse_bebity_profile(items[0])
            if text:
                return text, stats
    except Exception:
        pass

    # Fallback: atomus actor
    items = await _run_actor(_ACTOR_PROFILE_FALLBACK, {"profileUrls": [url]})
    if not items:
        return "", None
    return _parse_atomus_profile(items[0])


async def _fetch_posts(url: str) -> tuple[str, int, str | None]:
    """The profile's own recent posts, newest first, via the atomus posts actor.

    Only rows of type "post" whose author username matches the target handle
    are kept; reposts and quote-posts are dropped. Error rows (e.g. the
    account's free-tier event cap) are skipped so the caller can fall back
    to the Jina Activity parse.

    Returns (posts_text, own_post_count, author_avatar_or_None).
    """
    try:
        items = await _run_actor(
            _ACTOR_POSTS,
            {
                "profiles": [url],
                "maxPosts": _MAX_POSTS,
                "sortBy": "date",
                "includeReposts": False,
                "includeSharedPosts": False,
            },
        )
    except Exception:
        items = []
    if not isinstance(items, list):
        return "", 0, None

    handle = _handle_from_url(url)
    lines = ["Recent LinkedIn posts:"]
    post_count = 0
    avatar: str | None = None
    for post in items:
        if not isinstance(post, dict) or post.get("type") != "post":
            continue
        if post.get("is_repost") or post.get("reposted_by"):
            continue
        author = post.get("author") or {}
        author_username = author.get("username")
        if handle and author_username and author_username.lower() != handle.lower():
            continue
        if not avatar and author.get("avatar"):
            avatar = author["avatar"]
        content = (post.get("content") or post.get("text") or post.get("postText") or "").strip()
        if not content:
            continue
        posted = (post.get("posted_at") or "")[:10]
        post_url = post.get("post_url") or post.get("share_url") or ""
        line = f"- [{posted}] {content[:600]}" if posted else f"- {content[:600]}"
        if post_url:
            line += f" {post_url}"
        lines.append(line)
        post_count += 1
        if len(lines) > _MAX_POSTS + 1:
            break
    text = "\n".join(lines) if len(lines) > 1 else ""
    return text, post_count, avatar


def _parse_jina_activity(markdown: str) -> tuple[str, int]:
    """Extract the profile's own posts from Jina's LinkedIn Activity section.

    Public-profile Activity only contains the person's own posts. Jina renders
    each entry as a "[Name shared this](posts url)" marker line followed by the
    post text and a "[public_profile__posts]" terminator (after which reaction
    counts and images appear — skipped). Reposts are dropped.
    """
    idx = markdown.find("## Activity")
    if idx < 0:
        return "", 0
    section = markdown[idx + len("## Activity"):]

    lines = ["Recent LinkedIn posts:"]
    count = 0
    current_url: str | None = None
    current_kind: str | None = None
    current_text: list[str] = []
    in_reactions = False

    def flush() -> bool:
        nonlocal count
        if current_url is None or current_kind == "reposted":
            return False
        content = _JINA_MORE.sub("", " ".join(current_text)).strip()
        content = re.sub(r"\s+", " ", content)
        if not content:
            return False
        lines.append(f"- {content[:600]} {current_url}")
        count += 1
        return count >= _MAX_POSTS

    for raw in section.split("\n"):
        line = raw.strip()
        m = _JINA_MARKER.match(line)
        if m:
            if flush():
                return "\n".join(lines), count
            current_url, current_kind, current_text = m.group(2), m.group(1), []
            in_reactions = False
            continue
        if current_url is None or in_reactions:
            continue
        if not line or line.startswith("[public_profile__posts]"):
            in_reactions = line.startswith("[public_profile__posts]")
            continue
        if line.startswith("[Report this post]") or line.startswith("[![") or line.startswith("### "):
            continue
        current_text.append(line)

    flush()
    return ("\n".join(lines) if count else ""), count


def _parse_jina_avatar(markdown: str) -> str | None:
    """Profile display photo URL from Jina's LinkedIn markdown, if present."""
    m = re.search(
        r"!\[[^\]]*\]\(((?:https?://)?media\.licdn\.com/[^)]*profile-displayphoto[^)]*)\)",
        markdown,
    )
    if not m:
        return None
    url = m.group(1)
    return url if url.startswith("http") else f"https://{url}"


async def _fetch_posts_jina(url: str) -> tuple[str, int, str | None]:
    """Free fallback: parse the Activity section from Jina's render of the profile."""
    from scraping.website import _jina_fetch
    try:
        markdown = await _jina_fetch(url)
    except Exception:
        return "", 0, None
    text, count = _parse_jina_activity(markdown)
    return text, count, _parse_jina_avatar(markdown)


async def _apify_fetch(url: str) -> tuple[str, dict | None]:
    profile_result, posts_result = await asyncio.gather(
        _fetch_profile(url),
        _fetch_posts(url),
        return_exceptions=True,
    )

    parts: list[str] = []
    linkedin_stats: dict | None = None
    posts_count = 0

    if isinstance(profile_result, tuple):
        profile_text, linkedin_stats = profile_result
        if profile_text:
            parts.append(profile_text)

    if isinstance(posts_result, tuple) and len(posts_result) == 3:
        posts_text, posts_count, posts_avatar = posts_result
        if not posts_text:
            # Actor unavailable (billing caps, errors) — fall back to the free
            # Jina Activity parse so LinkedIn posts still flow.
            posts_text, posts_count, posts_avatar = await _fetch_posts_jina(url)
        if posts_text:
            parts.append(posts_text)
        if linkedin_stats is None:
            linkedin_stats = {}
        if posts_count:
            linkedin_stats["posts"] = posts_count
        if posts_avatar and not linkedin_stats.get("avatar"):
            linkedin_stats["avatar"] = posts_avatar
    elif linkedin_stats is None and posts_count:
        linkedin_stats = {"connections": "500+", "posts": posts_count}

    return "\n\n".join(parts)[:_MAX_CHARS], linkedin_stats


async def fetch_linkedin_profile(url: str) -> tuple[str, dict | None]:
    """Scrape LinkedIn profile + recent posts. Returns (text, linkedin_stats)."""
    if config.APIFY_API_KEY:
        try:
            text, stats = await _apify_fetch(url)
            if text:
                return text, stats
        except Exception:
            pass
    from scraping.website import _jina_fetch
    try:
        markdown = await _jina_fetch(url)
        if len(markdown) >= 100:
            posts_text, posts_count = _parse_jina_activity(markdown)
            avatar = _parse_jina_avatar(markdown)
            parts = [markdown[:_MAX_CHARS]]
            if posts_text:
                parts.append(posts_text)
            stats = None
            if posts_count or avatar:
                stats = {"connections": "500+", "posts": posts_count}
                if avatar:
                    stats["avatar"] = avatar
            return "\n\n".join(parts)[:_MAX_CHARS], stats
    except Exception:
        pass
    return "", None
