"""Recommend published ZYND cards with overlapping profile interests."""
from __future__ import annotations

import config
from models.card import AgentProfileCard
from services import cards as cards_service

FIELDS = ("working_on", "can_help_with", "connect_with", "love_talking_about")

KEYWORDS = {
    "working_on": [
        "Building a startup", "Building with AI", "Open source", "Side project",
        "Indie hacking", "B2B SaaS", "Consumer apps", "Deep tech / research",
        "Freelancing", "At a company", "Doing research", "Grad school",
        "Writing", "Teaching / mentoring", "Community building",
        "Design / creative work", "Investing", "Job hunting",
    ],
    "can_help_with": [
        "Code review", "System design", "ML / AI", "Cloud / infra",
        "Data / analytics", "Security", "Technical interviews", "Hiring",
        "Career advice", "Fundraising", "Pitching / storytelling", "Sales",
        "Marketing", "Go-to-market", "Design", "Legal / compliance",
        "Immigration / visas", "Public speaking",
    ],
    "connect_with": [
        "Founders", "Investors", "Engineers", "ML Researchers",
        "Product Managers", "Designers", "Operators", "Scientists",
        "Recruiters", "Mentors", "Potential co-founders", "Customers",
        "Students", "Writers", "DevRel", "Researchers in my field",
        "Healthcare builders", "Robotics people",
    ],
    "love_talking_about": [
        "AI / ML", "Agentic AI", "Startups", "Developer tools", "Open source",
        "Web3 / Crypto", "Climate tech", "Robotics", "Hardware", "Design",
        "Research", "SaaS", "Engineering culture", "Books", "Philosophy",
        "Personal finance", "Gaming", "History / science",
    ],
}

_ALIASES = {
    "working_on": {
        "developing ai agents": "Building with AI",
        "building decentralized ai agents": "Building with AI",
        "building ai agents": "Building with AI",
        "mobile app development": "Consumer apps",
    },
    "can_help_with": {
        "ml ai": "ML / AI",
        "cloud architecture": "Cloud / infra",
        "cloud infrastructure": "Cloud / infra",
        "backend development": "System design",
    },
    "connect_with": {
        "ai enthusiasts": "ML Researchers",
        "software engineers": "Engineers",
        "ai researchers": "ML Researchers",
        "other developers": "Engineers",
        "other web3 developers": "Engineers",
        "founders and entrepreneurs": "Founders",
        "potential cofounders": "Potential co-founders",
        "co-founders": "Potential co-founders",
    },
    "love_talking_about": {
        "ai technology": "AI / ML",
        "ai technologies": "AI / ML",
        "blockchain enthusiasts": "Web3 / Crypto",
        "blockchain technology": "Web3 / Crypto",
        "web3 technologies": "Web3 / Crypto",
        "open-source projects": "Open source",
        "open-source contributors": "Open source",
    },
}

_CANON = {
    field: {label.casefold(): label for label in labels}
    for field, labels in KEYWORDS.items()
}


def canonical_keyword(field: str, value: str) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().casefold().split())
    return _CANON.get(field, {}).get(normalized) or _ALIASES.get(field, {}).get(normalized)


def _card_interests(card: AgentProfileCard) -> dict[str, set[str]]:
    return {
        field: {
            canonical
            for value in (getattr(card, field) or [])
            if (canonical := canonical_keyword(field, value))
        }
        for field in FIELDS
    }


def _public_person(card: AgentProfileCard, handle: str, matched: dict[str, list[str]]) -> dict:
    return {
        "handle": handle,
        "name": card.identity.name,
        "headline": card.identity.headline,
        "location": card.identity.location,
        "avatar_url": card.identity.avatar_url,
        "url": f"{config.SITE_BASE_URL.rstrip('/')}/p/{handle}",
        "match_score": sum(map(len, matched.values())),
        "matched_fields": matched,
    }


def get_suggested_people(handle: str) -> dict | None:
    requester = cards_service.get_card_by_handle(handle)
    if not requester:
        return None
    interests = _card_interests(requester)
    if not any(interests.values()):
        return {"handle": handle, "people": []}

    results = []
    for row in cards_service.list_published_rows(columns="card,handle"):
        candidate_handle = row.get("handle")
        if not candidate_handle or candidate_handle == handle:
            continue
        try:
            candidate = AgentProfileCard.model_validate(row.get("card") or {})
        except Exception:
            continue
        candidate_interests = _card_interests(candidate)
        matched = {
            field: sorted(interests[field] & candidate_interests[field], key=str.casefold)
            for field in FIELDS
        }
        matched = {field: words for field, words in matched.items() if words}
        if matched:
            candidate.handle = candidate_handle
            results.append(_public_person(candidate, candidate_handle, matched))

    results.sort(key=lambda person: (-person["match_score"], person["handle"].casefold()))
    return {"handle": handle, "people": results[:2]}
