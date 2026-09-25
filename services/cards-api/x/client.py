"""
X API client — OAuth 2.0 user context via direct httpx calls.

X Developer Console (2026) issues OAuth 2.0 tokens:
- User Access Token  → POST /2/tweets (create replies), GET /2/users/:id/mentions
- App Bearer Token   → fallback for app-only endpoints (not needed for writes)
- Refresh Token      → renew user access token (requires matching client_id)

Tweepy is kept for backward compatibility on read operations only.
All writes go through httpx with `Authorization: Bearer <user_access_token>`.
"""
import logging
import threading
from datetime import datetime, timedelta, timezone

import httpx
import tweepy

import config

logger = logging.getLogger(__name__)

_BASE = "https://api.twitter.com/2"
_lock = threading.Lock()
_token_expiry: datetime | None = None
_current_access_token: str = ""


def _refresh_user_token() -> str:
    """Exchange refresh token for a new access token via X OAuth 2.0."""
    if not config.X_USER_REFRESH_TOKEN or not config.X_CLIENT_ID:
        raise RuntimeError("X_USER_REFRESH_TOKEN or X_CLIENT_ID not set")

    resp = httpx.post(
        "https://api.x.com/2/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": config.X_USER_REFRESH_TOKEN,
            "client_id": config.X_CLIENT_ID,
        },
        auth=(config.X_CLIENT_ID, config.X_CLIENT_SECRET) if config.X_CLIENT_SECRET else None,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    logger.info("X OAuth 2.0 token refreshed")
    if new_refresh := data.get("refresh_token"):
        config.X_USER_REFRESH_TOKEN = new_refresh
    return data["access_token"]


def _get_user_access_token() -> str:
    """Return a valid OAuth 2.0 user access token, refreshing if needed."""
    global _current_access_token, _token_expiry

    with _lock:
        now = datetime.now(timezone.utc)
        needs_refresh = (
            not _current_access_token or
            (_token_expiry is not None and now >= _token_expiry - timedelta(minutes=5))
        )

        if needs_refresh and config.X_USER_REFRESH_TOKEN:
            try:
                _current_access_token = _refresh_user_token()
                # X OAuth 2.0 user access tokens expire in 2 hours
                _token_expiry = now + timedelta(hours=2)
            except Exception as exc:
                logger.warning("Token refresh failed, using existing token: %s", exc)

        if not _current_access_token:
            _current_access_token = config.X_USER_ACCESS_TOKEN

    return _current_access_token


def _headers() -> dict[str, str]:
    """HTTP headers for OAuth 2.0 user context requests."""
    return {
        "Authorization": f"Bearer {_get_user_access_token()}",
        "Content-Type": "application/json",
    }


def get_me() -> dict:
    """Return the bot user's own profile."""
    resp = httpx.get(f"{_BASE}/users/me", headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json().get("data", {})


def bot_user_id() -> str:
    """Return the bot account's X user ID."""
    data = get_me()
    uid = data.get("id", "")
    if not uid:
        raise RuntimeError("Cannot resolve bot X user ID — check credentials")
    return str(uid)


def create_tweet(text: str, reply_to_id: str) -> dict:
    """Post a reply tweet. Returns the created tweet data dict."""
    payload = {"text": text, "reply": {"in_reply_to_tweet_id": reply_to_id}}
    resp = httpx.post(f"{_BASE}/tweets", headers=_headers(), json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json().get("data", {})


def get_user(user_id: str) -> dict:
    """Return a user's public profile fields."""
    params = {
        "user.fields": "name,username,description,location,url,entities,profile_image_url",
    }
    resp = httpx.get(f"{_BASE}/users/{user_id}", headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("data", {})


def get_users_mentions(bot_id: str, since_id: str | None = None, max_results: int = 20) -> list[dict]:
    """Return recent mentions of the bot user."""
    params: dict = {
        "max_results": min(max(5, max_results), 100),
        "expansions": "author_id",
        "tweet.fields": "text,author_id,in_reply_to_user_id",
        "user.fields": "username",
    }
    if since_id:
        params["since_id"] = since_id
    resp = httpx.get(
        f"{_BASE}/users/{bot_id}/mentions",
        headers=_headers(),
        params=params,
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    tweets = body.get("data") or []
    users = {u["id"]: u.get("username", "") for u in (body.get("includes") or {}).get("users", [])}
    return [
        {
            "tweet_id": str(t["id"]),
            "x_user_id": str(t.get("author_id", "")),
            "username": users.get(t.get("author_id", ""), ""),
            "text": t.get("text", ""),
            "in_reply_to_user_id": str(t.get("in_reply_to_user_id") or ""),
        }
        for t in tweets
    ]


# ── Legacy tweepy read client (kept for any future read-only calls) ──────────

def get_read_client() -> tweepy.Client:
    return tweepy.Client(bearer_token=config.X_BEARER_TOKEN, wait_on_rate_limit=True)
