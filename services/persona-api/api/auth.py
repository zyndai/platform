"""
Auth routes — verifies Supabase JWT tokens from the frontend.

The frontend handles the actual login via Supabase Auth JS SDK.
These routes let the backend validate & identify the user on each
request using the Supabase JWT in the Authorization header.

Performance note: ``get_current_user`` is on the hot path for every
authenticated endpoint. The naïve implementation calls
``supabase.auth.get_user(token)`` which round-trips to Supabase Auth
(~100–300ms) on every request — a page with three API calls would
spend a full second just validating the same JWT three times. We
cache decoded users in-process keyed on a hash of the token for 60
seconds, which is well below the JWT's typical 1-hour expiry but
short enough that a logout or role change propagates promptly.
"""

import asyncio
import hashlib
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
import config

router = APIRouter()


# ── JWT validation cache ────────────────────────────────────────────────
# Keyed on sha256(token). The token itself is never stored — defense in
# depth in case a heap dump ever leaks. Bounded size + TTL eviction so
# the cache can't grow unbounded under churn.
_USER_CACHE: dict[str, tuple[float, dict]] = {}
_USER_CACHE_LOCK = asyncio.Lock()
_USER_CACHE_TTL_SECONDS = 60.0
_USER_CACHE_MAX = 1024


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> Optional[dict]:
    now = time.time()
    hit = _USER_CACHE.get(key)
    if not hit:
        return None
    expires_at, user = hit
    if expires_at < now:
        _USER_CACHE.pop(key, None)
        return None
    return user


def _cache_put(key: str, user: dict) -> None:
    _USER_CACHE[key] = (time.time() + _USER_CACHE_TTL_SECONDS, user)
    if len(_USER_CACHE) > _USER_CACHE_MAX:
        # Drop the half-of-cache with the earliest expiries. O(n log n) but
        # only runs at the cap, which is large enough that this is rare.
        items = sorted(_USER_CACHE.items(), key=lambda kv: kv[1][0])
        for k, _ in items[: len(items) // 2]:
            _USER_CACHE.pop(k, None)


async def get_current_user(request: Request) -> dict:
    """
    Dependency — extract and verify user from the Authorization header.
    Returns the user dict from Supabase Auth.

    The first hit per token round-trips to Supabase Auth; subsequent
    hits within 60s use the in-memory cache.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")

    token = auth_header.removeprefix("Bearer ").strip()
    key = _token_key(token)

    cached = _cache_get(key)
    if cached is not None:
        return cached

    sb = config.get_supabase()
    try:
        # Offload the synchronous SDK call so the event loop stays free
        # for other requests while this one waits on Supabase Auth.
        user_response = await asyncio.to_thread(sb.auth.get_user, token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = {
            "id": user_response.user.id,
            "email": user_response.user.email,
            "user_metadata": user_response.user.user_metadata,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Auth error: {str(e)}")

    _cache_put(key, user)
    return user


def invalidate_user_token(token: str) -> None:
    """Drop a token's cache entry on logout / explicit invalidation."""
    _USER_CACHE.pop(_token_key(token), None)


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    """Return the currently logged-in user."""
    return user
