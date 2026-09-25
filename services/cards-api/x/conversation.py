"""
Supabase-backed conversation state for X onboarding.

Tables required (see db/x_bot_schema.sql):
  x_mentions      — idempotency; one row per processed tweet ID
  x_accounts      — maps x_user_id → zynd card id
  x_conversations — per-user onboarding state machine
"""
import logging
from enum import Enum

import config

logger = logging.getLogger(__name__)

ONBOARDING_QUESTIONS = [
    ("working_on",         "What are you currently working on? (brief answer is fine)"),
    ("can_help_with",      "What can you help other people with?"),
    ("love_talking_about", "What do you love talking about?"),
    ("connect_with",       "Who would you like to connect with on Zynd?"),
    ("location",           "Where are you currently based?"),
]


class ConvStatus(str, Enum):
    INITIAL = "initial"
    AWAITING_URLS = "awaiting_urls"  # waiting for user to share GitHub/LinkedIn
    BUILDING = "building"            # pipeline running
    ASKING = "asking"
    PROFILE_READY = "profile_ready"
    COMPLETED = "completed"
    ERROR = "error"


def _sb():
    return config.get_supabase()


# ── idempotency ──────────────────────────────────────────────────────────────

def mention_seen(tweet_id: str) -> bool:
    resp = _sb().table("x_mentions").select("tweet_id").eq("tweet_id", tweet_id).execute()
    return bool(resp.data)


def mark_mention(tweet_id: str, x_user_id: str, text: str, status: str = "processed") -> None:
    _sb().table("x_mentions").upsert(
        {"tweet_id": tweet_id, "x_user_id": x_user_id, "text": text[:500], "status": status},
        on_conflict="tweet_id",
    ).execute()


# ── x_accounts ───────────────────────────────────────────────────────────────

def get_account(x_user_id: str) -> dict | None:
    resp = _sb().table("x_accounts").select("*").eq("x_user_id", x_user_id).execute()
    return resp.data[0] if resp.data else None


def upsert_account(x_user_id: str, username: str, card_id: str | None = None) -> None:
    row: dict = {"x_user_id": x_user_id, "username": username}
    if card_id:
        row["card_id"] = card_id
    _sb().table("x_accounts").upsert(row, on_conflict="x_user_id").execute()


# ── x_conversations ───────────────────────────────────────────────────────────

def get_conversation(x_user_id: str) -> dict | None:
    resp = (
        _sb().table("x_conversations")
        .select("*")
        .eq("x_user_id", x_user_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def create_conversation(x_user_id: str, card_id: str | None = None, answered: dict | None = None) -> dict:
    row = {
        "x_user_id": x_user_id,
        "card_id": card_id,
        "status": ConvStatus.INITIAL,
        "current_question": None,
        "answered": answered or {},
    }
    resp = _sb().table("x_conversations").insert(row).execute()
    return resp.data[0]


def update_conversation(conv_id: str, **kwargs) -> None:
    _sb().table("x_conversations").update(kwargs).eq("id", conv_id).execute()


def next_question(answered: dict) -> tuple[str, str] | None:
    """Return (field_name, question_text) for the next unanswered onboarding question, or None."""
    for field, question in ONBOARDING_QUESTIONS:
        if field not in answered:
            return field, question
    return None


def apply_answer(conv: dict, field: str, answer_text: str) -> dict:
    """Merge a user answer into conv['answered'] and return the updated dict."""
    answered = dict(conv.get("answered") or {})
    answered[field] = answer_text.strip()
    return answered
