"""One result shape for people search, whatever source found the person.

    {handle, name, headline, location, why[], sources[], claimed, score,
     next_action: connect | invite_to_claim | view_profile, url, skills[], linkedin_url}

Cards is the one people index. A Zynd user is the same person as their Card (merged by
handle) and an external LinkedIn result is the same person as a Card that links the same
profile (merged by LinkedIn URL). Pure functions: no I/O, so the merge rules are unit-tested.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from app.services.people_query import CITIES, title_filters

# Scores are 0..1 and mean the same for every source: Cards' own score (relevance x fit x quality,
# services/cards-api/services/search.py), and for the other sources the same shape computed here:
# source relevance x a source prior x fit to the asked role, topics and place.
MULTI_SOURCE_BONUS = 0.05  # found by more than one source: the better score, a little higher
ZYND_PRIOR = 0.9           # a Zynd profile match is a weaker signal than a Card match
LINKEDIN_PRIOR = 0.8       # and LinkedIn a weaker one still, but it keeps the provider's order
EXTERNAL_BASE = 0.6        # a provider's first result, before the prior and fit
EXTERNAL_STEP = 0.02
ZYND_SEM_FLOOR, ZYND_SEM_SPAN = 0.20, 0.40   # as SEM_FLOOR/SEM_SPAN in cards-api search.py
FIT_ROLE_MISSING, FIT_TOPIC_MISSING, FIT_LOCATION_MISSING = 0.5, 0.8, 0.6
MAX_WHY = 8              # reasons kept per person while merging: the one that says what was loosened comes
                         # late in Cards' list and must survive until specific_why picks what to show
SHOWN_WHY = 4            # reasons shown where nothing picks the best (people like me, a group)
MAX_SPECIFIC_WHY = 3


def linkedin_key(url: object) -> str:
    """host/path of a LinkedIn profile URL, lowercased, or '' for anything else."""
    if not isinstance(url, str) or "linkedin.com" not in url.lower():
        return ""
    raw = url.strip()
    parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.rstrip("/").lower()
    return f"{host}{path}" if host.endswith("linkedin.com") and path else ""


def _next_action(handle: str | None, claimed: bool) -> str:
    if handle and claimed:
        return "connect"
    return "view_profile"


def with_invites(people: list[dict], uid: str, enabled: bool) -> list[dict]:
    """Offer an invitation to everyone who has no claimed Card but a LinkedIn profile and a name.

    The ref is signed here so invite_to_claim can trust the name and headline it will publish.
    Off, nobody is offered one and next_action stays view_profile."""
    if not enabled:
        return people
    from app.services import invite_refs
    for person in people:
        if person["claimed"] or not person.get("linkedin_url") or not person.get("name"):
            continue
        ref = invite_refs.sign(
            uid, linkedin_url=person["linkedin_url"], name=person["name"], headline=person.get("headline") or "")
        if ref:
            person["next_action"] = "invite_to_claim"
            person["invite_ref"] = ref
    return people


def _score(value: object) -> float:
    return round(float(value), 3) if isinstance(value, (int, float)) else 0.0


def person_from_card(row: dict, keep: tuple[str, ...] = ()) -> dict:
    """A Cards search hit (see people_discovery.search_cards). `keep` names extra Card fields to
    carry onto the person (the public MCP shows industries, availability, fresh_as_of)."""
    handle = row.get("handle") or None
    claimed = row.get("claimed") is True
    person = {
        "handle": handle,
        "name": row.get("name") or "",
        "headline": row.get("headline") or "",
        "location": row.get("location") or "",
        "why": list(row.get("why") or [])[:MAX_WHY],
        "sources": ["card"],
        "claimed": claimed,
        "score": _score(row.get("match_score")),
        "next_action": _next_action(handle, claimed),
        "url": row.get("url") or "",
        "skills": list(row.get("skills") or [])[:8],
        "linkedin_url": row.get("linkedin_url") or "",
        "verified": list(row.get("verified") or []),
    }
    if row.get("relaxed"):
        person["relaxed"] = list(row["relaxed"])   # which filters Cards had to loosen to include them
    for field in keep:
        if row.get(field) not in (None, "", []):
            person[field] = row[field]
    return person


def person_from_zynd(row: dict, card: dict, card_url: str) -> dict:
    """A Zynd user that matched on profile similarity, identified by their Card."""
    handle = card.get("handle") or None
    return {
        "handle": handle,
        "name": card.get("name") or row.get("display_name") or "",
        "headline": card.get("headline") or "",
        "location": card.get("location") or "",
        "why": [f"Zynd profile · {label}" for label in (row.get("matched_on") or [])[:2]]
               or ["Matches their Zynd profile"],
        "sources": ["zynd"],
        "claimed": card.get("claimed") is True,
        "score": _score(max(0.0, min(1.0, ((row.get("similarity") or 0.0) - ZYND_SEM_FLOOR) / ZYND_SEM_SPAN)) * ZYND_PRIOR),
        "next_action": _next_action(handle, card.get("claimed") is True),
        "url": card_url,
        "skills": [],
        "linkedin_url": "",
        "verified": [],
    }


def person_from_external(row: dict, index: int) -> dict:
    """An external (LinkedIn) result: no Card yet, so nothing to connect to."""
    title, company = row.get("title") or "", row.get("company") or ""
    headline = f"{title} at {company}" if title and company else (title or company)
    return {
        "handle": None,
        "name": row.get("name") or "",
        "headline": headline,
        "location": row.get("location") or "",
        "why": ["Found on LinkedIn" + (f" · {headline}" if headline else "")],
        "sources": ["linkedin"],
        "claimed": False,
        # a re-ranked row carries its own score; otherwise keep the provider's order
        "score": _score(row["score"]) if isinstance(row.get("score"), (int, float))
                 else round(max(EXTERNAL_BASE - EXTERNAL_STEP * index, 0.0) * LINKEDIN_PRIOR, 3),
        "next_action": "view_profile",
        "url": row.get("linkedin_url") or "",
        "skills": [],
        "linkedin_url": row.get("linkedin_url") or "",
        "verified": [],
    }


def identity_keys(person: dict) -> list[str]:
    keys = []
    if person.get("handle"):
        keys.append(f"handle:{person['handle'].lower()}")
    li = linkedin_key(person.get("linkedin_url"))
    if li:
        keys.append(f"li:{li}")
    return keys


def _absorb(base: dict, other: dict) -> None:
    new_source = any(src not in base["sources"] for src in other["sources"])
    for source in other["sources"]:
        if source not in base["sources"]:
            base["sources"].append(source)
    for reason in other["why"]:
        if reason not in base["why"]:
            base["why"].append(reason)
    base["why"] = base["why"][:MAX_WHY]
    for field in ("name", "headline", "location", "url", "linkedin_url"):
        if not base.get(field) and other.get(field):
            base[field] = other[field]
    if other.get("relaxed") and not base.get("relaxed"):
        base["relaxed"] = other["relaxed"]
    if not base["handle"] and other["handle"]:
        base["handle"], base["claimed"] = other["handle"], other["claimed"]
        base["next_action"] = other["next_action"]
    if other.get("skills") and not base.get("skills"):
        base["skills"] = other["skills"]
    base["verified"] = sorted(set(base.get("verified") or []) | set(other.get("verified") or []))
    best = max(base["score"], other["score"])
    base["score"] = round(min(best + (MULTI_SOURCE_BONUS if new_source else 0.0), 1.0), 3)


def merge_people(people: list[dict]) -> list[dict]:
    """One entry per person, keyed by Card handle or LinkedIn URL, best score first."""
    merged: list[dict] = []
    by_key: dict[str, dict] = {}
    for person in people:
        keys = identity_keys(person)
        existing = next((by_key[k] for k in keys if k in by_key), None)
        if existing is None:
            existing = person
            merged.append(person)
        else:
            _absorb(existing, person)
        for key in set(keys) | set(identity_keys(existing)):
            by_key[key] = existing
    return sorted(merged, key=lambda p: (-p["score"], not p["claimed"], p["name"].lower()))


def _words(text: str) -> set[str]:
    """Whole words, plus the parts of hyphenated or dotted ones: "Co-Founder" is also "founder"."""
    out: set[str] = set()
    for word in _WORD.findall((text or "").lower()):
        out.add(word.rstrip(".-"))
        if "-" in word or "." in word:
            out.update(p for p in __import__("re").split(r"[.-]", word) if p)
    return out


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")) else word


def features(person: dict, query) -> dict:
    """How well one person fits what was asked, whatever source found them. Each value is 0..1,
    or None when that part was not asked: role_fit (their headline says it), topic_fit (share of
    topics in their headline, skills or reasons) and location_fit."""
    headline = {_stem(w) for w in _words(person.get("headline"))}
    # What the person is about. A reason that says what was LOOSENED ("Not an investor (closest match)")
    # is about the search, not the person: counting it made a non-investor look like one.
    reasons = [w for w in person.get("why") or [] if isinstance(w, str) and not w.lower().startswith(_RELAXED_WHY)]
    around = {_stem(w) for w in _words(" ".join([person.get("headline") or "", " ".join(person.get("skills") or []),
                                                 " ".join(reasons)]))}
    role = {_stem(w) for w in _words(query.role_noun or query.role_label)} if query.role else set()
    topics = [{_stem(w) for w in _words(t)} - {"a", "of", "the"} for t in query.topics]
    place = {_stem(w) for w in _words(query.locality or query.location)}
    out: dict = {"role_fit": None, "topic_fit": None, "location_fit": None}
    sources = person.get("sources") or ()
    is_card = "card" in sources
    if role:
        out["role_fit"] = 1.0 if role <= headline else (0.9 if role <= around else 0.0)
        # Cards read the whole card (job titles, approved facts) and says "Role match" when the role is
        # there; it no longer counts who someone wants to meet, so the reason can be trusted, unless the
        # role is what Cards had to loosen to find them (the role only in passing, "Not an investor").
        loosened_role = "role" in (person.get("relaxed") or ()) or any(
            isinstance(w, str) and w.lower().startswith(("not a ", "not an ")) for w in person.get("why") or [])
        if is_card and out["role_fit"] == 0.0 and "Role match" in (person.get("why") or []) and not loosened_role:
            out["role_fit"] = 0.9
        if "linkedin" in sources:
            out["role_fit"] = _linkedin_role_fit(person, query)
    # A LinkedIn record has a title and a company, nothing that says what the person works on, so
    # its topic fit is unknown, not missed (rescore marks it unchecked: close at best).
    if topics and "linkedin" not in sources:
        out["topic_fit"] = sum(1 for t in topics if t and t <= around) / len(topics)
        # Memory sees a card's headline, skills and reasons only. A Card that passed every filter and
        # that Cards scored strong was judged on its whole text: no topic word here is not a miss.
        if (out["topic_fit"] == 0.0 and is_card and not person.get("relaxed")
                and person.get("score", 0) >= STRONG_CARD):
            out["topic_fit"] = None
    if place:
        out["location_fit"] = 1.0 if (place <= {_stem(w) for w in _words(person.get("location"))}
                                      or _in_country(person.get("location") or "", query)) else 0.0
    return out


def _in_country(location: str, query) -> bool:
    """A country was asked ("in India") and the person names one of its cities ("Pune", "Gurgaon"):
    most cards give a city, not a country."""
    if query.locality or not query.country_code:
        return False
    low = f" {' '.join(_words(location))} "
    return any(code == query.country_code and f" {city} " in low for city, (_, code) in CITIES.items())


def _headline_names_role(person: dict, query) -> bool:
    """The headline itself says the role ("Investor at Acme"), as opposed to a title that is the
    role under another name ("Venture Partner")."""
    role = {_stem(w) for w in _words(query.role_noun or query.role_label)}
    text = _linkedin_title(person) if "linkedin" in (person.get("sources") or ()) else person.get("headline")
    return role <= {_stem(w) for w in _words(text)}


def _linkedin_title(person: dict) -> str:
    """The job title of a LinkedIn person: their headline is "title at company", and a company
    name ("Investor Relations Inc") says nothing about the person's role."""
    return (person.get("headline") or "").split(" at ", 1)[0]


PARTIAL_ROLE = 0.5   # a broad title ("Principal") at a company that does not look like the role's kind


def _linkedin_role_fit(person: dict, query) -> float:
    """A LinkedIn person was found by title: "Venture Partner" is an investor although the title
    never says "investor". Judge the title by the same include and exclude words the request used
    (people_discovery.title_strength): 1 for a title that is the role, PARTIAL_ROLE for a broad one
    at a company that does not look like a fund, 0 for another job ("Investor Grievance Officer")."""
    from app.services.people_discovery import BROAD_TITLE, title_strength

    title = _linkedin_title(person)
    company = (person.get("headline") or "").split(" at ", 1)[1] if " at " in (person.get("headline") or "") else ""
    strength = title_strength({"title": title, "company": company}, query)
    if strength >= 1.0:
        return 1.0
    role = {_stem(w) for w in _words(query.role_noun or query.role_label)}
    if role and role <= {_stem(w) for w in _words(title)} and strength > 0:
        return 1.0
    return PARTIAL_ROLE if strength == BROAD_TITLE else 0.0


def fit_factor(feats: dict) -> float:
    """The multiplier a missed requirement costs; 1.0 when everything asked was met."""
    factor = 1.0
    if feats["role_fit"] == 0.0:
        factor *= FIT_ROLE_MISSING
    if feats["topic_fit"] == 0.0:
        factor *= FIT_TOPIC_MISSING
    if feats["location_fit"] == 0.0:
        factor *= FIT_LOCATION_MISSING
    return factor


def rescore(people: list[dict], query) -> list[dict]:
    """Judge Zynd and LinkedIn people by the same fit as Cards judges its own (Cards' scores
    already include it), so a LinkedIn investor can beat a weak Card and a Zynd member who is
    not the role cannot."""
    for person in people:
        person["_features"] = feats = features(person, query)
        if "linkedin" in person["sources"] and query.topics:
            person["_topic_unchecked"] = True
        if person["sources"] != ["card"]:
            person["score"] = round(person["score"] * fit_factor(feats), 3)
    return people


_GENERIC_WHY = ("matches your search terms", "strong overall match", "matches their zynd profile", "approved fact",
                "found on linkedin", "role match")      # "role match" is Cards' word for the role found anywhere on the card
_RELAXED_WHY = ("not in ", "not a ", "not an ", "skill filter relaxed", "similar to people you asked")


def specific_why(person: dict, query) -> list[str]:
    """At most MAX_SPECIFIC_WHY reasons, most specific first, built from what the person fits and
    what their source said: the role, what they work on (an approved fact first), what was
    loosened, the place. Reasons that would be true of anyone returned (a generic "matches your
    search terms") are dropped."""
    feats = features(person, query)
    given = [w for w in person.get("why") or [] if isinstance(w, str) and w.strip()]
    lowered = [(w, w.lower()) for w in given]
    out: list[str] = []

    def add(text: str) -> None:
        if text and text not in out:
            out.append(text)

    if feats["role_fit"] is not None and feats["role_fit"] >= 0.9 and query.role_label:
        where = ("headline" if _headline_names_role(person, query) else "title") if feats["role_fit"] >= 1 \
            else "on their profile"
        add(f"{query.role_label.title()} ({where})")
    fact = next((w for w, low in lowered if low.startswith("approved fact: ")), "")
    if fact:
        add(fact.replace("Approved fact: ", "", 1) + " (approved fact)")
    elif feats["topic_fit"]:
        add("Works on " + ", ".join(query.topics))
    for w, low in lowered:
        if low.startswith(_RELAXED_WHY):
            add(w)
    if feats["location_fit"] and person.get("location"):
        add(person["location"])
    for w, low in lowered:
        if not low.startswith(_GENERIC_WHY) and not low.startswith("approved fact: ") and w != person.get("headline"):
            add(w)
    if not out and "linkedin" in person["sources"]:
        out.append("Found on LinkedIn")
    return out[:MAX_SPECIFIC_WHY]


STRONG_CARD = 0.5   # a Card's own score (cards-api search.py scale) for a good match


def is_strong(person: dict) -> bool:
    """A Card that passed every filter with a good score, or anyone who meets the asked role
    (when one was asked) and a topic or the place."""
    if "card" in person["sources"]:
        return not person.get("relaxed") and person["score"] >= STRONG_CARD
    f = person.get("_features") or {}
    if f.get("role_fit") is not None and f["role_fit"] < 0.9:
        return False
    if f.get("topic_fit") is None and f.get("location_fit") is None:
        return f.get("role_fit") is not None
    return bool(f.get("topic_fit")) or bool(f.get("location_fit"))


def strong_count(people: list[dict]) -> int:
    return sum(1 for p in people if is_strong(p))


QUALITY_ORDER = {"exact": 0, "close": 1, "loose": 2}
# A score never says more than its label: an assistant reads 0.84 as strong whatever match_quality says.
LOOSE_CEILING = 0.45      # below STRONG_CARD, so a loose match never counts as strong
CLOSE_CEILING = 0.79


def _quality(person: dict) -> str:
    if person.get("match_quality") == "exact":          # set by the name lookup
        return "exact"
    feats = person.get("_features") or {}
    relaxed = person.get("relaxed") or []
    role_fit = feats.get("role_fit")
    if role_fit == 0.0 or "role" in relaxed:
        return "loose"          # not the kind of person asked for is never a close match
    # what was missed or loosened, each once: a loosened place the person also is not in is one miss
    missed = {name.removesuffix("_fit").replace("topic", "topics") for name, v in feats.items() if v == 0.0}
    missed |= set(relaxed)
    # each doubt counts once: a broad title, a LinkedIn record that cannot show the asked topic
    partial = int(role_fit is not None and role_fit < 0.9) + int(bool(person.get("_topic_unchecked")))
    if not missed and not partial:
        return "exact"
    if len(missed) + partial <= 1:
        return "close"
    return "loose"


def order_by_quality(people: list[dict]) -> list[dict]:
    """Set match_quality (exact / close / loose) on each person, cap the score to what the label
    allows, and order exact before close before loose, then by score. Run before the list is cut to
    `k`, so a close LinkedIn investor is never dropped for a loose Card that scored higher."""
    for person in people:
        person["match_quality"] = quality = _quality(person)
        ceiling = LOOSE_CEILING if quality == "loose" else CLOSE_CEILING if quality == "close" else 1.0
        person["score"] = round(min(person["score"], ceiling), 3)
    # stable: within a tier and score, the order the caller had (merge's claimed-then-name, or a provider's)
    return sorted(people, key=lambda p: (QUALITY_ORDER[p["match_quality"]], -p["score"]))


def label_quality(people: list[dict]) -> str:
    """Make sure every person has a match_quality, drop the working features, and return a note when
    nobody matched exactly."""
    for person in people:
        if person.get("match_quality") not in QUALITY_ORDER:
            person["match_quality"] = _quality(person)
        person.pop("_features", None)
        person.pop("_topic_unchecked", None)
    if people and not any(p["match_quality"] == "exact" for p in people):
        return "No exact matches; these are the closest."
    return ""


_WORD = __import__("re").compile(r"[a-z0-9][a-z0-9+#.-]*")


def cap_why(people: list[dict]) -> list[dict]:
    """At most SHOWN_WHY reasons each, for results nothing ranked the reasons of (specific_why does)."""
    for person in people:
        person["why"] = list(person.get("why") or [])[:SHOWN_WHY]
    return people


def apply_preferences(people: list[dict], prefs: dict) -> list[dict]:
    """Drop people the searcher hid and people matching a topic they muted (A8). "Less like this"
    is applied by Cards while ranking, so it is not repeated here."""
    hidden = {h.lower() for h in prefs.get("hide_person") or []}
    muted = [set(_WORD.findall(topic.lower())) for topic in prefs.get("mute_topic") or [] if topic.strip()]
    if not hidden and not muted:
        return people
    kept = []
    for person in people:
        if (person.get("handle") or "").lower() in hidden:
            continue
        words = set(_WORD.findall(" ".join([person.get("name") or "", person.get("headline") or "",
                                            " ".join(person.get("skills") or []), " ".join(person.get("why") or [])]).lower()))
        if any(topic and topic <= words for topic in muted):
            continue
        kept.append(person)
    return kept
