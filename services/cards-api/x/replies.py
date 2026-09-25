"""Compose and send X replies via OAuth 2.0 user context."""
import logging

import config
from x.client import create_tweet

logger = logging.getLogger(__name__)

_SITE = config.SITE_BASE_URL


def _post(text: str, reply_to_id: str) -> str | None:
    try:
        data = create_tweet(text[:280], reply_to_id)
        return str(data.get("id", "")) or None
    except Exception as exc:
        logger.error("Failed to post reply to %s: %s", reply_to_id, exc)
        return None


def reply_help(username: str, tweet_id: str) -> str | None:
    text = (
        f"@{username} Hey! 👋 I'm Zynd — I turn your public profiles into a discoverable card.\n\n"
        f"Try: @ZyndAI create my profile\n\n"
        f"I'll pull your GitHub, bio, posts, and build your card at {_SITE}/p/you"
    )
    return _post(text, tweet_id)


def reply_ask_urls(username: str, tweet_id: str) -> str | None:
    text = (
        f"@{username} Got it! Reply with your GitHub and/or LinkedIn links for a richer profile "
        f"(e.g. github.com/you linkedin.com/in/you). Or reply \"skip\" to use X only."
    )
    return _post(text, tweet_id)


def reply_creating(username: str, tweet_id: str) -> str | None:
    text = (
        f"@{username} On it! Pulling your public profiles and building your Zynd card 🔍\n\n"
        f"I'll reply with your profile URL in a moment."
    )
    return _post(text, tweet_id)


def reply_profile_ready(username: str, tweet_id: str, handle: str, first_question: str | None) -> str | None:
    url = f"{_SITE}/p/{handle}"
    if first_question:
        text = (
            f"@{username} Your Zynd profile is live 🎉\n{url}\n\n"
            f"One quick question to make it better:\n{first_question}"
        )
    else:
        text = f"@{username} Your Zynd profile is live 🎉\n{url}"
    return _post(text, tweet_id)


def reply_already_exists(username: str, tweet_id: str, handle: str) -> str | None:
    url = f"{_SITE}/p/{handle}"
    text = (
        f"@{username} You already have a Zynd profile 👀\n{url}\n\n"
        f"Reply \"update my profile\" and I'll refresh it."
    )
    return _post(text, tweet_id)


def reply_question(username: str, tweet_id: str, question: str) -> str | None:
    return _post(f"@{username} {question}", tweet_id)


def reply_error(username: str, tweet_id: str) -> str | None:
    text = (
        f"@{username} Sorry, something went wrong on my end. "
        f"Try again in a moment, or visit {_SITE} directly."
    )
    return _post(text, tweet_id)


def reply_profile_updated(username: str, tweet_id: str, handle: str, next_question: str | None) -> str | None:
    url = f"{_SITE}/p/{handle}"
    if next_question:
        text = f"@{username} Got it, profile updated ✓\n\n{next_question}"
    else:
        text = f"@{username} Profile complete! 🎉\n{url}"
    return _post(text, tweet_id)
