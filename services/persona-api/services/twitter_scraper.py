"""
Twitter (X) scraper service — wraps Apify's Tweet Scraper V2, by handle.

Actor: apidojo/tweet-scraper (id 61RPP7dywgiy0JPD0). The user's X handle
is the only input — scraped from the Settings → Accounts "X (Twitter)"
card, stored in the persona profile (profile.twitter), and pushed here.

Raw tweets land in public.twitter_profiles (never in the memory layer).
Only CURATED facts are synced to memory:
  • is_interested_in — up to MAX_FACTS topics the user currently tweets
    about, extracted by the LLM from their latest tweets
  • one LLM-composed first-person summary ingested with
    source_system="twitter" for async extraction
Facts are declared with source_system="twitter" so the memory layer tags
them with provenance (plus its own observed_at timestamp) — same shape
as the linkedin/github syncs.

The scrape is strictly opt-in: nothing runs until the user saves a handle
on the Accounts page. Weekly background refresh via agent/twitter_sync_loop.py;
manual refresh via the card's "Refresh now" button.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone

import httpx

import config

logger = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"
# apidojo/tweet-scraper — Tweet Scraper V2 (profile scraping by handle).
TWITTER_ACTOR = "61RPP7dywgiy0JPD0"

# Per-call timeout for Apify run-sync. Profile scrapes are quick (a few
# seconds to ~30s); 120s gives headroom without dangling requests.
_ACTOR_TIMEOUT = 120.0

# How many of the account's latest tweets to pull per run. 50 satisfies
# the actor's per-query minimum; only the first MAX_EXTRACT_TWEETS are
# shown to the LLM for fact extraction.
MAX_TWEETS = 50
MAX_EXTRACT_TWEETS = 30
MAX_FACTS = 8

TABLE = "twitter_profiles"


def _get_supabase():
    return config.get_supabase()


def normalize_handle(raw: str) -> str | None:
    """Accept "@handle", "handle", or an x.com/twitter.com URL — return
    the bare handle, or None if it doesn't look like one."""
    v = (raw or "").strip().lstrip("@")
    if not v:
        return None
    if re.match(r"^https?://", v, re.IGNORECASE):
        try:
            v = re.sub(r"[/\s]+$", "", v.split("?")[0]).rstrip("/").split("/")[-1]
            v = v.lstrip("@")
        except Exception:
            return None
    v = v.strip()
    if not v or re.search(r"[/\s@]", v) or len(v) > 15:
        return None
    return v


async def _run_actor(payload: dict) -> list:
    """Run the Apify actor synchronously and return its dataset items."""
    if not config.APIFY_API_TOKEN:
        raise RuntimeError("APIFY_API_TOKEN is not configured")

    url = (
        f"{APIFY_BASE}/acts/{TWITTER_ACTOR}/run-sync-get-dataset-items"
        f"?token={config.APIFY_API_TOKEN}"
    )
    async with httpx.AsyncClient(timeout=_ACTOR_TIMEOUT) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code >= 400:
            logger.error(
                "[twitter] actor returned %s: %s", resp.status_code, resp.text[:500]
            )
        resp.raise_for_status()
        return resp.json() or []


def _reject_refused_run(items: list) -> list[dict]:
    """A refused run (Apify plan restriction on the actor, blocked scrape)
    comes back as HTTP 200 with a dataset of {"noResults": true} placeholders
    rather than an error. Treat an all-placeholder dataset as a failure, not
    as "this account has no tweets" — otherwise the placeholders get stored
    and shown to the user as real, successfully-read tweets.
    """
    real = [i for i in items if isinstance(i, dict) and not i.get("noResults")]
    if items and not real:
        raise RuntimeError(
            "Apify returned no usable tweets — the actor run was refused. "
            "Most often this is an Apify plan restriction on "
            f"{TWITTER_ACTOR}; check the run log at "
            "https://console.apify.com/actors/runs for the exact reason."
        )
    return real


async def scrape_tweets(handle: str) -> list[dict]:
    """Fetch the account's latest tweets (newest first) by handle."""
    items = await _run_actor(
        {
            "twitterHandles": [handle],
            "maxItems": MAX_TWEETS,
            "sort": "Latest",
        }
    )
    return _reject_refused_run(items)


def _select_tweets(items: list[dict], handle: str) -> list[dict]:
    """Keep only the account's own tweets, in newest-first order. Original
    tweets are always preferred — retweets only enter when the account
    posts no originals at all (a pure-retweet account still signals what
    it engages with, which beats no signal)."""
    handle_l = (handle or "").lower()
    own = [
        t for t in items
        if (t.get("author") or {}).get("userName", "").lower() == handle_l
    ]
    originals = [t for t in own if not t.get("isRetweet")]
    if originals:
        return originals[:MAX_EXTRACT_TWEETS]
    if own:
        return own[:MAX_EXTRACT_TWEETS]
    # Author info missing/odd — fall back to everything the actor gave us.
    return items[:MAX_EXTRACT_TWEETS]


def _tweet_text(item: dict) -> str:
    """Trimmed tweet text for the extractor — multiline collapsed."""
    return " ".join(str(item.get("text") or "").split())


def _parse_facts_json(raw: str) -> list[str]:
    """Parse the LLM's JSON answer into a clean list of interest strings.

    The provider returns markdown-wrapped JSON about as often as bare JSON,
    so strip code fences and tolerate trailing prose. Anything unparseable
    yields no facts (never raises — the scrape must not fail on this).
    """
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    candidates = [text]
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        candidates.insert(0, m.group(0))
    for cand in candidates:
        try:
            data = json.loads(cand)
            values = data.get("interests") or data.get("facts") or []
            if isinstance(values, list):
                facts = []
                for v in values:
                    s = " ".join(str(v).split()).strip(" -•*")
                    if s and s not in facts and len(s) <= 120:
                        facts.append(s)
                return facts[:MAX_FACTS]
        except (json.JSONDecodeError, AttributeError):
            continue
    return []


async def _extract_interest_facts(handle: str, tweets: list[dict]) -> list[str]:
    """LLM-extract the topics the user is currently engaged in/tweeting
    about. Returns a short list of interest strings (max MAX_FACTS), or an
    empty list when the LLM is unreachable or returns junk — extraction is
    a bonus, never a dependency of the scrape."""
    if not tweets:
        return []

    numbered = "\n".join(
        f"{i + 1}. {_tweet_text(t)}" for i, t in enumerate(tweets)
    )
    prompt = (
        "You are analyzing a person's recent tweets to learn what they are "
        "interested in and currently engaged with. Return ONLY a JSON object "
        'of the form {"interests": ["...", "..."]} — 3 to 8 short noun '
        "phrases (e.g. \"open-source LLM tooling\", \"climate investing\"). "
        "Only infer from what the tweets actually show. No markdown, no "
        "commentary, no sentences longer than a few words.\n\n"
        f"Twitter handle: @{handle}\n\nTweets (newest first):\n{numbered}"
    )
    try:
        from agent.orchestrator import _get_provider

        provider = _get_provider()
        text, _ = await asyncio.to_thread(
            provider.chat_with_tools,
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "List their interests."},
            ],
            [],
        )
        return _parse_facts_json(text or "")
    except Exception as exc:
        logger.warning("[twitter] %s: interest extraction LLM call failed: %s", handle, exc)
        return []


async def _compose_summary(handle: str, facts: list[str], tweets: list[dict]) -> str:
    """LLM-composed first-person memory note about the tweets.

    Falls back to a plain template when the LLM is unreachable — the
    summary is a bonus, never a dependency of the scrape.
    """
    if facts:
        prompt = (
            "Write a private memory note about a person's Twitter (X) "
            "activity, in their own first-person voice. Use only the facts "
            "given. 3-5 short declarative sentences. Lead with what they are "
            "currently engaged with, then the topics they tweet about. "
            "No fluff, no markdown, no bullet lists.\n\n"
            f"Currently engaged with / interested in: {', '.join(facts)}"
        )
        try:
            from agent.orchestrator import _get_provider

            provider = _get_provider()
            text, _ = await asyncio.to_thread(
                provider.chat_with_tools,
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Write the note."},
                ],
                [],
            )
            if text and text.strip():
                return text.strip()
        except Exception as exc:
            logger.warning("[twitter] %s: summary LLM call failed: %s", handle, exc)

    if not facts:
        return ""
    return f"I tweet about: {', '.join(facts)}."


async def sync_to_memory(user_id: str, handle: str, facts: list[str]) -> dict:
    """Write the IMPORTANT Twitter facts to the memory layer, deduped.

      • is_interested_in — each extracted topic, declared with
        source_system="twitter" (provenance tag in the memory layer)
    Plus one LLM-composed first-person summary ingested with
    source_system="twitter" for async extraction — only when at least one
    new fact was declared, so an unchanged re-scrape writes nothing.

    Diffed against the user's current assertion graph (list_assertions)
    so only new (predicate, object) pairs are declared. Fire-and-forget:
    memory-layer problems are logged and never block the scrape.
    """
    from agent.memory_client import (
        declare_fact,
        ingest_turns,
        is_enabled,
        list_assertions,
    )

    if not is_enabled():
        return {"facts_declared": 0}
    if not facts:
        return {"facts_declared": 0}

    try:
        existing = await list_assertions(user_id)
        seen = {(a.predicate, (a.object or "").strip().lower()) for a in existing}
        new_facts = [
            f for f in facts if ("is_interested_in", f.strip().lower()) not in seen
        ]
    except Exception as exc:
        logger.warning("[twitter] memory graph read failed for %s: %s", user_id, exc)
        return {"facts_declared": 0}

    declared = 0
    for fact in new_facts:
        try:
            if await declare_fact(user_id, "is_interested_in", fact, source_system="twitter"):
                declared += 1
        except Exception as exc:
            logger.warning(
                "[twitter] declare_fact(is_interested_in, %r) failed for %s: %s",
                fact, user_id, exc,
            )

    if declared:
        summary = await _compose_summary(handle, facts, [])
        if summary:
            try:
                await ingest_turns(
                    user_id,
                    turns=[{"role": "user", "content": summary}],
                    source_system="twitter",
                )
            except Exception as exc:
                logger.warning("[twitter] summary ingest failed for %s: %s", user_id, exc)

    logger.info(
        "[twitter] memory sync for %s: %d new facts declared (of %d extracted)",
        user_id, declared, len(facts),
    )
    return {"facts_declared": declared}


async def scrape_user(user_id: str, handle: str) -> dict:
    """End-to-end scrape of a known X handle: fetch latest tweets, persist
    to twitter_profiles, and sync curated interest facts to the memory
    layer (deduped). Idempotent — calling twice upserts.

    The handle is mandatory. Nothing runs until the user saves one on the
    Accounts page.
    """
    if not handle:
        return {"status": "skipped", "reason": "no_handle"}

    logger.info("[twitter] starting scrape for %s (@%s)", user_id, handle)

    try:
        items = await scrape_tweets(handle)
    except Exception as exc:
        # Actor call itself failed (network, Apify billing/rate limit) —
        # distinct from "ran fine and found nothing". Abort without
        # touching the DB so the next call retries cleanly.
        logger.warning("[twitter] scrape failed for %s: %s", user_id, exc)
        return {"status": "error", "stage": "tweets", "detail": str(exc)}

    tweets = _select_tweets(items, handle)

    sb = _get_supabase()

    # Don't overwrite existing good data with an empty scrape.
    if not items or not tweets:
        existing = (
            sb.table(TABLE)
            .select("raw_tweets")
            .eq("user_id", user_id)
            .execute()
        )
        if existing.data and existing.data[0].get("raw_tweets"):
            logger.warning(
                "[twitter] skipping upsert for %s — new scrape returned empty, "
                "and existing data is still good (@%s)",
                user_id, handle,
            )
            return {"status": "skipped", "reason": "empty_scrape_preserved_existing"}

    facts = await _extract_interest_facts(handle, tweets)

    sb.table(TABLE).upsert(
        {
            "user_id": user_id,
            "handle": handle,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "raw_tweets": items[:MAX_TWEETS],
            "facts": facts,
        },
        on_conflict="user_id",
    ).execute()

    logger.info(
        "[twitter] stored %d tweets (%d used for extraction) for %s (@%s)",
        len(items), len(tweets), user_id, handle,
    )
    memory = await _safe_memory_sync(user_id, handle, facts)
    return {"status": "ok", "handle": handle, "tweets_count": len(items), **memory}


async def _safe_memory_sync(user_id: str, handle: str, facts: list[str]) -> dict:
    """Wrapper — a memory-sync failure must never fail the scrape that
    triggered it. sync_to_memory already catches most errors; this is the
    last line of defense."""
    try:
        return await sync_to_memory(user_id, handle, facts)
    except Exception as exc:
        logger.warning("[twitter] memory sync failed for %s: %s", user_id, exc)
        return {"facts_declared": 0}
