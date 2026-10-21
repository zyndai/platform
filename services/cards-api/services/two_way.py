"""Two-way matching: does the person we found also want to meet someone like the searcher?

A search for "seed investors" is a one-way question. A founder is a much better answer when
the investor's card says they want to meet founders. Cards already say who they want to meet
(`connect_with`) and what they are looking for (`is_seeking` facts the owner approved), so the
searcher's own card is reduced to the kinds of people they are and compared with that.

Pure functions over public card data; nothing private is read.
"""
from __future__ import annotations

from models.card import AgentProfileCard
from services.card_view import fact_object, fact_predicate, live_facts
from services.search_text import token_set

TWO_WAY_BOOST = 0.15

# connect_with label (see suggested_people.KEYWORDS) -> words a person of that kind has in their headline
_HEADLINE_WORDS: dict[str, frozenset[str]] = {
    "Founders": frozenset({"founder", "cofounder", "ceo", "entrepreneur"}),
    "Investors": frozenset({"investor", "vc", "venture", "angel"}),
    "Engineers": frozenset({"engineer", "developer", "programmer", "cto"}),
    "ML Researchers": frozenset({"ml", "researcher"}),
    "Product Managers": frozenset({"pm"}),
    "Designers": frozenset({"designer", "ux"}),
    "Operators": frozenset({"operator", "coo"}),
    "Scientists": frozenset({"scientist"}),
    "Recruiters": frozenset({"recruiter", "talent"}),
    "Mentors": frozenset({"mentor", "advisor"}),
    "Students": frozenset({"student"}),
    "Writers": frozenset({"writer", "author", "journalist"}),
    "DevRel": frozenset({"devrel", "advocate"}),
    "Researchers in my field": frozenset({"researcher", "professor", "phd"}),
}
# multi-word headline phrases
_HEADLINE_PHRASES: dict[str, tuple[frozenset[str], ...]] = {
    "Product Managers": (frozenset({"product", "manager"}),),
    "ML Researchers": (frozenset({"machine", "learning", "researcher"}),),
}
# what someone says they are working on -> the kind of person that makes them
_WORKING_ON_KIND = {
    "Building a startup": "Founders", "Indie hacking": "Founders", "Investing": "Investors",
    "Doing research": "Researchers in my field", "Grad school": "Students",
    "Teaching / mentoring": "Mentors", "Writing": "Writers", "Design / creative work": "Designers",
}
# approved is_seeking value -> the kinds of people who would fit it
_SEEKING_KINDS: dict[str, frozenset[str]] = {
    "investment": frozenset({"Investors"}),
    "co_founder": frozenset({"Founders", "Engineers", "Product Managers", "Designers", "Potential co-founders"}),
    "mentoring": frozenset({"Mentors"}),
    "being_mentored": frozenset({"Mentors"}),
    "technical_feedback": frozenset({"Engineers"}),
    "early_users": frozenset({"Customers"}),
}
_COFOUNDER_FITS = frozenset({"Founders", "Engineers", "Product Managers", "Designers"})


def kinds_of(card: AgentProfileCard) -> set[str]:
    """The kinds of person this card's owner is, from public fields only."""
    from services.suggested_people import canonical_keyword

    tokens = token_set(card.identity.headline)
    kinds = {kind for kind, words in _HEADLINE_WORDS.items() if words & tokens}
    for kind, phrases in _HEADLINE_PHRASES.items():
        if any(phrase <= tokens for phrase in phrases):
            kinds.add(kind)
    for value in card.working_on or []:
        label = canonical_keyword("working_on", value)
        if label in _WORKING_ON_KIND:
            kinds.add(_WORKING_ON_KIND[label])
    if kinds & _COFOUNDER_FITS:
        kinds.add("Potential co-founders")      # someone seeking a co-founder wants people like this
    return kinds


def wanted_kinds(card: AgentProfileCard) -> set[str]:
    """The kinds of person this card's owner says they want to meet."""
    from services.suggested_people import canonical_keyword

    wanted = {label for v in card.connect_with or [] if (label := canonical_keyword("connect_with", v))}
    for fact in live_facts(card.zynd_memory):
        if fact_predicate(fact) == "is_seeking":
            wanted |= _SEEKING_KINDS.get(fact_object(fact).strip().lower(), frozenset())
    return wanted


def two_way_match(searcher_kinds: set[str], candidate: AgentProfileCard) -> list[str]:
    """Kinds the candidate wants that the searcher is (empty = no two-way fit)."""
    if not searcher_kinds:
        return []
    return sorted(wanted_kinds(candidate) & searcher_kinds)


LESS_LIKE_PENALTY = 0.2


def too_much_like(disliked: AgentProfileCard, candidate: AgentProfileCard) -> bool:
    """True when `candidate` is the kind of person the searcher asked to see less of: the same
    kind of person (headline words) who also shares a skill or an industry with the disliked Card."""
    if candidate.handle == disliked.handle or not (kinds_of(disliked) & kinds_of(candidate)):
        return False
    skills = lambda c: {x.name.strip().lower() for x in c.skills if x.name.strip()}
    industries = lambda c: {i.strip().lower() for i in c.industries if i.strip()}
    return bool(skills(disliked) & skills(candidate) or industries(disliked) & industries(candidate))
