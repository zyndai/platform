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


# Synonyms that name an activity anyone may list ("working on Investing", "loves talking about
# Design"), not a job. They count in a headline or a job title, never in the rest of a card.
ACTIVITY_SYNONYMS = frozenset({
    "investing", "invest", "fund", "design", "designing", "research", "hiring", "law", "legal", "growth",
    "mentoring", "advising", "recruiting", "talent", "engineering", "founding", "seo",
})


def role_matches(haystack_tokens: set[str], role: str, activities: bool = True) -> bool:
    """Every meaningful word of `role` is present, or a close synonym of it is. activities=False
    leaves out ACTIVITY_SYNONYMS, for text that is not a headline or a job title."""
    terms = query_terms(role)
    return bool(terms) and all(
        t in haystack_tokens
        or (ROLE_SYNONYMS.get(t, frozenset()) - (frozenset() if activities else ACTIVITY_SYNONYMS)) & haystack_tokens
        for t in terms
    )


# --- Topics --------------------------------------------------------------------------------------
#
# A topic is a caller's guess at what the person works on ("developer tools"). Scored word by word,
# "developer tools" credited every developer and "AI development" every card that said "development".
# A topic of several words now has to appear as a phrase (its words close together); a single word
# that says nothing on its own ("tools", "software") is never a topic.

_TOPIC_CANON = {"developer": "dev", "development": "dev", "tooling": "tool", "devtool": "dev tool"}
GENERIC_TOPIC_TERMS = frozenset({
    "tool", "platform", "software", "company", "product", "service", "app", "system", "technology",
    "tech", "dev", "solution", "startup", "business", "thing", "stuff", "work", "project",
})
PHRASE_SLACK = 1          # one word may sit between a phrase's words: "tools for developers"
TOPIC_APART = 0.5         # every word of the phrase is on the card, but not together


def _canon(term: str) -> list[str]:
    return _TOPIC_CANON.get(term, term).split()


def topic_terms(topic: str) -> list[str]:
    """Canonical terms of one topic, order kept: "Developer Tools" -> ["dev", "tool"]."""
    out: list[str] = []
    for term in query_terms(topic):
        for t in _canon(term):
            if t not in out:
                out.append(t)
    return out


def term_sequence(text: str) -> list[str]:
    """The canonical terms of `text` in order (hyphenated words split), for phrase tests."""
    seq: list[str] = []
    for raw in _RAW.findall((text or "").lower()):
        for part in re.split(r"[.\-']", raw) if re.search(r"[\-']", raw) else [raw]:
            term = _stem(_SQUASH.sub("", part))
            if term:
                seq.extend(_canon(term))
    return seq


def topic_phrases(topics: str, already: set[str] | frozenset[str] = frozenset()) -> list[tuple[str, list[str]]]:
    """(label, terms) for each comma-separated topic worth scoring: not a lone generic word ("tools";
    "developer tools" is a real phrase), and not already answered by the query's own words
    (`already`, canonical terms), which count there."""
    out: list[tuple[str, list[str]]] = []
    for label in (t.strip() for t in (topics or "").split(",")):
        terms = topic_terms(label)
        if not terms or (len(terms) == 1 and terms[0] in GENERIC_TOPIC_TERMS) or all(t in already for t in terms):
            continue
        if all(terms != seen for _, seen in out):
            out.append((label, terms))
    return out


def phrase_score(seq: list[str], terms: list[str]) -> float:
    """1 when the phrase is on the text (its words within a short window). Otherwise up to
    TOPIC_APART for its specific words found apart ("climate" of "climate hardware"); generic words
    found on their own ("developer" of "developer tools") earn nothing. A one-word phrase is simply
    present or not."""
    if not terms:
        return 0.0
    if len(terms) == 1:
        return 1.0 if terms[0] in seq else 0.0
    wanted, have = set(terms), set(seq)
    if wanted <= have:
        window = len(terms) + PHRASE_SLACK
        for start in range(len(seq)):
            if seq[start] in wanted and wanted <= set(seq[start:start + window]):
                return 1.0
    specific = [t for t in terms if t not in GENERIC_TOPIC_TERMS]
    if not specific:
        return TOPIC_APART if wanted <= have else 0.0
    return TOPIC_APART * sum(1 for t in specific if t in have) / len(specific)
