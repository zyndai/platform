"""Turn "seed-stage investor who backs AI dev tools in India" into structured filters.

find_people used to hand the raw string to every source. Each source then did its own
crude word-splitting (QuickEnrich took the first four words and dropped "AI" and
"India" under a 3-letter rule). One parser now produces {role, stage, topics, location}
and every source maps it onto its own filters.

`parse_target_heuristic` is deterministic, offline and always available. `parse_target`
asks a small LLM first when one is configured and falls back to the heuristic on any
failure, so a flaky model never makes a search worse than it was.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field

from app.config import settings

logger = logging.getLogger(__name__)

MAX_TOPICS = 3
_LLM_TIMEOUT = 6.0
_CACHE_MAX = 256

LIKE_ME = frozenset({"like_me", "like me", "people like me", "similar to me"})


@dataclass(frozen=True)
class TargetQuery:
    raw: str
    role: str = ""                    # canonical key from ROLES, e.g. "investor"
    titles: tuple[str, ...] = ()      # job-title keywords for title-based sources
    stage: str = ""                   # "seed", "series a", ...
    topics: tuple[str, ...] = ()      # what they work on / back, as short phrases
    location: str = ""                # as the user wrote it ("India", "Bengaluru")
    country_code: str = ""            # ISO 3166-1 alpha-2 when recognised
    locality: str = ""                # city when one was named
    company_hint: bool = False        # the target is described via their company
    required_skills: tuple[str, ...] = ()   # skills the user explicitly asked for ("knows Rust")

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)

    @property
    def role_noun(self) -> str:
        """The single noun a headline would contain ("engineer" for an ML engineer)."""
        return ROLE_NOUNS.get(self.role, self.role_label)

    def search_text(self) -> str:
        """Compact natural-language form for embedding / full-text sources."""
        parts = [self.stage, self.role_label, *self.topics, self.location]
        text = " ".join(p for p in parts if p).strip()
        return text or self.raw

    def as_dict(self) -> dict:
        return asdict(self)


# role key -> (words that signal it, title keywords for people-search APIs)
ROLES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "investor": (("investor", "investors", "vc", "vcs", "angel", "angels", "venture capitalist",
                  "venture capital", "venture partner", "general partner", "limited partner"),
                 ("Investor", "Venture Partner", "General Partner")),
    "founder": (("founder", "founders", "co-founder", "cofounder", "co-founders", "cofounders",
                 "entrepreneur", "entrepreneurs", "startup founder"),
                ("Founder", "Co-Founder", "CEO")),
    "cto": (("cto", "ctos", "head of engineering", "vp engineering", "engineering leader"),
            ("CTO", "VP Engineering", "Head of Engineering")),
    "engineer": (("engineer", "engineers", "developer", "developers", "programmer", "programmers",
                  "swe", "software engineer", "software engineers"),
                 ("Software Engineer", "Developer")),
    "ml": (("ml engineer", "machine learning engineer", "ai engineer", "data scientist",
            "ml researcher", "ai researcher", "research scientist"),
           ("Machine Learning Engineer", "Data Scientist", "Research Scientist")),
    "designer": (("designer", "designers", "product designer", "ux designer", "ui designer"),
                 ("Designer", "Product Designer")),
    "pm": (("product manager", "product managers", "pm", "pms", "head of product"),
           ("Product Manager", "Head of Product")),
    "recruiter": (("recruiter", "recruiters", "talent partner", "talent acquisition"),
                  ("Recruiter", "Talent")),
    "marketer": (("marketer", "marketers", "growth marketer", "head of growth", "marketing lead"),
                 ("Marketing", "Growth")),
    "sales": (("sales", "account executive", "salesperson", "head of sales", "gtm"),
              ("Sales", "Account Executive")),
    "researcher": (("researcher", "researchers", "scientist", "scientists", "professor", "phd"),
                   ("Researcher", "Scientist")),
    "advisor": (("mentor", "mentors", "advisor", "advisors", "adviser"),
                ("Advisor", "Mentor")),
    "devrel": (("devrel", "developer advocate", "developer advocates", "developer relations"),
               ("Developer Advocate", "Developer Relations")),
    "lawyer": (("lawyer", "lawyers", "attorney", "counsel", "legal"),
               ("Counsel", "Attorney")),
    "operator": (("operator", "operators", "coo", "chief of staff"),
                 ("COO", "Chief of Staff")),
}

ROLE_LABELS: dict[str, str] = {
    "cto": "CTO", "ml": "machine learning engineer", "pm": "product manager",
    "devrel": "developer advocate", "marketer": "marketing", "advisor": "advisor",
}
ROLE_NOUNS: dict[str, str] = {"ml": "engineer", "marketer": "marketing", "devrel": "developer advocate"}

# Roles whose organisation's own description tells you what they back or build.
_COMPANY_ROLES = frozenset({"investor", "founder", "cto", "operator"})

_STAGES = (
    "pre-seed", "preseed", "pre seed", "seed", "series a", "series b", "series c",
    "early-stage", "early stage", "growth-stage", "growth stage", "late-stage", "late stage",
)

_STOP = frozenset({
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at", "who", "whom", "which",
    "that", "this", "these", "those", "with", "from", "into", "by", "me", "my", "i", "we", "our",
    "us", "you", "your", "is", "are", "be", "been", "am", "find", "show", "get", "give", "list",
    "search", "looking", "look", "want", "need", "like", "people", "person", "someone", "anyone",
    "somebody", "folks", "someone's", "based", "located", "near", "around", "within", "stage",
    "does", "do", "has", "have", "having", "about", "any", "some", "good", "great", "best",
    "top", "who's", "that's", "would", "could", "can", "please", "help",
})
_FILLER = frozenset({
    "back", "backs", "backing", "backed", "invest", "invests", "investing", "invested",
    "fund", "funds", "funding", "building", "builds", "build", "working", "works", "work",
    "focused", "focus", "focusing", "interested", "passionate", "specializing", "specialising",
    "experienced", "expert", "experience", "doing", "make", "makes", "making", "cares",
    "care", "knows", "know", "knowledge", "into", "startups", "startup", "senior", "junior",
})
_COMPANY_WORDS = frozenset({"company", "companies", "startup", "startups", "firm", "firms", "fund", "funds"})

# name -> ISO alpha-2
COUNTRIES: dict[str, str] = {
    "india": "IN", "usa": "US", "us": "US", "u.s.": "US", "united states": "US", "america": "US",
    "uk": "GB", "u.k.": "GB", "united kingdom": "GB", "england": "GB", "britain": "GB",
    "germany": "DE", "france": "FR", "canada": "CA", "singapore": "SG", "uae": "AE",
    "united arab emirates": "AE", "australia": "AU", "brazil": "BR", "netherlands": "NL",
    "spain": "ES", "italy": "IT", "israel": "IL", "japan": "JP", "china": "CN",
    "switzerland": "CH", "sweden": "SE", "ireland": "IE", "nigeria": "NG", "kenya": "KE",
    "indonesia": "ID", "mexico": "MX", "south korea": "KR", "korea": "KR", "portugal": "PT",
    "poland": "PL", "estonia": "EE", "hong kong": "HK", "saudi arabia": "SA", "egypt": "EG",
    "south africa": "ZA", "norway": "NO", "denmark": "DK", "finland": "FI", "belgium": "BE",
    "austria": "AT", "new zealand": "NZ", "argentina": "AR", "colombia": "CO", "chile": "CL",
    "vietnam": "VN", "philippines": "PH", "thailand": "TH", "malaysia": "MY",
    "pakistan": "PK", "bangladesh": "BD", "sri lanka": "LK", "turkey": "TR", "ukraine": "UA",
}

# city -> (display locality, ISO alpha-2)
CITIES: dict[str, tuple[str, str]] = {
    "bangalore": ("Bengaluru", "IN"), "bengaluru": ("Bengaluru", "IN"), "mumbai": ("Mumbai", "IN"),
    "bombay": ("Mumbai", "IN"), "delhi": ("Delhi", "IN"), "new delhi": ("New Delhi", "IN"),
    "hyderabad": ("Hyderabad", "IN"), "pune": ("Pune", "IN"), "chennai": ("Chennai", "IN"),
    "gurgaon": ("Gurugram", "IN"), "gurugram": ("Gurugram", "IN"), "noida": ("Noida", "IN"),
    "kolkata": ("Kolkata", "IN"), "ahmedabad": ("Ahmedabad", "IN"),
    "san francisco": ("San Francisco", "US"), "sf": ("San Francisco", "US"),
    "bay area": ("San Francisco", "US"), "new york": ("New York", "US"), "nyc": ("New York", "US"),
    "boston": ("Boston", "US"), "seattle": ("Seattle", "US"), "austin": ("Austin", "US"),
    "los angeles": ("Los Angeles", "US"), "chicago": ("Chicago", "US"), "miami": ("Miami", "US"),
    "denver": ("Denver", "US"), "london": ("London", "GB"), "berlin": ("Berlin", "DE"),
    "munich": ("Munich", "DE"), "paris": ("Paris", "FR"), "toronto": ("Toronto", "CA"),
    "vancouver": ("Vancouver", "CA"), "dubai": ("Dubai", "AE"), "tel aviv": ("Tel Aviv", "IL"),
    "amsterdam": ("Amsterdam", "NL"), "stockholm": ("Stockholm", "SE"), "lisbon": ("Lisbon", "PT"),
    "barcelona": ("Barcelona", "ES"), "madrid": ("Madrid", "ES"), "sydney": ("Sydney", "AU"),
    "melbourne": ("Melbourne", "AU"), "tokyo": ("Tokyo", "JP"), "lagos": ("Lagos", "NG"),
    "nairobi": ("Nairobi", "KE"), "jakarta": ("Jakarta", "ID"), "sao paulo": ("Sao Paulo", "BR"),
}

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#.'/-]*")
_FREE_LOCATION = re.compile(
    r"\b(?:in|based in|from|near)\s+([A-Z][\w-]+(?:\s+[A-Z][\w-]+){0,2})\b")


_NON_WORD = re.compile(r"[^a-z0-9+#.]+")


def _norm(text: str) -> str:
    """Lowercase words separated by single spaces; commas, hyphens and brackets are
    separators, so "Pune, India" and "seed-stage" match as the words they contain."""
    return " ".join(_NON_WORD.sub(" ", (text or "").lower()).split())


def _find_phrase(haystack: str, needles: list[str]) -> str:
    """Longest needle that appears in haystack as whole words, else ''."""
    padded = f" {haystack} "
    for needle in sorted(needles, key=len, reverse=True):
        if f" {needle} " in padded:
            return needle
    return ""


# "developer tools", "sales automation": the role word is a modifier of a topic here.
_COMPOUND_FOLLOWERS = frozenset({
    "tool", "tools", "tooling", "platform", "platforms", "infrastructure", "experience",
    "productivity", "ecosystem", "community", "software", "automation", "stack", "workflow",
    "workflows", "framework", "frameworks", "library", "libraries", "api", "apis", "product",
})


def _detect_role(text: str) -> tuple[str, str]:
    """(role key, matched phrase). The head noun usually comes first ("investor who backs
    developer tools"), so the earliest phrase wins, the longest on a tie; a role word used
    as a modifier ("developer tools") is not the role."""
    words = _norm(text).split()
    best: tuple[int, int, str, str] | None = None     # (start, -length, key, phrase)
    for key, (spellings, _titles) in ROLES.items():
        for spelling in spellings:
            phrase = _norm(spelling).split()
            n = len(phrase)
            for start in range(len(words) - n + 1):
                if words[start:start + n] != phrase:
                    continue
                follower = words[start + n] if start + n < len(words) else ""
                if follower in _COMPOUND_FOLLOWERS:
                    continue
                candidate = (start, -n, key, " ".join(phrase))
                if best is None or candidate[:2] < best[:2]:
                    best = candidate
    return (best[2], best[3]) if best else ("", "")


def _detect_location(text: str) -> tuple[str, str, str, str]:
    """(display text, country_code, locality, matched normalized phrase)."""
    norm = _norm(text)
    city = _find_phrase(norm, list(CITIES))
    country = _find_phrase(norm, [c for c in COUNTRIES if len(c) > 2 or c in norm.split()])
    if city:
        locality, code = CITIES[city]
        if country and COUNTRIES[country] != code:
            return country.title(), COUNTRIES[country], "", country
        return locality, code, locality, city
    if country:
        return country.upper() if len(country) <= 3 else country.title(), COUNTRIES[country], "", country
    free = _FREE_LOCATION.search(text or "")
    if free:
        phrase = free.group(1).strip()
        return phrase, "", "", _norm(phrase)
    return "", "", "", ""


def resolve_location(text: str) -> tuple[str, str, str]:
    """(display text, ISO country code, city) for a free-text place like "Pune, India"."""
    location, code, locality, _phrase = _detect_location(text or "")
    return location, code, locality


def query_from_filters(
    *, titles: list[str] | tuple[str, ...] = (), keywords: list[str] | tuple[str, ...] = (),
    location: str = "",
) -> TargetQuery:
    """A TargetQuery from already-structured filters (what Cards' suggestions send), so one
    QuickEnrich request builder serves every caller. Keywords describe the person's
    company, as everywhere else."""
    place, code, locality = resolve_location(location)
    clean_titles = tuple(t.strip()[:60] for t in titles if isinstance(t, str) and t.strip())[:5]
    clean_keywords = tuple(k.strip()[:60] for k in keywords if isinstance(k, str) and k.strip())[:5]
    return TargetQuery(
        raw=" ".join([*clean_titles, *clean_keywords, place]).strip(), titles=clean_titles,
        topics=clean_keywords, location=place, country_code=code, locality=locality,
        company_hint=True,
    )


# Programming languages: the one kind of skill a request names unambiguously.
LANGUAGES = ("javascript", "typescript", "python", "golang", "rust", "kotlin", "swift", "ruby", "java",
             "scala", "elixir", "haskell", "c++", "c#", "sql", "go")
_SKILL_ALIASES = {"golang": "go"}
_SKILL_CUE = re.compile(r"\b(?:knows?|engineers?|developers?|programmers?|skills?|proficient|using)\b", re.I)


def _required_skills(raw: str) -> tuple[str, ...]:
    """Skills that are a requirement, not a guess: "knows Rust", "Go engineer". Same rule as
    Cards' explicit_query_constraints (services/cards-api/services/search_constraints.py), so a
    topic like "AI dev tools" is never one. "Rust or Python" is an alternative, so no requirement."""
    if not _SKILL_CUE.search(raw):
        return ()
    skills: list[str] = []
    for language in LANGUAGES:
        if re.search(r"(?<![\w+#])" + re.escape(language) + r"(?![\w+#])", raw, re.I):
            if language == "go" and re.search(r"\bgo[- ]to[- ]market\b", raw, re.I):
                continue
            skills.append(_SKILL_ALIASES.get(language, language))
    skills = list(dict.fromkeys(skills))
    if len(skills) > 1 and re.search(r"\bor\b", raw, re.I):
        return ()
    return tuple(skills)


def parse_target_heuristic(target: str) -> TargetQuery:
    raw = " ".join((target or "").split())
    if not raw:
        return TargetQuery(raw="")

    role, role_phrase = _detect_role(raw)
    norm = _norm(raw)
    stage = _find_phrase(norm, [_norm(s) for s in _STAGES])
    location, code, locality, loc_phrase = _detect_location(raw)

    consumed: set[str] = set()
    for phrase in (role_phrase, stage, loc_phrase):
        consumed.update(phrase.split())
    for key in ROLES:  # every spelling of the role, so "investors who ..." drops both forms
        if key == role:
            for word in ROLES[key][0]:
                consumed.update(_norm(word).split())

    phrases: list[list[str]] = [[]]
    for token in _WORD.findall(raw):
        parts = _norm(token).split()
        removable = all(
            part in _STOP or part in _FILLER or part in consumed for part in parts
        )
        if removable:
            if phrases[-1]:
                phrases.append([])
            continue
        phrases[-1].append(token.strip(".,;:!?'\""))
    topics = tuple(
        " ".join(words)[:60] for words in phrases if words and " ".join(words)
    )[:MAX_TOPICS]

    return TargetQuery(
        raw=raw,
        role=role,
        titles=ROLES[role][1] if role else (),
        stage=stage,
        topics=topics,
        location=location,
        country_code=code,
        locality=locality,
        company_hint=bool(role in _COMPANY_ROLES or (set(norm.split()) & _COMPANY_WORDS)),
        required_skills=_required_skills(raw),
    )


# ── Optional LLM refinement ────────────────────────────────────────────────────────

_LLM_PROMPT = """You turn a request for people into search filters. Output ONLY JSON:
{"role": string, "stage": string, "topics": [string], "location": string}
role: the job role wanted, singular, lowercase ("investor", "founder", "designer", "ml engineer"). "" if none.
stage: funding stage only for investors/founders ("seed", "series a", "pre-seed"), else "".
topics: up to 3 short phrases for what they work on or back. Never include the role, stage or place.
location: the place if one is named ("India", "Berlin"), else "".
Never invent anything not in the request."""

_client = None
_cache: dict[str, TargetQuery] = {}


def _get_client():
    global _client
    if _client is None:
        from openai import AsyncOpenAI
        _client = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url,
                              timeout=_LLM_TIMEOUT)
    return _client


def _llm_enabled() -> bool:
    return bool(settings.deepseek_api_key) and not settings.mock_llm


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")) else word


def _grounded(topics: list, raw: str) -> list:
    """Keep only the LLM topics with a word (plural-insensitive) that the user actually wrote.
    The model returned "technology innovation" for an investor query that never said it."""
    said = {_stem(w) for w in _norm(raw).split()}
    return [t for t in topics if isinstance(t, str) and any(_stem(w) in said for w in _norm(t).split())]


def _merge_llm(base: TargetQuery, payload: dict) -> TargetQuery:
    """Overlay validated LLM output on the heuristic result. The LLM can add, never erase,
    something the heuristic found with a code (country) or a known role."""
    if not isinstance(payload, dict):
        return base
    role_text = str(payload.get("role") or "").strip().lower()[:60]
    role_key, _ = _detect_role(role_text) if role_text else ("", "")
    stage = str(payload.get("stage") or "").strip().lower()[:30] or base.stage
    topics_raw = payload.get("topics") if isinstance(payload.get("topics"), list) else []
    if settings.feature_people_search_v2:
        topics_raw = _grounded(topics_raw, base.raw)    # the model must not invent topics
    topics = tuple(
        t.strip()[:60] for t in topics_raw if isinstance(t, str) and t.strip()
    )[:MAX_TOPICS] or base.topics
    location_text = str(payload.get("location") or "").strip()[:80]
    location, code, locality = base.location, base.country_code, base.locality
    if location_text:
        loc, c, loc_city, _phrase = _detect_location(location_text)
        if not loc and location_text:
            loc = location_text
        location, code, locality = loc or base.location, c or base.country_code, loc_city or base.locality
    role = role_key or base.role
    return TargetQuery(
        raw=base.raw, role=role, titles=ROLES[role][1] if role else base.titles, stage=stage,
        topics=topics, location=location, country_code=code, locality=locality,
        company_hint=base.company_hint or role in _COMPANY_ROLES,
        required_skills=base.required_skills,
    )


async def parse_target(target: str) -> TargetQuery:
    """Structured filters for a described target; never raises."""
    base = parse_target_heuristic(target)
    if not base.raw or not _llm_enabled():
        return base
    key = base.raw.lower()
    if key in _cache:
        return _cache[key]
    try:
        resp = await _get_client().chat.completions.create(
            model=settings.extraction_model,
            messages=[{"role": "system", "content": _LLM_PROMPT},
                      {"role": "user", "content": base.raw[:300]}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        parsed = _merge_llm(base, json.loads(resp.choices[0].message.content or "{}"))
    except Exception as exc:  # noqa: BLE001 — a flaky model must not break search
        logger.warning("people_query LLM parse failed, using heuristic: %s", exc)
        return base
    if len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[key] = parsed
    return parsed


# ── Intent: is this a person's name? ───────────────────────────────────────────────
#
# "chandan" or "send a request to Chandan from Zynd" is not a role/topic/location description.
# Run through that parser, a name became a topic, and a topic became a required skill.

@dataclass(frozen=True)
class Intent:
    kind: str            # "name" | "target" | "like_me"
    name: str = ""       # the person's name, or the @handle when one was given
    company: str = ""    # "from Zynd" / "at Stripe", when given


_LEAD = re.compile(
    r"^(?:(?:can|could|would|will) you\s+|please\s+|pls\s+|i (?:want|need|would like|'d like) to\s+|let'?s\s+|help me\s+)*"
    r"(?:(?:send|make|create|draft)\s+(?:a\s+|an\s+|my\s+)?(?:connection\s+|connect\s+|intro\s+|introduction\s+)?"
    r"(?:request|invite|invitation|message|dm)\s+(?:to|for)\s+"
    r"|connect\s+(?:me\s+)?(?:with|to)\s+|introduce\s+me\s+to\s+|message\s+|dm\s+"
    r"|(?:find|look\s*up|search\s+for|search|show\s+me|who\s+is|who'?s|tell\s+me\s+about|get)\s+(?:me\s+)?(?:the\s+)?)?"
    r"(?:(?:the\s+)?(?:people|persons?|someone|user|guy|girl)\s+)?(?:(?:named|called)\s+)?",
    re.I)
_COMPANY_SPLIT = re.compile(r"\s+(?:from|at|@|of|works?\s+at|working\s+at)\s+", re.I)
_TRAIL = re.compile(r"\s*(?:on\s+zynd\b)?[\s?.!]*$", re.I)
_NAME_WORD = re.compile(r"[A-Za-z][A-Za-z'.-]*\Z")
_HANDLE_TOKEN = re.compile(r"@?[A-Za-z0-9][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)+\Z")

# Words that mean the query describes a kind of person or a field, never a person's name.
_TOPIC_WORDS = frozenset({
    "ai", "ml", "llm", "llms", "genai", "agents", "agent", "fintech", "saas", "climate", "climatetech",
    "health", "healthcare", "healthtech", "biotech", "crypto", "web3", "blockchain", "edtech", "education",
    "devtools", "developer", "tools", "marketing", "design", "software", "hardware", "robotics", "data",
    "cloud", "security", "cybersecurity", "gaming", "games", "ecommerce", "commerce", "retail", "logistics",
    "energy", "mobility", "agtech", "proptech", "insurtech", "legaltech", "martech", "adtech", "b2b", "b2c",
    "consumer", "enterprise", "deeptech", "infra", "infrastructure", "product", "growth", "finance",
    "banking", "payments", "payment", "quantum", "space", "automotive", "founder", "investor", "engineer",
})


def _guard_words() -> frozenset[str]:
    words: set[str] = set(_STOP) | set(_FILLER) | set(_TOPIC_WORDS) | set(LANGUAGES)
    for spellings, _titles in ROLES.values():
        for spelling in spellings:
            words.update(_norm(spelling).split())
    for stage in _STAGES:
        words.update(_norm(stage).split())
    for place in (*COUNTRIES, *CITIES):
        words.update(_norm(place).split())
    return frozenset(words)


_GUARD = _guard_words()


def detect_intent(target: str) -> Intent:
    """name, target or like_me. Precision first: anything that could be a description of people
    ("AI", "rust engineer", "investor from India") stays a target; only a short run of plain words
    nobody would use as a role, field or place is read as a name."""
    raw = " ".join((target or "").split())
    if raw.lower() in LIKE_ME:
        return Intent("like_me")
    text = _TRAIL.sub("", _LEAD.sub("", raw, count=1)).strip()
    if not text:
        return Intent("target")
    name_part, company = text, ""
    split = _COMPANY_SPLIT.split(text, maxsplit=1)
    if len(split) == 2:
        name_part, company = split[0].strip(), split[1].strip(" .,")
        if not company or len(company.split()) > 3:
            return Intent("target")
    tokens = name_part.split()
    if len(tokens) == 1 and _HANDLE_TOKEN.fullmatch(tokens[0]):
        return Intent("name", name=tokens[0].lstrip("@"), company=company)
    if not 1 <= len(tokens) <= 3:
        return Intent("target")
    for token in tokens:
        bare = token.lstrip("@")
        if not _NAME_WORD.fullmatch(bare):
            return Intent("target")
        if bare.lower() in _GUARD or (bare.isupper() and len(bare) <= 4 and len(bare) > 1):
            return Intent("target")   # "AI", "VC", "investor", "India"
    return Intent("name", name=" ".join(t.lstrip("@") for t in tokens), company=company)


# ── QuickEnrich title filters per role ─────────────────────────────────────────────
#
# A bare include list matched "Investor Grievance Officer" for an investor search. Each role
# has the titles that are the role and the words that make a title something else. QuickEnrich
# matches a title by substring (Q1 in the plan, unconfirmed), so "Principal" is fenced with
# exclusions for the engineers and teachers who also carry it.

ROLE_TITLE_FILTERS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "investor": (("Investor", "Angel Investor", "Venture Partner", "General Partner", "Managing Partner",
                  "Principal", "Venture Capitalist"),
                 ("Grievance", "Relations", "Communications", "Compliance", "Services", "Relationship",
                  "Officer", "Engineer", "Software", "Teacher")),
    "founder": (("Founder", "Co-Founder", "CEO"), ("Assistant", "Executive Assistant")),
    "cto": (("CTO", "VP Engineering", "Head of Engineering"), ("Assistant",)),
    "engineer": (("Software Engineer", "Developer", "Engineer"), ("Sales Engineer", "Support")),
    "ml": (("Machine Learning Engineer", "ML Engineer", "Data Scientist", "Research Scientist"),
           ("Sales", "Support", "Intern")),
    "designer": (("Designer", "Product Designer"), ("Interior", "Fashion")),
    "pm": (("Product Manager", "Head of Product"), ("Assistant",)),
    "recruiter": (("Recruiter", "Talent"), ()),
    "marketer": (("Marketing", "Growth"), ("Assistant", "Intern")),
    "sales": (("Sales", "Account Executive"), ("Assistant", "Intern")),
    "researcher": (("Researcher", "Scientist"), ("Intern",)),
    "advisor": (("Advisor", "Mentor"), ("Financial Advisor", "Insurance Advisor")),
    "devrel": (("Developer Advocate", "Developer Relations"), ()),
    "lawyer": (("Counsel", "Attorney"), ("Paralegal", "Assistant")),
    "operator": (("COO", "Chief of Staff"), ("Assistant",)),
}
assert set(ROLE_TITLE_FILTERS) == set(ROLES), "every role needs a title filter row"


def title_filters(query: TargetQuery) -> tuple[list[str], list[str]]:
    """(include, exclude) title words for a title-based source."""
    row = ROLE_TITLE_FILTERS.get(query.role) if settings.feature_people_search_v2 else None
    if row:
        return list(row[0]), list(row[1])
    return list(query.titles), []
