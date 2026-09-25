"""Offline stand-ins for the embedding + extraction APIs (MOCK_LLM=true).

Lets the full pipeline run with zero API spend so you can watch assertions land
in Postgres. Two real, classic techniques:

  * mock_embed  — the "hashing trick" (feature hashing): hash each word to a
    bucket in a 1536-dim vector, then L2-normalize. Cosine similarity reflects
    word OVERLAP. A real embedding model would capture MEANING (so "car" and
    "automobile" would be close); this only makes shared *words* close. Good
    enough to demo entity resolution + matching; swap to real keys for quality.

  * mock_extract — regex rules mapping phrases to predicates. A real LLM reads
    context; this only catches the patterns below. Same output shape, so the
    rest of the pipeline is identical.
"""
import hashlib
import math
import re

from app.models import ExtractedAssertion

EMBED_DIM = 1536


def mock_embed(text: str) -> list[float]:
    vec = [0.0] * EMBED_DIM
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        digest = hashlib.md5(token.encode()).digest()
        bucket = int.from_bytes(digest[:8], "big") % EMBED_DIM
        sign = 1.0 if digest[8] & 1 else -1.0
        vec[bucket] += sign
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


# (regex, predicate, entity_type, confidence). Matched case-insensitively on the
# original text so entity names keep their casing.
_RULES: list[tuple[str, str, str, float]] = [
    (r"\blearning\s+(.+?)(?:[.,;]| and | but | while |$)", "is_learning", "skill_technical", 0.9),
    (r"\bbuilding\s+(?:an?\s+|the\s+)?(.+?)(?:[.,;]| and | but |$)", "is_building", "project_venture", 0.9),
    (r"\bworking on\s+(.+?)(?:[.,;]| and | but |$)", "is_working_on", "project_assignment", 0.85),
    (r"\b(?:intend to|intends to|plan(?:ning)? to|want to)\s+(.+?)(?:[.,;]| this | next |$)", "intends_to", "intent_project", 0.85),
    (r"\b(?:believe|believes)\s+(?:that\s+)?(.+?)(?:[.,;]|$)", "believes", "belief_opinion", 0.8),
    (r"\b(?:value|values|care about)\s+(.+?)(?:[.,;]| and |$)", "values", "belief_value", 0.8),
    (r"\b(?:located in|based in|liv(?:e|ing) in)\s+(.+?)(?:[.,;]| and |$)", "is_located_in", "place_physical", 0.85),
    (r"\b(?:frustrated by|frustrated with|annoyed by)\s+(.+?)(?:[.,;]| and |$)", "is_frustrated_by", "concept_topic", 0.8),
    (r"\b(?:inspired by|admire|admires)\s+(.+?)(?:[.,;]| and |$)", "is_inspired_by", "influence", 0.8),
    (r"\b(?:looking for|seeking|in search of)\s+(?:an?\s+)?(.+?)(?:[.,;]| and |$)", "is_seeking", "concept_topic", 0.8),
    (r"\b(?:co-?founder|teammate|collaborator)\s+(.+?)(?:[.,;]| and |$)", "has_collaborator", "collaborator", 0.85),
]


def _clean(phrase: str) -> str:
    phrase = phrase.strip().rstrip(".")
    phrase = re.sub(r"^(an?|the)\s+", "", phrase, flags=re.IGNORECASE)
    return " ".join(phrase.split()[:8])


def mock_extract(text: str) -> list[ExtractedAssertion]:
    out: list[ExtractedAssertion] = []
    seen: set[tuple[str, str]] = set()
    for pattern, predicate, entity_type, confidence in _RULES:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            name = _clean(match.group(1))
            key = (predicate, name.lower())
            if not name or key in seen:
                continue
            seen.add(key)
            out.append(ExtractedAssertion(
                predicate=predicate,
                object_name=name,
                object_type=entity_type,
                confidence=confidence,
            ))
    return out
