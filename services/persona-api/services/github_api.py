"""
Shared GitHub API access for the read-only GitHub MCP tools.

The OAuth token lifecycle lives in services/github_sync.py (8h user token,
rotating refresh). This module is a thin wrapper that resolves a fresh
token for a user and issues GETs with a consistent (status, payload)
return plus a single 401 → refresh → retry, so individual tools never
re-implement auth.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from services.github_sync import (
    _gh_client,
    _refresh_access_token,
    _token_needs_refresh,
    get_tokens,
)

logger = logging.getLogger(__name__)


async def get_access_token(user_id: str) -> str | None:
    """A usable GitHub access token for the user, refreshing when near
    expiry. None when there's no stored token or refresh fails."""
    if await _token_needs_refresh(user_id):
        if not await _refresh_access_token(user_id):
            return None
    tokens = await asyncio.to_thread(get_tokens, user_id, "github")
    if not tokens:
        return None
    return tokens.get("access_token")


async def api_get(
    user_id: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> tuple[int | None, Any]:
    """GET a GitHub API path with the user's token.

    Returns (status_code, json_payload). status is None when no usable
    token exists or the request failed to connect. On a 401 the token is
    refreshed once and the request retried (covers rotation races
    between the prod/dev backends).
    """
    token = await get_access_token(user_id)
    if not token:
        return None, None

    for attempt in (0, 1):
        try:
            async with _gh_client(token) as client:
                resp = await client.get(path, params=params)
        except Exception as exc:
            logger.warning("[github-api] GET %s failed: %s", path, exc)
            return None, None

        remaining = resp.headers.get("x-ratelimit-remaining", -1)
        if remaining != -1 and int(remaining) < 10:
            logger.warning(
                "[github-api] rate limit nearly exhausted (%s remaining) — aborting", remaining
            )

        if resp.status_code == 401 and attempt == 0:
            if not await _refresh_access_token(user_id):
                return None, None
            fresh = await asyncio.to_thread(get_tokens, user_id, "github") or {}
            token = fresh.get("access_token")
            if not token:
                return None, None
            continue

        try:
            payload = resp.json()
        except Exception:
            payload = None
        return resp.status_code, payload

    return None, None