"""Word-level matching for card search.

Search used to test `token in search_text` as a substring, so "in" and "who" matched
nearly every card and "ai" matched "maintain". Queries are now reduced to meaningful
terms (stopwords out) and matched against whole words, with a light plural stem and
punctuation squashed so "Next.js" and "nextjs" are one word.
"""
from __future__ import annotations

import re

STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at", "who", "whom", "whose",
    "which", "that", "this", "these", "those", "with", "from", "into", "by", "me", "my", "i",
    "we", "our", "us", "you", "your", "is", "are", "be", "been", "am", "it", "its", "as", "if",
    "find", "show", "get", "give", "list", "search", "looking", "look", "want", "need", "like",
    "people", "person", "someone", "anyone", "somebody", "folks", "based", "located", "near",
    "around", "does", "do", "has", "have", "having", "about", "any", "some", "good", "great",
    "best", "top", "would", "could", "can", "please", "help", "who's",
})

# raw token: letters/digits with inner . - so "next.js", "seed-stage", "c++" stay together
_RAW = re.compile(r"[a-z0-9][a-z0-9+#]*(?:[.\-'][a-z0-9+#]+)*")
_SQUASH = re.compile(r"[^a-z0-9+#]")

# Common places spelled two ways; the key is what a card or a query might say.
_LOCATION_ALIASES = {
    "bengaluru": "bangalore", "bombay": "mumbai", "gurugram": "gurgaon",
    "nyc": "newyork", "sf": "sanfrancisco",
}


def _stem(word: str) -> str:
    """Plural-insensitive: investors == investor, tools == tool; leaves ai, ss, us, is alone."""
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _forms(raw: str) -> list[str]:
    """Match forms for one raw token: the squashed whole ("nextjs"), plus its parts when it
    was hyphenated or dotted ("seed", "stage")."""
    whole = _stem(_SQUASH.sub("", raw))
    parts = [_stem(_SQUASH.sub("", p)) for p in re.split(r"[.\-']", raw)]
    forms = [whole] if whole else []
    if len(parts) > 1:
        forms.extend(p for p in parts if p)
    return forms


def token_set(text: str) -> set[str]:
    """Every whole-word form in `text`, for membership tests."""
    out: set[str] = set()
    for raw in _RAW.findall((text or "").lower()):
        out.update(_forms(raw))
    return out


def query_terms(text: str) -> list[str]:
    """Meaningful, de-duplicated terms of a query, order kept, stopwords removed.

    A dotted name ("next.js") is one term; a hyphenated phrase ("seed-stage") is split.
    """
    terms: list[str] = []
    for raw in _RAW.findall((text or "").lower()):
        pieces = [raw.replace(".", "")] if "." in raw and "-" not in raw else re.split(r"-", raw)
        for piece in pieces:
            if piece in STOPWORDS:
                continue
            term = _stem(_SQUASH.sub("", piece))
            if term and term not in STOPWORDS and term not in terms:
                terms.append(term)
    return terms


def contains_all(haystack_tokens: set[str], text: str) -> bool:
    """True when every meaningful term of `text` is a whole word in the haystack."""
    terms = query_terms(text)
    return bool(terms) and all(t in haystack_tokens for t in terms)


def location_terms(text: str) -> list[str]:
    return [_LOCATION_ALIASES.get(t, t) for t in query_terms(text)]


def location_tokens(text: str) -> set[str]:
    return {_LOCATION_ALIASES.get(t, t) for t in token_set(text)}


# A role word and the words people actually put in a headline for it. A search for an
# "investor" should find "Partner at a venture fund"; one for an "engineer" a "backend
# developer". Deliberately small: wide enough for the common roles, narrow enough not to
# turn every search into a thesaurus lookup.
ROLE_SYNONYMS: dict[str, frozenset[str]] = {
    "investor": frozenset({"vc", "venture", "angel", "fund", "investing", "invest"}),
    "founder": frozenset({"cofounder", "cofound", "founding", "entrepreneur", "ceo"}),
    "engineer": frozenset({"developer", "programmer", "swe", "engineering"}),
    "developer": frozenset({"engineer", "programmer", "swe"}),
    "designer": frozenset({"design", "ux", "ui", "designing"}),
    "recruiter": frozenset({"talent", "recruiting", "hiring", "sourcer"}),
    "advisor": frozenset({"mentor", "adviser", "advising", "mentoring"}),
    "marketing": frozenset({"marketer", "growth", "seo"}),
    "researcher": frozenset({"scientist", "research", "phd", "professor"}),
    "lawyer": frozenset({"counsel", "attorney", "legal", "law"}),
}


# Phrases that contain a role word without naming a role: "backing AI developer tools" is not a
# developer. Removed before a text is read for roles (role_tokens), never from its words otherwise.
_NOT_A_ROLE = re.compile(r"\bdev(?:eloper)?[\s-]+tool(?:s|ing)?\b")


def role_tokens(text: str) -> set[str]:
    """token_set for role checks: the words of `text` minus phrases that only look like a role."""
    return token_set(_NOT_A_ROLE.sub(" ", (text or "").lower()))


def role_matches(haystack_tokens: set[str], role: str) -> bool:
    """Every meaningful word of `role` is present, or a close synonym of it is."""
    terms = query_terms(role)
    return bool(terms) and all(
        t in haystack_tokens or ROLE_SYNONYMS.get(t, frozenset()) & haystack_tokens
        for t in terms
    )
