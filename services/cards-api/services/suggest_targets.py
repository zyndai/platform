"""What to search for on a card owner's behalf: "who should I meet?" as up to three searches.

Suggestions used to match people who want the *same* things (two founders who both want
investors were suggested to each other). Here the owner's card is read as a request instead:

  who      the kinds of person the owner wants to meet: approved `is_seeking` facts first, then
           `connect_with` labels, then free-text `connect_with` values (matched to a kind by its
           words, or searched as written), and a current beacon before all of them;
  about    what the owner works on and talks about, and their top skills: soft topics that rank
           people up, never a requirement;
  where    the owner's location, applied later as a small boost (suggestions.NEAR_*), never a
           filter.

Pure functions over public card data; each Target is run through search.search_agents.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from models.card import AgentProfileCard
from services.card_view import fact_object, fact_predicate, live_facts
from services.suggested_people import KEYWORDS, _KEYWORD_FOR, canonical_keyword
from services.two_way import _SEEKING_KINDS, kind_from_text

MAX_TARGETS = 3
MAX_TOPICS = 3
MAX_FREE_TEXT_WORDS = 4

# connect_with kind -> (role the search requires, extra topics, how one of them is called).
# A kind with no role is searched by its words instead ("healthcare"), which the scorer still
# floors, so a vague kind never returns the whole corpus. Customers have no searchable shape.
KIND_SEARCH: dict[str, tuple[str, tuple[str, ...], str]] = {
    "Founders": ("founder", (), "Founder"),
    "Investors": ("investor", (), "Investor"),
    "Engineers": ("engineer", (), "Engineer"),
    "ML Researchers": ("researcher", ("machine learning",), "ML researcher"),
    "Product Managers": ("product manager", (), "Product manager"),
    "Designers": ("designer", (), "Designer"),
    "Operators": ("operator", (), "Operator"),
    "Scientists": ("scientist", (), "Scientist"),
    "Recruiters": ("recruiter", (), "Recruiter"),
    "Mentors": ("advisor", (), "Mentor"),
    "Potential co-founders": ("", ("co-founder",), "Potential co-founder"),
    "Students": ("student", (), "Student"),
    "Writers": ("writer", (), "Writer"),
    "DevRel": ("developer advocate", (), "Developer advocate"),
    "Researchers in my field": ("researcher", (), "Researcher"),
    "Healthcare builders": ("", ("healthcare",), "Healthcare builder"),
    "Robotics people": ("", ("robotics",), "Robotics"),
}


@dataclass(frozen=True)
class Target:
    """One search. `kind` is the connect_with label it came from ("" for free text or topics);
    `q` is searched as text, `topics` only rank, `role` is required (search keeps it)."""
    kind: str
    role: str = ""
    q: str = ""
    topics: tuple[str, ...] = field(default_factory=tuple)
    label: str = ""


def _short(value: str) -> str:
    text = " ".join((value or "").split())
    return text if text and len(text.split()) <= MAX_FREE_TEXT_WORDS else ""


def owner_topics(card: AgentProfileCard) -> list[str]:
    """What the owner works on and talks about, most specific first: known labels as search
    words, then short free-text values, then their top skills."""
    out: list[str] = []
    for field_name in ("working_on", "love_talking_about"):
        for value in getattr(card, field_name) or []:
            label = canonical_keyword(field_name, value)
            if label in _KEYWORD_FOR:
                out.append(_KEYWORD_FOR[label])
            elif not label and (free := _short(value)):
                out.append(free)
    out += [s.name.strip() for s in card.skills[:3] if s.name.strip()]
    seen: set[str] = set()
    unique = []
    for topic in out:
        if topic.lower() not in seen:
            seen.add(topic.lower())
            unique.append(topic)
    return unique[:MAX_TOPICS]


def wanted_in_order(card: AgentProfileCard) -> tuple[list[str], list[str]]:
    """(kinds, free-text wants): approved is_seeking kinds, then connect_with labels in the
    owner's order, then free-text connect_with values matched to a kind; values that match no
    kind come back as text to search for."""
    kinds: list[str] = []
    free: list[str] = []
    for fact in live_facts(card.zynd_memory):
        if fact_predicate(fact) == "is_seeking":
            for kind in sorted(_SEEKING_KINDS.get(fact_object(fact).strip().lower(), ())):
                kinds.append(kind)
    for value in card.connect_with or []:
        label = canonical_keyword("connect_with", value) or kind_from_text(value)
        if label in KEYWORDS["connect_with"]:
            kinds.append(label)
        elif text := _short(value):
            free.append(text)
    return list(dict.fromkeys(kinds)), list(dict.fromkeys(free))


def _label(name: str, topics: tuple[str, ...]) -> str:
    return f"{name} · {topics[0]}" if topics else name


def targets_for(card: AgentProfileCard) -> list[Target]:
    """Up to MAX_TARGETS searches for this owner, most specific first; [] when the card says
    nothing to search with."""
    from services.beacons import active_beacon

    topics = tuple(owner_topics(card))
    targets: list[Target] = []
    beacon = active_beacon(card)
    if beacon and beacon.text.strip():
        targets.append(Target(kind="", q=beacon.text.strip()[:200], topics=topics, label="Your beacon"))
    kinds, free = wanted_in_order(card)
    for kind in kinds:
        spec = KIND_SEARCH.get(kind)
        if not spec:
            continue
        role, extra, name = spec
        if role:
            want = tuple(dict.fromkeys((*extra, *topics)))[:MAX_TOPICS]
            targets.append(Target(kind=kind, role=role, topics=want, label=_label(name, want)))
        else:
            targets.append(Target(kind=kind, q=" ".join(extra), topics=topics, label=_label(name, topics)))
    for text in free:
        targets.append(Target(kind="", q=text, topics=topics, label=text))
    if not targets and topics:
        # Nobody named: people who work on what the owner works on.
        targets.append(Target(kind="", q=topics[0], topics=topics[1:], label=f"Works on {topics[0]}"))
    return targets[:MAX_TARGETS]
