"""A5 — connection brief: what each person is up to now, what they share, what to talk about.

Shown for an ACCEPTED connection only, from what both people approved onto their public Cards:
current facts (not expired, so "working on" means now), shared skills / industries / place, and a
few concrete things to bring up. Pure: no I/O beyond the cards passed in.
"""
from __future__ import annotations

from datetime import datetime, timezone

from models.card import AgentProfileCard
from services.card_view import fact_object, fact_predicate, live_facts
from services.search_text import location_tokens, query_terms

NOW_PREDICATES = ("is_building", "is_working_on", "is_seeking", "open_to")
_SEEKING = {
    "co_founder": "a co-founder", "technical_feedback": "technical feedback", "early_users": "early users",
    "mentoring": "mentoring", "being_mentored": "a mentor", "peer_review": "peer reviews",
    "collaboration": "collaborators", "investment": "investment", "community": "community",
    "coffee_chat": "coffee chats", "mentoring_others": "people to mentor", "early_user_testing": "early user testing",
}
MAX_ITEMS = 5


def _label(predicate: str, obj: str) -> str:
    obj = _SEEKING.get(obj.strip().lower(), obj.strip())
    return {"is_building": f"Building {obj}", "is_working_on": f"Working on {obj}",
            "is_seeking": f"Looking for {obj}", "open_to": f"Open to {obj}"}.get(predicate, obj)


def current(card: AgentProfileCard, now: datetime | None = None) -> list[dict]:
    """What this person says they are doing now: live approved facts, newest first, then the
    stored "working on" list for whatever the facts do not cover."""
    now = now or datetime.now(timezone.utc)
    from services.card_view import _parse_ts

    facts = [f for f in live_facts(card.zynd_memory, now) if fact_predicate(f) in NOW_PREDICATES]
    facts.sort(key=lambda f: _parse_ts(f.get("approved_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    out, seen = [], set()
    for f in facts:
        text = _label(fact_predicate(f), fact_object(f))
        if text.lower() not in seen:
            seen.add(text.lower())
            out.append({"text": text, "object": fact_object(f), "predicate": fact_predicate(f), "source": "approved_fact"})
    for item in card.working_on or []:
        if item.strip() and f"working on {item}".lower() not in seen and item.lower() not in seen:
            out.append({"text": f"Working on {item.strip()}", "object": item.strip(), "predicate": "is_working_on", "source": "card"})
    return out[:MAX_ITEMS]


def _overlap(a: list[str], b: list[str]) -> list[str]:
    theirs = {x.strip().lower(): x.strip() for x in b if x and x.strip()}
    return [theirs[x.strip().lower()] for x in a if x and x.strip().lower() in theirs]


def shared_ground(me: AgentProfileCard, them: AgentProfileCard) -> dict:
    skills = _overlap([s.name for s in me.skills], [s.name for s in them.skills])
    industries = _overlap(me.industries, them.industries)
    interests = _overlap(me.love_talking_about, them.love_talking_about)
    place = ""
    if location_tokens(me.identity.location) & location_tokens(them.identity.location):
        place = them.identity.location
    return {"skills": skills[:MAX_ITEMS], "industries": industries[:3], "interests": interests[:3], "location": place}


def suggested_topics(me: AgentProfileCard, them: AgentProfileCard, shared: dict, their_now: list[dict]) -> list[str]:
    topics: list[str] = []
    for kind in ("skills", "interests", "industries"):
        for item in shared[kind][:2]:
            topics.append(f"You both care about {item}")
    if shared["location"]:
        topics.append(f"You are both in {shared['location']}")
    mine = {s.name.strip().lower() for s in me.skills} | {e.strip().lower() for e in me.can_help_with}
    for fact in their_now:
        text = fact["text"]
        if fact["predicate"] == "is_seeking":
            wanted = text.removeprefix("Looking for ").lower()
            helpers = [m for m in mine if m and (m in wanted or any(w in mine for w in query_terms(wanted)))]
            topics.append(f"{text}: " + ("you may be able to help" if helpers else "ask how it is going"))
        elif fact["predicate"] in ("is_building", "is_working_on"):
            topics.append(f"Ask about: {fact.get('object') or text}")
    seen, out = set(), []
    for t in topics:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:MAX_ITEMS]


def build_brief(me: AgentProfileCard, them: AgentProfileCard, now: datetime | None = None) -> dict:
    mine, theirs = current(me, now), current(them, now)
    shared = shared_ground(me, them)
    return {
        "partner": {"handle": them.handle, "name": them.identity.name, "headline": them.identity.headline},
        "now": {"you": mine, "them": theirs},
        "shared": shared,
        "suggested_topics": suggested_topics(me, them, shared, theirs),
    }
