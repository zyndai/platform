"""
Matches API — surfaces the three-people-you'd-want-to-meet onboarding
hero (S6) and any other "show me a curated handful" surface.

v1 logic (no LLM yet):
  - Query persona_agents for active rows other than the caller's.
  - Drop anyone the caller is already connected with.
  - Score by interest overlap (capabilities ∪ profile.interests).
  - Take top N, enrich each with a LinkedIn headline + a recent-post
    excerpt + a one-liner "why I picked them" reason.
"""

import logging
from typing import Optional

from fastapi import APIRouter
from supabase import create_client

import config

logger = logging.getLogger(__name__)
router = APIRouter()


def _sb():
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def _interests(persona: dict) -> set[str]:
    """Pull the union of capabilities + profile.interests, lower-cased."""
    caps = persona.get("capabilities") or []
    profile = persona.get("profile") or {}
    raw = profile.get("interests")
    if isinstance(raw, str):
        ints = [s.strip() for s in raw.split(",") if s.strip()]
    elif isinstance(raw, list):
        ints = [str(s).strip() for s in raw if s]
    else:
        ints = []
    return {x.lower() for x in (list(caps) + ints) if x}


def _short(s: str | None, n: int) -> str:
    if not s:
        return ""
    s = s.strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _build_reason(candidate: dict, my_interests: set[str]) -> str:
    """One-line 'why I picked them'. Prefers an interest-overlap framing
    when there's overlap, otherwise falls back to a short description."""
    their = _interests(candidate)
    overlap = sorted(my_interests & their)[:2]
    if overlap:
        return f"Working on {', '.join(overlap)} — close to what you're focused on."
    desc = (candidate.get("description") or "").strip()
    first = desc.split(".")[0].strip() if desc else ""
    return _short(first or desc or "Active on the network.", 160)


@router.get("/{user_id}")
async def get_matches(user_id: str, exclude: Optional[str] = None, limit: int = 3):
    """Return up to `limit` personas the user might want to meet.

    `exclude` is an optional comma-separated list of agent_ids to skip
    (used by the S6 "Show me more" reroll)."""
    sb = _sb()
    excluded = {x for x in (exclude or "").split(",") if x}

    me_q = (
        sb.table("persona_agents")
        .select("*")
        .eq("user_id", user_id)
        .eq("active", True)
        .execute()
    )
    if not me_q.data:
        return {"matches": []}
    me = me_q.data[0]
    excluded.add(me["agent_id"])

    # Drop anyone we're already in a thread with.
    threads = (
        sb.table("dm_threads")
        .select("initiator_id,receiver_id")
        .or_(f"initiator_id.eq.{me['agent_id']},receiver_id.eq.{me['agent_id']}")
        .execute()
    )
    for t in threads.data or []:
        if t["initiator_id"] != me["agent_id"]:
            excluded.add(t["initiator_id"])
        if t["receiver_id"] != me["agent_id"]:
            excluded.add(t["receiver_id"])

    candidates = (
        sb.table("persona_agents")
        .select("*")
        .eq("active", True)
        .neq("user_id", user_id)
        .execute()
        .data
        or []
    )
    candidates = [c for c in candidates if c["agent_id"] not in excluded]

    my_interests = _interests(me)
    candidates.sort(
        key=lambda c: len(my_interests & _interests(c)),
        reverse=True,
    )

    out = []
    for c in candidates[:limit]:
        # Look up enrichment data — LinkedIn headline + a recent post.
        linkedin_q = (
            sb.table("linkedin_profiles")
            .select("raw_profile,raw_posts")
            .eq("user_id", c["user_id"])
            .execute()
        )
        headline = ""
        recent_post = None
        if linkedin_q.data:
            row = linkedin_q.data[0]
            raw_profile = row.get("raw_profile") or {}
            headline = raw_profile.get("headline") or raw_profile.get("summary") or ""
            posts = row.get("raw_posts") or []
            if posts and isinstance(posts[0], dict):
                first = posts[0]
                recent_post = first.get("text") or first.get("content") or first.get("summary")

        # Headline fallback: first sentence of description.
        if not headline:
            desc = (c.get("description") or "").strip()
            headline = desc.split(".")[0].strip() if desc else ""

        out.append({
            "agent_id":    c["agent_id"],
            "name":        c.get("name") or "Someone",
            "description": c.get("description") or "",
            "headline":    _short(headline, 80),
            "recent_post": _short(recent_post, 240) if recent_post else None,
            "reason":      _build_reason(c, my_interests),
        })

    return {"matches": out}
