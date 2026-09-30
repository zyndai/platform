"""Shared keyword post cache. One post per card section per handle/day."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import httpx

import config
from models.card import AgentProfileCard, WritingSample
from services import cards as cards_service
from services.suggested_people import FIELDS, KEYWORDS

_SHOWN_CAP = 28
_APIFY_BASE = "https://api.apify.com/v2"
_ACTOR = "apidojo~tweet-scraper"

_CANON = {k.lower(): k for opts in KEYWORDS.values() for k in opts}


def keyword_key(phrase: str) -> str:
    return phrase.strip().lower()


def _canonical(phrase: str) -> str:
    raw = (phrase or "").strip()
    return _CANON.get(raw.lower(), raw)


def intent_queries(card: AgentProfileCard) -> list[tuple[str, str]]:
    out = []
    for field in FIELDS:
        phrases = getattr(card, field) or []
        first = next((_canonical(p) for p in phrases if str(p).strip()), "")
        out.append((field, first))
    return out


def queries_hash(queries: list[tuple[str, str]]) -> str:
    blob = "|".join(f"{f}:{q}" for f, q in queries)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _seed(handle: str, day: str, field: str) -> int:
    return int(hashlib.sha256(f"{handle}:{day}:{field}".encode()).hexdigest()[:8], 16)


def pick_day(
    handle: str,
    day: str,
    queries: list[tuple[str, str]],
    pool: dict,
    shown_urls: list[str],
) -> tuple[list[dict | None], dict, list[str]]:
    shown = list(shown_urls)
    leftover = {k: list(v) for k, v in (pool or {}).items()}
    posts: list[dict | None] = []
    for field, query in queries:
        if not query:
            posts.append(None)
            continue
        cands = leftover.get(field) or []
        avail = [c for c in cands if c.get("url") and c["url"] not in shown]
        if not avail:
            posts.append(None)
            continue
        chosen = avail[_seed(handle, day, field) % len(avail)]
        posts.append({**chosen, "field": field, "query": query})
        shown.append(chosen["url"])
        leftover[field] = [c for c in cands if c.get("url") != chosen["url"]]
    return posts, leftover, shown[-_SHOWN_CAP:]


def _tokens(text: str) -> set[str]:
    return {t for t in text.lower().split() if t}


def linkedin_candidates(query: str, samples, exclude_urls: set[str]) -> list[dict]:
    qtok = _tokens(query)
    if not qtok:
        return []
    out = []
    for s in samples or []:
        platform = s.platform if isinstance(s, WritingSample) else s.get("platform")
        url = s.url if isinstance(s, WritingSample) else s.get("url") or ""
        excerpt = s.excerpt if isinstance(s, WritingSample) else s.get("excerpt") or ""
        author = "" if isinstance(s, WritingSample) else s.get("author") or ""
        posted_at = s.posted_at if isinstance(s, WritingSample) else s.get("posted_at") or ""
        if platform != "linkedin" or not url or url in exclude_urls:
            continue
        if not qtok & _tokens(excerpt):
            continue
        out.append({
            "url": url,
            "platform": "linkedin",
            "excerpt": excerpt,
            "author": author,
            "posted_at": posted_at,
        })
    return out


def _keyword_fresh(entry: dict | None, today: str) -> bool:
    return bool(entry and entry.get("fetched_on") == today and entry.get("posts"))


def stitch_summary(queries: list[tuple[str, str]], keyword_cache: dict) -> str | None:
    parts = []
    seen = set()
    for _, query in queries:
        if not query:
            continue
        key = keyword_key(query)
        if key in seen:
            continue
        seen.add(key)
        blurb = (keyword_cache.get(key) or {}).get("summary") or ""
        if blurb:
            parts.append(f"{query}: {blurb}")
    return "\n\n".join(parts) or None


def refresh_snapshot(
    handle: str,
    card: AgentProfileCard,
    snap: dict | None,
    today: str,
    keyword_cache: dict,
    search_x,
    linkedin_samples,
    llm=None,
) -> tuple[dict, dict | None]:
    queries = intent_queries(card)
    qhash = queries_hash(queries)
    snap = snap or {}
    if snap.get("date") == today and snap.get("queries_hash") == qhash and snap.get("summary"):
        return snap, None

    same_day = snap.get("date") == today and snap.get("queries_hash") == qhash
    shown = list(snap.get("shown_urls") or [])
    owner_urls = {s.url for s in (card.writing_samples or []) if s.url}
    pool: dict = {}

    for field, query in queries:
        if not query:
            continue
        key = keyword_key(query)
        entry = keyword_cache.get(key)
        if not _keyword_fresh(entry, today):
            posts = list(search_x(query) or [])
            seen = {p.get("url") for p in posts}
            for p in linkedin_candidates(query, linkedin_samples, owner_urls):
                if p.get("url") and p["url"] not in seen:
                    posts.append(p)
                    seen.add(p["url"])
            entry = {"fetched_on": today, "posts": posts, "summary": ""}
            keyword_cache[key] = entry
        if llm and entry and not entry.get("summary") and entry.get("posts"):
            entry["summary"] = llm(query, entry["posts"]) or ""
            keyword_cache[key] = entry
        cached = entry["posts"] if entry else []
        pool[field] = [
            p for p in cached
            if p.get("url") and p["url"] not in owner_urls
        ]

    if same_day:
        posts, shown = snap.get("posts") or [], shown
    else:
        posts, _, shown = pick_day(handle, today, queries, pool, shown)
    wrote = {
        "date": today,
        "queries_hash": qhash,
        "posts": posts,
        "shown_urls": shown,
        "summary": stitch_summary(queries, keyword_cache),
    }
    return wrote, wrote


_BRIEF = (
    "You write a 2-4 sentence briefing of what is currently happening in a topic, "
    "using only the social posts below. No intro, no bullets, no URLs, no advice."
)


def summarize_keyword(keyword: str, posts: list[dict]) -> str:
    excerpts = [p.get("excerpt") or "" for p in posts if p.get("excerpt")]
    if not excerpts:
        return ""
    try:
        client = config.get_llm_client()
        resp = client.chat.completions.create(
            model=config.OPENROUTER_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": _BRIEF},
                {
                    "role": "user",
                    "content": f"Topic: {keyword}\n\nPosts:\n" + "\n---\n".join(excerpts[:12]),
                },
            ],
        )
    except Exception:
        return ""
    if not resp.choices:
        return ""
    return (resp.choices[0].message.content or "").strip()


def _extract_tweet(item: dict) -> dict | None:
    tweet_id = str(item.get("id") or item.get("tweetId") or item.get("tweet_id") or "")
    text = item.get("text") or item.get("fullText") or item.get("content") or ""
    author = item.get("author") or item.get("user") or {}
    username = (
        author.get("userName") or author.get("username") or author.get("screen_name") or
        item.get("authorUserName") or item.get("username") or ""
    ).lstrip("@")
    url = item.get("url") or item.get("twitterUrl") or ""
    if not url and tweet_id and username:
        url = f"https://x.com/{username}/status/{tweet_id}"
    if not url or not text:
        return None
    return {
        "url": url,
        "platform": "x",
        "excerpt": text[:500],
        "author": username,
        "posted_at": item.get("createdAt") or item.get("created_at") or "",
    }


def search_x_topic(query: str) -> list[dict]:
    if not query or not config.APIFY_API_KEY:
        return []
    try:
        resp = httpx.post(
            f"{_APIFY_BASE}/acts/{_ACTOR}/run-sync-get-dataset-items",
            params={"token": config.APIFY_API_KEY, "timeout": 90, "memory": 256},
            json={"searchTerms": [query], "maxItems": 12, "queryType": "Latest", "lang": ""},
            timeout=120,
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        return []
    out = []
    for item in resp.json() or []:
        post = _extract_tweet(item)
        if post:
            out.append(post)
    return out


def _other_linkedin_samples(handle: str) -> list[WritingSample]:
    samples = []
    for card in cards_service.list_published():
        if card.handle == handle:
            continue
        samples.extend(card.writing_samples or [])
    return samples


def _load_keyword_cache(sb, keys: list[str]) -> dict:
    if not keys:
        return {}
    resp = sb.table("keyword_posts").select("keyword,fetched_on,posts,summary").in_("keyword", keys).execute()
    cache = {}
    for row in resp.data or []:
        cache[row["keyword"]] = {
            "fetched_on": row.get("fetched_on"),
            "posts": row.get("posts") or [],
            "summary": row.get("summary") or "",
        }
    return cache


def _save_keyword_cache(sb, before: dict, after: dict) -> None:
    for key, entry in after.items():
        if before.get(key) == entry:
            continue
        sb.table("keyword_posts").upsert(
            {
                "keyword": key,
                "fetched_on": entry["fetched_on"],
                "posts": entry["posts"],
                "summary": entry.get("summary") or "",
            },
            on_conflict="keyword",
        ).execute()


def get_suggested_posts(handle: str, today: str | None = None) -> dict | None:
    card = cards_service.get_card_by_handle(handle)
    if not card:
        return None
    day = today or datetime.now(timezone.utc).date().isoformat()
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("suggested_posts")
        .eq("handle", handle)
        .execute()
    )
    snap = (resp.data[0].get("suggested_posts") if resp.data else None)
    keys = [keyword_key(q) for _, q in intent_queries(card) if q]
    cache = _load_keyword_cache(sb, keys)
    before = {k: dict(v) for k, v in cache.items()}
    out, wrote = refresh_snapshot(
        handle,
        card,
        snap,
        day,
        cache,
        search_x_topic,
        _other_linkedin_samples(handle),
        llm=summarize_keyword,
    )
    if wrote:
        sb.table("agent_profile_cards").update({"suggested_posts": wrote}).eq("handle", handle).execute()
        _save_keyword_cache(sb, before, cache)
    return {
        "handle": handle,
        "date": out.get("date"),
        "posts": out.get("posts") or [],
        "summary": out.get("summary"),
    }
