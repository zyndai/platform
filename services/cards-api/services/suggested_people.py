"""Recommend published ZYND cards with overlapping profile interests."""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

import config
from models.card import AgentProfileCard
from services import cards as cards_service

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


def _card_interests(card: AgentProfileCard) -> dict[str, set[str]]:
    return {
        field: {
            canonical
            for value in (getattr(card, field) or [])
            if (canonical := canonical_keyword(field, value))
        }
        for field in FIELDS
    }


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


def _india_body() -> dict:
    return {
        "page": 1,
        "per_page": 4,
        "country_code": {"include": ["IN"], "exclude": []},
    }


def outside_search_bodies(card: AgentProfileCard) -> list[dict]:
    interests = _card_interests(card)
    titles = [_TITLE_FOR[k] for k in KEYWORDS["connect_with"] if k in interests["connect_with"]][:2]
    keywords = list(dict.fromkeys(
        _KEYWORD_FOR[k]
        for field in ("working_on", "love_talking_about")
        for k in KEYWORDS[field]
        if k in interests[field] and k in _KEYWORD_FOR
    ))[:2]
    bodies = []
    if titles:
        bodies.append({**_india_body(), "title": {"include": titles, "exclude": []}})
    if keywords:
        bodies.append({**_india_body(), "bio_li": {"include": keywords, "exclude": []}})
    return bodies


def _shape_outside(record: dict) -> dict | None:
    def field(key: str) -> str:
        text = str(record.get(key) or "").strip()
        return "" if text.upper() == "N/A" else text

    url = field("employee_linkedin")
    name = " ".join(part for part in (field("first_name"), field("last_name")) if part)
    if not url and not name:
        return None
    return {
        "name": name,
        "title": field("title"),
        "company": field("company_name"),
        "linkedin_url": url,
        "source": "quickenrich",
    }


def _qe_headers() -> dict:
    header = (config.QUICKENRICH_AUTH_HEADER or "Authorization").strip()
    key = config.QUICKENRICH_API_KEY
    return {
        header: f"Bearer {key}" if header.lower() == "authorization" else key,
        "Accept": "application/json",
    }


def _contact_finder(body: dict) -> list[dict]:
    url = f"{config.QUICKENRICH_BASE_URL.rstrip('/')}/api/employees/contact-finder"
    try:
        resp = httpx.post(url, json=body, headers=_qe_headers(), timeout=config.QUICKENRICH_TIMEOUT)
        if resp.status_code >= 400:
            logger.warning(
                "QuickEnrich contact-finder failed: HTTP %s %s",
                resp.status_code,
                (resp.text or "")[:300],
            )
            return []
        payload = resp.json()
    except Exception as exc:
        logger.warning("QuickEnrich contact-finder failed: %s", exc)
        return []
    records = payload.get("data") if isinstance(payload, dict) else payload
    return [
        shaped
        for record in records or []
        if isinstance(record, dict) and (shaped := _shape_outside(record))
    ]


def search_outside(card: AgentProfileCard, _taken: set[str]) -> list[dict]:
    if not config.QUICKENRICH_BASE_URL or not config.QUICKENRICH_API_KEY:
        return []
    out = []
    seen = set()
    for body in outside_search_bodies(card):
        for person in _contact_finder(body):
            url = person.get("linkedin_url") or ""
            key = url or person.get("name")
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(person)
            break
    return out


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


def _card_linkedin_key(card: AgentProfileCard) -> str:
    links = card.identity.links or {}
    return _linkedin_key(links.get("linkedin") or "")


def get_suggested_people(handle: str) -> dict | None:
    requester = cards_service.get_card_by_handle(handle)
    if not requester:
        return None
    interests = _card_interests(requester)
    if not any(interests.values()):
        return {"handle": handle, "people": [], "outside": []}

    results = []
    taken = set()
    if key := _card_linkedin_key(requester):
        taken.add(key)
    rows = cards_service.list_published_rows(columns="card,handle")
    for row in rows:
        candidate_handle = row.get("handle")
        if not candidate_handle or candidate_handle == handle:
            continue
        try:
            candidate = AgentProfileCard.model_validate(row.get("card") or {})
        except Exception:
            continue
        if key := _card_linkedin_key(candidate):
            taken.add(key)
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
    outside = []
    if config.QUICKENRICH_BASE_URL and config.QUICKENRICH_API_KEY:
        for person in search_outside(requester, taken):
            url = person.get("linkedin_url") or ""
            key = _linkedin_key(url)
            if key and key in taken:
                continue
            if key:
                taken.add(key)
            person.setdefault("source", "quickenrich")
            outside.append(person)
            if len(outside) == 2:
                break
    return {"handle": handle, "people": results[:2], "outside": outside}
