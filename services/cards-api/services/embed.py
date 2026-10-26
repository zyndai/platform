import re

import config

EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIM = 1536


def embed_text(text: str) -> list[float]:
    text = (text or "").strip()
    if not text:
        return []
    client = config.get_openai_client()
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=text[:8000])
    return list(resp.data[0].embedding)


# "<name> — looking to connect with Founders, Investors — Zynd" (written by cards-web when a card is
# created) says who the owner wants to MEET. It is not who they are: in the text a search reads it made
# everyone who wants investors look like an investor ("Role match", word hits, a close embedding).
# Two-way matching reads the same wish from `connect_with` and `is_seeking` facts instead.
_WANTS_FACT = re.compile(r"(?:^|[—–-])\s*(?:is\s+)?(?:looking to (?:connect with|meet)|wants to meet)\s", re.I)
SEEKING_PREDICATES = frozenset({"is_seeking"})


# The same wish written in free text: "looking forward to meet builders, founders and investors".
_WISH_CLAUSE = re.compile(
    r"\b(?:(?:i\s+am|i'm|am)\s+)?(?:looking\s+(?:forward\s+)?to\s+(?:meet(?:ing)?|connect(?:ing)?\s+with)"
    r"|(?:want|wants|hoping|hope|keen)\s+to\s+(?:meet|connect\s+with))\b[^.;!?\n]*", re.I)


def strip_wishes(text: str) -> str:
    """Free text with the clauses that say who the person wants to meet taken out."""
    return _WISH_CLAUSE.sub(" ", text or "")


def is_wants_fact(text: str) -> bool:
    """A searchable fact that says who the owner wants to meet, not what they are or do."""
    return bool(_WANTS_FACT.search(text or ""))


def describes_person(fact: dict) -> bool:
    """An approved fact about the person, as opposed to what they are looking for."""
    from services.card_view import fact_predicate

    return fact_predicate(fact) not in SEEKING_PREDICATES


def card_search_text(card) -> str:
    """The text that describes the person, for the embedding, word matching and role checks. What
    they want (who to meet, what they seek) is left out; see _WANTS_FACT."""
    parts = [
        card.identity.name,
        card.identity.headline,
        card.identity.location,
        card.summary,
    ]
    parts += [s.name for s in card.skills]
    parts += [p.name for p in card.projects]
    parts += list(card.industries)
    parts += [ws.excerpt[:200] for ws in card.writing_samples if ws.excerpt]
    parts += [f for f in card.searchable_facts if not is_wants_fact(f)]
    parts += list(card.working_on)
    parts += list(card.can_help_with)
    if card.availability:
        parts.append(f"available {card.availability}")
    if card.experience_years:
        parts.append(f"{card.experience_years} years experience")
    if getattr(card, "zynd_memory", None):
        from services.card_view import fact_object, fact_predicate, live_facts

        for fact in live_facts(card.zynd_memory):
            if not describes_person(fact):
                continue
            parts.append(fact_object(fact))
            parts.append(fact_predicate(fact).replace("_", " "))
    return strip_wishes(" ".join(p for p in parts if p))
