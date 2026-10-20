"""Signed references to people a search returned, so only they can be invited.

An invitation publishes a Card with a name and headline. Those must come from Memory's own
search result for this user, not from whatever an AI client types, or an agent could create a
public Card about anyone with any claim. find_people therefore attaches an opaque `invite_ref`
to each person who can be invited; invite_to_claim accepts nothing else. The ref is an HMAC
over the person's data, bound to the searching user and short-lived.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.config import settings

TTL_SECONDS = 24 * 3600


def _mac(payload: bytes) -> str:
    return hmac.new(f"invite-ref:{settings.jwt_secret}".encode(), payload, hashlib.sha256).hexdigest()[:32]


def sign(uid: str, *, linkedin_url: str, name: str, headline: str, now: float | None = None) -> str:
    """The ref, or "" when there is no secret to sign with (nothing is then invitable)."""
    if not settings.jwt_secret:
        return ""
    body = json.dumps(
        {"u": str(uid), "l": linkedin_url, "n": name, "h": headline, "x": int((now or time.time()) + TTL_SECONDS)},
        separators=(",", ":"), sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(body).decode().rstrip("=") + "." + _mac(body)


def verify(uid: str, ref: str, now: float | None = None) -> dict | None:
    """{linkedin_url, name, headline} when `ref` was issued to this user and is still valid."""
    if not settings.jwt_secret:
        return None
    try:
        encoded, mac = (ref or "").strip().rsplit(".", 1)
        body = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        if not hmac.compare_digest(mac, _mac(body)):
            return None
        data = json.loads(body)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    if data.get("u") != str(uid) or (now or time.time()) > data.get("x", 0):
        return None
    return {"linkedin_url": data["l"], "name": data["n"], "headline": data.get("h", "")}
