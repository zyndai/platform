"""Conservative explicit constraints; semantic similarity cannot waive these."""
import re
from dataclasses import dataclass

from models.card import AgentProfileCard
from services.search_text import contains_all, location_terms, location_tokens, role_matches, token_set

SKILL_ALIASES = {"js": "javascript", "ts": "typescript", "golang": "go", "python3": "python", "reactjs": "react", "nodejs": "node.js", "postgres": "postgresql"}
LANGUAGES = ("javascript", "typescript", "python", "golang", "rust", "kotlin", "swift", "ruby", "java", "scala", "elixir", "haskell", "c++", "c#", "sql", "go")


def skill_key(value: str) -> str:
    text = value.strip().casefold()
    return SKILL_ALIASES.get(text, text)


def skill_matches(wanted: str, have: str) -> bool:
    # Require the requested topic, not an arbitrary substring or a broader skill.
    return contains_all(token_set(skill_key(have)), skill_key(wanted))


def explicit_query_constraints(query: str) -> tuple[str, list[str]]:
    """Extract unambiguous city and language requirements. Vague queries stay semantic."""
    location = ""
    place = re.search(r"\b(?:based in|located in|in|near)\s+([\w .'-]+?)(?=\s+(?:with|who|using|knowing|open to|available for|and knows?|skilled in)\b|[?;]|$)", query, re.I)
    if place:
        candidate = place.group(1).strip(" .?")
        # "expert in Rust" describes a skill, not a city. Don't treat it as a location.
        if candidate.casefold() not in LANGUAGES and len(candidate.split()) <= 4 and not re.search(r"\b(?:engineers?|developers?|skills?|years?)\b", candidate, re.I):
            location = candidate
    skills = []
    if re.search(r"\b(?:knows?|engineers?|developers?|programmers?|skills?|proficient|using)\b", query, re.I):
        for language in LANGUAGES:
            if re.search(r"(?<![\w+#])" + re.escape(language) + r"(?![\w+#])", query, re.I):
                if language == "go" and re.search(r"\bgo[- ]to[- ]market\b", query, re.I):
                    continue
                skills.append(skill_key(language))
    # An alternative (Rust OR Python) is not an all-skills requirement. Leave
    # ambiguous alternatives semantic until an explicit filter is supplied.
    if len(skills) > 1 and re.search(r"\bor\b", query, re.I):
        skills = []
    return location, list(dict.fromkeys(skills))


@dataclass(frozen=True)
class Constraints:
    role: str = ""
    location: str = ""
    skills: tuple[str, ...] = ()
    industry: str = ""
    availability: str = ""
    experience_min: int | None = None

    @property
    def active(self) -> bool:
        return any((self.role, self.location, self.skills, self.industry, self.availability, self.experience_min is not None))

    def matches(self, card: AgentProfileCard) -> bool:
        from services.card_view import fact_object, fact_predicate, live_facts
        evidence = [s.name for s in card.skills]
        evidence += [fact_object(f) for f in live_facts(card.zynd_memory)
                     if fact_predicate(f) in ("has_skill", "has_expertise_in")]
        if self.skills and not all(any(skill_matches(w, h) for h in evidence) for w in self.skills):
            return False
        if self.location and not set(location_terms(self.location)) <= location_tokens(card.identity.location):
            return False
        roles = [card.identity.headline, *[str(j.get("title") or "") for j in (card.work_experience or []) if isinstance(j, dict)]]
        if any(fact_predicate(f) == "is_founder_of" for f in live_facts(card.zynd_memory)):
            roles.append("Founder")
        if self.role and not any(role_matches(token_set(r), self.role) for r in roles):
            return False
        if self.industry and not any(contains_all(token_set(i), self.industry) for i in card.industries):
            return False
        if self.availability and not contains_all(token_set(card.availability), self.availability):
            return False
        if self.experience_min is not None and (card.experience_years is None or card.experience_years < self.experience_min):
            return False
        return True
