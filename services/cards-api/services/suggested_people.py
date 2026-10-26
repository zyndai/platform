"""The card vocabulary suggestions read (KEYWORDS, canonical_keyword) and the outside (LinkedIn)
step of suggestions. Who to suggest is decided in services/suggestions.py."""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

import config
from models.card import AgentProfileCard

logger = logging.getLogger(__name__)

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


_TITLE_FOR = {
    "Founders": "Founder",
    "Investors": "Investor",
    "Engineers": "Software Engineer",
    "ML Researchers": "Machine Learning Engineer",
    "Product Managers": "Product Manager",
    "Designers": "Designer",
    "Operators": "COO",
    "Scientists": "Scientist",
    "Recruiters": "Recruiter",
    "Mentors": "Mentor",
    "Potential co-founders": "Co-Founder",
    "Students": "Student",
    "Writers": "Writer",
    "DevRel": "Developer Advocate",
    "Researchers in my field": "Researcher",
    "Healthcare builders": "Healthcare",
    "Robotics people": "Robotics Engineer",
}

_KEYWORD_FOR = {
    "Building with AI": "AI",
    "Building a startup": "startup",
    "Open source": "open source",
    "B2B SaaS": "SaaS",
    "Consumer apps": "consumer",
    "Deep tech / research": "deep tech",
    "Indie hacking": "indie hacker",
    "ML / AI": "AI",
    "AI / ML": "AI",
    "Agentic AI": "AI agents",
    "Startups": "startup",
    "Developer tools": "developer tools",
    "Web3 / Crypto": "crypto",
    "Climate tech": "climate",
    "Robotics": "robotics",
    "SaaS": "SaaS",
}


def _linkedin_key(url: str) -> str:
    raw = (url or "").strip().lower().rstrip("/")
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}" if host else ""


def outside_search_requests(card: AgentProfileCard, targets: list | None = None) -> list[dict]:
    """Filters for the external people search, one request per kind of person the owner wants to
    meet (a job title, plus what the owner works on as company keywords), near where the owner
    is. With no such kind, one request by keywords alone. No country is assumed; a card with no
    location searches everywhere."""
    from services.suggest_targets import owner_topics, targets_for

    targets = targets_for(card) if targets is None else targets
    location = (card.identity.location or "").strip()
    keywords = owner_topics(card)[:2]
    requests = [
        {"titles": [_TITLE_FOR[t.kind]], "keywords": keywords, "location": location, "limit": 4}
        for t in targets if t.kind in _TITLE_FOR
    ]
    if not requests and keywords:
        requests.append({"titles": [], "keywords": keywords, "location": location, "limit": 4})
    return requests


def _shape_outside(record: dict) -> dict | None:
    url = str(record.get("linkedin_url") or "").strip()
    name = str(record.get("name") or "").strip()
    if not url and not name:
        return None
    return {
        "name": name,
        "title": str(record.get("title") or "").strip(),
        "company": str(record.get("company") or "").strip(),
        "linkedin_url": url,
        "source": "quickenrich",
    }


def _outside_people(request: dict) -> list[dict]:
    """One request to Memory's external people search (the only QuickEnrich client)."""
    url = f"{config.MEMORY_LAYER_URL.rstrip('/')}/v1/service/outside-people"
    try:
        resp = httpx.post(
            url, json=request, timeout=config.QUICKENRICH_TIMEOUT,
            headers={"Authorization": f"Bearer {config.MEMORY_SERVICE_TOKEN}", "Accept": "application/json"},
        )
        if resp.status_code >= 400:
            logger.warning("outside-people failed: HTTP %s %s", resp.status_code, (resp.text or "")[:300])
            return []
        payload = resp.json()
    except Exception as exc:
        logger.warning("outside-people failed: %s", exc)
        return []
    if isinstance(payload, dict) and payload.get("warning"):
        logger.info("outside-people returned nothing: %s", payload["warning"])
    records = payload.get("people") if isinstance(payload, dict) else None
    return [
        shaped
        for record in records or []
        if isinstance(record, dict) and (shaped := _shape_outside(record))
    ]


def outside_search_enabled() -> bool:
    return bool(config.MEMORY_LAYER_URL and config.MEMORY_SERVICE_TOKEN)


OUTSIDE_PER_REQUEST = 2       # people kept from one external request
MAX_OUTSIDE = 2               # people not on Zynd yet that one owner is shown
ZYND_LINKEDIN_TTL = 600       # seconds the set of LinkedIn profiles already on Zynd is reused
_zynd_linkedin: tuple[float, set[str]] = (0.0, set())


def search_outside(card: AgentProfileCard, taken: set[str], limit: int | None = None) -> list[dict]:
    """Up to OUTSIDE_PER_REQUEST new people from each request, skipping LinkedIn profiles in
    `taken`; stops asking once it has `limit` (each request is a paid lookup)."""
    if not outside_search_enabled():
        return []
    out = []
    seen = set(taken)
    for request in outside_search_requests(card):
        if limit is not None and len(out) >= limit:
            break
        added = 0
        for person in _outside_people(request):
            key = _linkedin_key(person.get("linkedin_url") or "") or person.get("name")
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(person)
            added += 1
            if added >= OUTSIDE_PER_REQUEST:
                break
    return out if limit is None else out[:limit]


def _zynd_linkedin_keys() -> set[str]:
    """LinkedIn profiles that already have a published Zynd card, reused for ZYND_LINKEDIN_TTL so
    a digest run doesn't read every card once per owner."""
    global _zynd_linkedin
    import time

    at, keys = _zynd_linkedin
    if time.monotonic() - at < ZYND_LINKEDIN_TTL:
        return keys
    from services import cards as cards_service
    keys = set()
    for row in cards_service.list_published_rows(columns="card"):
        links = ((row.get("card") or {}).get("identity") or {}).get("links") or {}
        if key := _linkedin_key(links.get("linkedin") or ""):
            keys.add(key)
    _zynd_linkedin = (time.monotonic(), keys)
    return keys


def outside_for(card: AgentProfileCard, people: list[dict]) -> list[dict]:
    """People not on Zynd yet, for an owner with too few Zynd suggestions: at most MAX_OUTSIDE,
    never someone whose LinkedIn is already on a Zynd card."""
    if not outside_search_enabled():
        return []
    taken = {_card_linkedin_key(card)} - {""}
    taken |= {k for p in people if (k := _linkedin_key(p.get("linkedin_url") or ""))}
    try:
        taken |= _zynd_linkedin_keys()
    except Exception as exc:  # noqa: BLE001 — dedupe against Zynd is best effort
        logger.info("outside dedupe failed: %s", exc)
    from services import invites

    can_invite = invites.enabled()
    outside = search_outside(card, taken, limit=MAX_OUTSIDE)
    for person in outside:
        person.setdefault("source", "quickenrich")
        person["label"] = "Not on Zynd yet"
        # A2: the owner can invite them to claim a card (POST /network/invites) from owner home.
        person["invitable"] = can_invite and bool(person.get("linkedin_url"))
    return outside


def _card_linkedin_key(card: AgentProfileCard) -> str:
    links = card.identity.links or {}
    return _linkedin_key(links.get("linkedin") or "")


def get_suggested_people(handle: str) -> dict | None:
    """{handle, people, outside} for the public suggested-people route: the owner's suggestions
    (services/suggestions.py), without the digest cooldown. None when there is no such card."""
    from services import suggestions

    return suggestions.for_owner(handle, "api", k=2)
