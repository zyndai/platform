"""
Mention polling via X API user mentions (primary) or Apify (fallback).

Poll cycle (every 5 min):
  GET /2/users/:id/mentions  OR  Apify tweet-scraper
  → deduplicate via x_mentions table
  → parse command → dispatch handler
  → reply via free X API write

Profile creation flow:
  1. Detect "@bot create my profile"
  2. Reply asking for GitHub / LinkedIn links (or "skip")
  3. On reply: run pipeline with all provided URLs
  4. Publish card → ask onboarding questions
"""
import asyncio
import logging
import re

import httpx

import config
from x.client import bot_user_id, get_user, get_users_mentions
from x.commands import Command, parse_command, strip_mention
from x import conversation as conv_svc
from x import replies

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 300  # seconds (5 minutes — credits cost per call)
_APIFY_BASE = "https://api.apify.com/v2"
_ACTOR = "apidojo~tweet-scraper"
_BOT_HANDLE = config.X_BOT_HANDLE


# ── Mention fetching: X API user mentions (primary) → Apify search (fallback) ─

async def _fetch_mentions_x_api(bot_id: str, since_id: str | None) -> list[dict] | None:
    """
    GET /2/users/:id/mentions with OAuth 2.0 user auth.
    Returns list of mention dicts on success, None if credits needed or error.
    """
    try:
        mentions = await asyncio.to_thread(get_users_mentions, bot_id, since_id)
        return mentions
    except Exception as exc:
        msg = str(exc)
        if "402" in msg or "credits" in msg.lower():
            logger.warning("X API mentions endpoint requires credits — falling back to Apify")
        else:
            logger.warning("X API mentions failed (%s) — falling back to Apify", exc)
        return None


async def _fetch_mentions_apify() -> list[dict]:
    """Search for @BOT_HANDLE mentions via Apify. Returns normalised mention dicts."""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{_APIFY_BASE}/acts/{_ACTOR}/run-sync-get-dataset-items",
            params={"token": config.APIFY_API_KEY, "timeout": 90, "memory": 256},
            json={
                "searchTerms": [f"@{_BOT_HANDLE}"],
                "maxItems": 50,
                "queryType": "Latest",
                "lang": "",
            },
        )
        resp.raise_for_status()
        raw = resp.json() or []
        mentions = []
        for item in raw:
            m = _extract_mention(item)
            if m:
                mentions.append(m)
        return mentions


def _extract_mention(item: dict) -> dict | None:
    """
    Normalise an Apify tweet-scraper result into a consistent dict.
    Returns None if required fields are missing.
    """
    tweet_id = str(item.get("id") or item.get("tweetId") or item.get("tweet_id") or "")
    text = item.get("text") or item.get("fullText") or item.get("content") or ""
    author = item.get("author") or item.get("user") or {}
    x_user_id = str(
        author.get("id") or author.get("userId") or
        item.get("authorId") or item.get("userId") or ""
    )
    username = (
        author.get("userName") or author.get("username") or author.get("screen_name") or
        item.get("authorUserName") or item.get("username") or ""
    ).lstrip("@")

    # Reply context — is this a reply to one of our bot's tweets?
    in_reply_to_user = str(
        item.get("inReplyToUserId") or item.get("in_reply_to_user_id") or ""
    )

    if not tweet_id or not x_user_id or not username:
        return None

    return {
        "tweet_id": tweet_id,
        "x_user_id": x_user_id,
        "username": username,
        "text": text,
        "in_reply_to_user_id": in_reply_to_user,
    }


# ── X user lookup ────────────────────────────────────────────────────────────

def fetch_x_user(x_user_id: str) -> dict:
    return get_user(x_user_id)


def _extract_urls_from_user(user_data: dict) -> list[str]:
    urls: list[str] = []
    entities = user_data.get("entities") or {}
    for e in (entities.get("url") or {}).get("urls", []) + (entities.get("description") or {}).get("urls", []):
        expanded = e.get("expanded_url") or e.get("url") or ""
        if expanded and not expanded.startswith("https://t.co"):
            urls.append(expanded)
    return list(dict.fromkeys(urls))


# ── pipeline helpers ──────────────────────────────────────────────────────────

async def _run_profile_pipeline(x_url: str, extra_urls: list[str]):
    from api.onboard import _run_pipeline
    from services.jobs import create_job, get_job

    job_id = create_job()
    await _run_pipeline(job_id, [x_url] + extra_urls, resume_text=None)
    job = get_job(job_id)
    if not job or job.status == "error":
        raise RuntimeError(job.error if job else "pipeline failed")
    return job.card, job.scrape_raw, job.handle_github, job.handle_x


async def _publish_card(card, scrape_raw, github_handle, x_handle, answers: dict) -> str:
    from services import cards as cards_service
    from services.jobs import utcnow
    from publish import hooks

    now = utcnow()
    card.status = "published"
    card.updated_at = now
    card.review.status = "human_approved"
    card.review.reviewed_by = "x_bot"
    card.review.reviewed_at = now
    _apply_answers_to_card(card, answers)

    handle = await asyncio.to_thread(
        cards_service.insert_card, card, github_handle, x_handle, scrape_raw, answers or None,
    )
    card.handle = handle
    await hooks.run_publish_hooks(card.id, handle)
    return handle


def _apply_answers_to_card(card, answers: dict) -> None:
    if answers.get("working_on"):
        card.working_on = [a.strip() for a in answers["working_on"].split(",") if a.strip()]
    if answers.get("can_help_with"):
        card.can_help_with = [a.strip() for a in answers["can_help_with"].split(",") if a.strip()]
    if answers.get("connect_with"):
        card.connect_with = [a.strip() for a in answers["connect_with"].split(",") if a.strip()]
    if answers.get("love_talking_about"):
        card.love_talking_about = [a.strip() for a in answers["love_talking_about"].split(",") if a.strip()]
    if answers.get("location") and not card.identity.location:
        card.identity.location = answers["location"]


def _missing_fields(card, answered: dict) -> list[tuple[str, str]]:
    missing = []
    for field, question in conv_svc.ONBOARDING_QUESTIONS:
        if field in answered:
            continue
        val = card.identity.location if field == "location" else getattr(card, field, None)
        if val:
            continue
        missing.append((field, question))
    return missing


# ── URL parsing ───────────────────────────────────────────────────────────────

_URL_RE = re.compile(
    r'(?:https?://)?(?:www\.)?'
    r'(github\.com/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*'
    r'|linkedin\.com/in/[A-Za-z0-9_.-]+)',
    re.IGNORECASE,
)


def _parse_profile_urls(text: str) -> list[str]:
    """Extract GitHub / LinkedIn profile URLs from free text."""
    urls = []
    for m in _URL_RE.finditer(text):
        raw = m.group(0).rstrip(".,)")
        if not raw.startswith("http"):
            raw = "https://" + raw
        urls.append(raw)
    return list(dict.fromkeys(urls))


# ── command handlers ──────────────────────────────────────────────────────────

async def handle_create_profile(tweet_id: str, username: str, x_user_id: str) -> None:
    """Step 1: detect create command → ask for GitHub/LinkedIn links."""
    account = conv_svc.get_account(x_user_id)
    if account and account.get("card_id"):
        from services import cards as cards_service
        card = cards_service.get_card(account["card_id"])
        if card and card.handle:
            replies.reply_already_exists(username, tweet_id, card.handle)
            return

    # Ask user to share extra profile links before running pipeline
    replies.reply_ask_urls(username, tweet_id)

    x_url = f"https://x.com/{username}"
    conv_svc.create_conversation(
        x_user_id,
        card_id=None,
        answered={"__x_url": x_url, "__trigger_tweet_id": tweet_id},
    )
    conv = conv_svc.get_conversation(x_user_id)
    conv_svc.update_conversation(conv["id"], status=conv_svc.ConvStatus.AWAITING_URLS)


async def handle_url_collection(tweet_id: str, username: str, x_user_id: str, text: str) -> None:
    """Step 2: user replied with GitHub/LinkedIn or 'skip' → run pipeline."""
    conv = conv_svc.get_conversation(x_user_id)
    if not conv:
        return

    answered = dict(conv.get("answered") or {})
    x_url = answered.pop("__x_url", f"https://x.com/{username}")
    trigger_tweet = answered.pop("__trigger_tweet_id", tweet_id)

    body = strip_mention(text).strip().lower()
    extra_urls: list[str] = [] if body == "skip" else _parse_profile_urls(strip_mention(text))

    # Also pull any URLs embedded in the user's X bio
    try:
        user_data = fetch_x_user(x_user_id)
        extra_urls = list(dict.fromkeys(extra_urls + _extract_urls_from_user(user_data)))
    except Exception:
        pass

    conv_svc.update_conversation(conv["id"], status=conv_svc.ConvStatus.BUILDING)
    replies.reply_creating(username, trigger_tweet)

    try:
        card, scrape_raw, github_handle, x_handle = await _run_profile_pipeline(x_url, extra_urls)

        missing = _missing_fields(card, answered)
        first_question = missing[0][1] if missing else None

        handle = await _publish_card(card, scrape_raw, github_handle, x_handle, answered)
        conv_svc.upsert_account(x_user_id, username, card.id)

        if missing:
            conv_svc.update_conversation(
                conv["id"],
                card_id=card.id,
                status=conv_svc.ConvStatus.ASKING,
                current_question=missing[0][0],
                answered=answered,
            )
        else:
            conv_svc.update_conversation(conv["id"], card_id=card.id, status=conv_svc.ConvStatus.COMPLETED)

        replies.reply_profile_ready(username, trigger_tweet, handle, first_question)

    except Exception as exc:
        logger.error("url_collection pipeline failed for @%s: %s", username, exc, exc_info=True)
        conv_svc.update_conversation(conv["id"], status=conv_svc.ConvStatus.ERROR)
        replies.reply_error(username, tweet_id)


async def handle_onboarding_answer(tweet_id: str, username: str, x_user_id: str, text: str) -> None:
    """Step 3: user answering profile enrichment questions."""
    conv = conv_svc.get_conversation(x_user_id)
    if not conv:
        replies.reply_help(username, tweet_id)
        return

    # Route AWAITING_URLS replies here too (user might reply late)
    if conv["status"] == conv_svc.ConvStatus.AWAITING_URLS:
        await handle_url_collection(tweet_id, username, x_user_id, text)
        return

    if conv["status"] != conv_svc.ConvStatus.ASKING:
        replies.reply_help(username, tweet_id)
        return

    field = conv.get("current_question")
    if not field:
        return

    answered = conv_svc.apply_answer(conv, field, strip_mention(text))
    conv_svc.update_conversation(conv["id"], answered=answered)

    try:
        from services import cards as cards_service
        from services.jobs import utcnow
        account = conv_svc.get_account(x_user_id)
        card = cards_service.get_card(conv["card_id"])
        if card:
            _apply_answers_to_card(card, answered)
            card.status = "published"
            card.updated_at = utcnow()
            await asyncio.to_thread(
                cards_service.insert_card, card,
                account.get("handle_github") if account else None,
                account.get("handle_x") if account else None,
                None, answered,
            )
    except Exception as exc:
        logger.warning("Card update failed for @%s: %s", username, exc)

    from services import cards as cards_service
    card = cards_service.get_card(conv["card_id"])
    missing = _missing_fields(card, answered) if card else []

    if missing:
        next_field, next_q = missing[0]
        conv_svc.update_conversation(conv["id"], current_question=next_field)
        replies.reply_profile_updated(username, tweet_id, card.handle if card else "", next_q)
    else:
        conv_svc.update_conversation(conv["id"], status=conv_svc.ConvStatus.COMPLETED, current_question=None)
        replies.reply_profile_updated(username, tweet_id, card.handle if card else "", None)


# ── polling loop ─────────────────────────────────────────────────────────────

async def poll_once() -> None:
    try:
        try:
            _bot_id = bot_user_id()
        except Exception:
            _bot_id = ""

        # Try X API user mentions first (free with user auth), fall back to Apify
        mentions: list[dict] | None = await _fetch_mentions_x_api(_bot_id, since_id=None) if _bot_id else None
        if mentions is None:
            logger.info("Using Apify for mention detection")
            mentions = await _fetch_mentions_apify()
        else:
            logger.info("Using X API user mentions, found %d", len(mentions))

        for mention in mentions:
            tweet_id = mention["tweet_id"]
            x_user_id = mention["x_user_id"]
            username = mention["username"]
            text = mention["text"]

            if not tweet_id or not x_user_id:
                continue
            if conv_svc.mention_seen(tweet_id):
                continue

            conv_svc.mark_mention(tweet_id, x_user_id, text)

            is_reply_to_bot = bool(_bot_id and mention["in_reply_to_user_id"] == _bot_id)
            cmd = parse_command(text, is_reply_to_bot=is_reply_to_bot)
            logger.info("mention tweet=%s user=@%s cmd=%s", tweet_id, username, cmd)

            if cmd == Command.CREATE_PROFILE:
                asyncio.create_task(handle_create_profile(tweet_id, username, x_user_id))
            elif cmd == Command.ONBOARDING_ANSWER:
                # Check if user is in AWAITING_URLS state — route to URL collection
                conv = conv_svc.get_conversation(x_user_id)
                if conv and conv.get("status") == conv_svc.ConvStatus.AWAITING_URLS:
                    asyncio.create_task(handle_url_collection(tweet_id, username, x_user_id, text))
                else:
                    asyncio.create_task(handle_onboarding_answer(tweet_id, username, x_user_id, text))
            else:
                replies.reply_help(username, tweet_id)

    except Exception as exc:
        logger.error("poll_once failed: %s", exc, exc_info=True)


async def polling_loop() -> None:
    logger.info("X bot polling loop started (interval=%ds)", _POLL_INTERVAL)
    while True:
        await asyncio.sleep(_POLL_INTERVAL)
        await poll_once()
