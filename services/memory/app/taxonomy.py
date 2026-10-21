"""Single source of truth for predicates, decay, entity types, and clusters.

Brief §14.8: a new predicate requires a migration + prompt update + decay_fn.
Adding one here (and to the extraction prompt) is that change in one place.
"""

# Predicate -> decay half-life in days. None = no decay. (v2 predicate reference, 36 total.)
PREDICATE_HALFLIFE_DAYS: dict[str, int | None] = {
    # 1. Building & creating
    "is_building": 60,
    "is_working_on": 14,
    "is_creating": 60,
    "wants_to_preserve": 365,
    # 2. Learning & skills
    "is_learning": 30,
    "has_expertise_in": 540,         # 18 months
    "has_skill": 730,                # 2 years
    "uses_tool": 365,                # a product/tool the person operates, not builds or is expert in
    # 3. Goals & intent
    "intends_to": 21,
    "is_seeking": 7,
    "is_preparing_for": 14,
    "fears": 30,
    "open_to": None,                 # declared availability — no decay
    # 4. Beliefs & values
    "believes": 90,
    "values": 365,
    "recently_changed_stance_on": 30,
    "has_aesthetic": 365,
    # 5. Navigation & constraints
    "is_navigating": 60,
    "is_constrained_by": 45,
    "is_frustrated_by": 45,
    "has_been_wronged": 180,         # 6 months
    "is_resolved": 180,              # system-emitted only
    # 6. Life stage & experience
    "has_age": 180,
    "is_transitioning": 180,
    "is_experiencing": 90,
    "is_processing": 45,
    "is_rediscovering": 365,
    "has_unsolved_problem": None,
    # Historical accomplishments remain true as current interests change.
    "is_founder_of": None,
    "has_experience_in": None,
    # 7. Relationships & responsibilities
    "has_collaborator": None,
    "is_responsible_for": None,
    "is_advocating_for": 180,
    "is_in_conflict_with": 90,
    "is_inspired_by": 180,
    # 8. Place & affiliation
    "is_located_in": None,
    "is_affiliated_with": None,
    "has_language_context": None,
    # 9. Motivation
    "is_motivated_by": 365,
}

ALLOWED_PREDICATES: frozenset[str] = frozenset(PREDICATE_HALFLIFE_DAYS)

# ── Freshness: when is a fact "old"? ───────────────────────────────────────────────
# Predicates that describe a moment rather than a trait. Once a fact of one of these has
# gone this many days without being seen again it is *stale*: it drops out of the default
# (no-topic) context but stays stored and comes back when a topic query matches it.
# Predicates not listed here never go stale. Never archived on age alone.
STALE_AFTER_DAYS: dict[str, int] = {
    "is_working_on": 30,       # D4
    "is_learning": 60,
    "is_seeking": 30,
    "intends_to": 45,
    "is_preparing_for": 30,
    "is_building": 120,
}

# ── One thing, one fact ──────────────────────────────────────────────────────────────
# Predicates whose object is usually a technology name; only these get alias and version
# canonicalization ("JS" -> "JavaScript"). A project called "Next" must not become Next.js.
TECH_NAME_PREDICATES: frozenset[str] = frozenset({
    "has_expertise_in", "has_skill", "uses_tool", "is_learning",
})

_TECH_FAMILY: frozenset[str] = frozenset({"has_expertise_in", "has_skill", "uses_tool"})
_WORK_FAMILY: frozenset[str] = frozenset({"is_building", "is_creating", "is_working_on", "intends_to"})

# Within a family the stronger predicate wins; a weaker report of the same thing only
# refreshes the stronger fact. is_learning ranks lowest in both families it can join.
FAMILY_RANK: dict[str, int] = {
    "has_expertise_in": 4, "has_skill": 3, "uses_tool": 2,
    "is_building": 5, "is_creating": 4, "is_working_on": 3, "intends_to": 2,
    "is_learning": 1,
}


def family_of(predicate: str, *, is_tech: bool = False, is_project: bool = False) -> str | None:
    """The family a (predicate, object) fact belongs to, or None when it stands alone.

    is_learning joins a family only by what it is about: learning a technology is the
    tech family, learning a project the work family. Learning a *field* ("machine
    learning") next to expertise in it is legitimate and stays on its own.
    """
    if predicate in _TECH_FAMILY:
        return "tech"
    if predicate in _WORK_FAMILY:
        return "work"
    if predicate == "is_learning":
        if is_tech:
            return "tech"
        if is_project:
            return "work"
    return None


# Entity types that name the same kind of thing. "JavaScript" can come back from extraction as
# skill_technical, skill_domain or concept_topic; within a user these are one entity.
ENTITY_TYPE_GROUPS: dict[str, tuple[str, ...]] = {
    "tech": ("skill_technical", "skill_domain", "concept_topic"),
    "project": ("project_venture", "project_assignment", "project_side"),
}


def entity_type_group(entity_type: str, *, tech_name: bool = False, work: bool = False) -> tuple[str, ...]:
    """The set of entity types a name may already be stored under."""
    if tech_name and entity_type in ENTITY_TYPE_GROUPS["tech"]:
        return ENTITY_TYPE_GROUPS["tech"]
    if work and entity_type in ENTITY_TYPE_GROUPS["project"]:
        return ENTITY_TYPE_GROUPS["project"]
    return (entity_type,)


# Sources whose sync already DECLARES these facts directly (persona-api github_sync /
# linkedin_scraper / twitter_scraper). The sync also ingests an LLM summary turn under the
# same source_system, and extraction turned that summary into the same facts again, so
# these predicates are dropped from chunks of those sources.
SYNC_SOURCES: frozenset[str] = frozenset({"github", "linkedin", "twitter"})
SYNC_DECLARED_PREDICATES: frozenset[str] = frozenset({
    "has_skill", "uses_tool", "has_expertise_in", "is_working_on", "is_building",
})


# ── What context returns ─────────────────────────────────────────────────────────────
# Always part of the no-topic context packet, as (predicate, max facts of it). Capped to a
# share of k elsewhere so they never crowd out what the person is doing now.
CORE_LIMITS: tuple[tuple[str, int], ...] = (
    ("is_located_in", 1),
    ("is_affiliated_with", 2),
    ("is_building", 3),
    ("has_expertise_in", 3),
)
CORE_PREDICATES: frozenset[str] = frozenset(p for p, _ in CORE_LIMITS)
CORE_MAX_SHARE = 0.4

# Minimum cosine similarity between a topic and a fact's object for the fact to count as
# related. A starting value for text-embedding-3-small on short entity names; tuned by
# tests/fixtures/context_eval.json.
RELATED_MIN = 0.45

# Ranking nudge by kind of fact. Things a person is doing or is rank above things they
# merely hold an opinion on or touched once.
PREDICATE_WEIGHT: dict[str, float] = {
    "is_building": 1.0, "is_creating": 1.0, "is_working_on": 1.0, "is_seeking": 1.0,
    "is_located_in": 1.0, "is_affiliated_with": 1.0, "has_expertise_in": 0.95,
    "open_to": 0.9, "is_learning": 0.9, "intends_to": 0.85, "has_skill": 0.85,
    "uses_tool": 0.8, "is_preparing_for": 0.85,
}
DEFAULT_PREDICATE_WEIGHT = 0.7

# System-emitted (never extracted or declared) + declared-only predicates.
SYSTEM_PREDICATES: frozenset[str] = frozenset({"is_resolved"})
DECLARED_ONLY: frozenset[str] = frozenset({"open_to"})
# What the LLM extractor is allowed to emit (v2 source = inferred|both).
INFERRABLE_PREDICATES: frozenset[str] = ALLOWED_PREDICATES - SYSTEM_PREDICATES - DECLARED_ONLY

# v2 — the ONLY predicates used for matching / public discovery (the "findability card").
# Everything else (beliefs, frustrations, life-stage, etc.) is private memory, never matched.
FINDABILITY_PREDICATES: frozenset[str] = frozenset({
    "is_founder_of", "has_experience_in",
    "is_building", "is_learning", "has_expertise_in",
    "is_seeking", "open_to", "is_affiliated_with", "is_located_in",
    # Public card sections only. Neither is matched on (see MATCHING_PREDICATES).
    "is_working_on", "uses_tool",
})

# The subset that feeds matching embeddings. Card-only sections (current work streams,
# tools used) are shown to people but must not change who matches whom.
MATCHING_PREDICATES: frozenset[str] = FINDABILITY_PREDICATES - {"is_working_on", "uses_tool"}

# Entity subtypes by family (brief §2). Flattened to a validation set.
ENTITY_TYPES: frozenset[str] = frozenset({
    "self", "collaborator", "influence", "adversary",
    "place_physical", "place_institutional", "place_virtual",
    "concept_field", "concept_topic", "concept_idea",
    "project_venture", "project_assignment", "project_side",
    "skill_technical", "skill_cognitive", "skill_domain",
    "belief_opinion", "belief_value", "belief_worldmodel",
    "intent_immediate", "intent_project", "intent_life",
    "artifact_document", "artifact_code", "artifact_creative",
})

# Cluster -> predicates it is built from. v2: every match cluster draws ONLY from
# FINDABILITY_PREDICATES — beliefs, frustrations, and life-stage are never matched on.
CLUSTER_PREDICATES: dict[str, frozenset[str]] = {
    "intent_cluster": frozenset({"is_building", "is_seeking", "open_to"}),
    "skill_cluster": frozenset({"has_expertise_in", "is_learning"}),
    "place_cluster": frozenset({"is_affiliated_with", "is_located_in"}),
    "full_context": MATCHING_PREDICATES,
}

# Reliability weight per source, used in the Bayesian update (brief §5.4).
SOURCE_RELIABILITY: dict[str, float] = {
    "user_confirmed": 1.00,
    "claude": 0.85,
    "chatgpt": 0.80,
    "import": 0.70,
}
DEFAULT_SOURCE_RELIABILITY = 0.70


def decay_fn_for(predicate: str) -> str:
    """Canonical decay_fn string for a predicate. Derived here, not trusted
    from the LLM (brief §14.3: never write LLM output straight to the DB)."""
    halflife = PREDICATE_HALFLIFE_DAYS[predicate]
    return "none" if halflife is None else f"exponential(halflife={halflife}d)"


# Predicate -> second-person sentence template for human display ("what do you know
# about me?"). The graph stores machine predicates; this renders them so the user
# never sees raw keys like "has_expertise_in -> ai".
PREDICATE_PHRASE: dict[str, str] = {
    "is_founder_of": "You founded {obj}",
    "has_experience_in": "Your experience: {obj}",
    "is_building": "You're building {obj}",
    "is_working_on": "You're working on {obj}",
    "is_creating": "You're creating {obj}",
    "wants_to_preserve": "You want to preserve {obj}",
    "is_learning": "You're learning {obj}",
    "has_expertise_in": "You have expertise in {obj}",
    "has_skill": "You're skilled in {obj}",
    "uses_tool": "You use {obj}",
    "intends_to": "You intend to {obj}",
    "is_seeking": "You're looking for {obj}",
    "is_preparing_for": "You're preparing for {obj}",
    "fears": "You're worried about {obj}",
    "open_to": "You're open to {obj}",
    "believes": "You believe {obj}",
    "values": "You value {obj}",
    "recently_changed_stance_on": "You recently rethought your stance on {obj}",
    "has_aesthetic": "Your taste leans toward {obj}",
    "is_navigating": "You're navigating {obj}",
    "is_constrained_by": "You're constrained by {obj}",
    "is_frustrated_by": "You're frustrated by {obj}",
    "has_been_wronged": "You feel wronged over {obj}",
    "is_resolved": "You've resolved {obj}",
    "has_age": "You are {obj} years old",
    "is_transitioning": "You're in transition: {obj}",
    "is_experiencing": "You're experiencing {obj}",
    "is_processing": "You're processing {obj}",
    "is_rediscovering": "You're rediscovering {obj}",
    "has_unsolved_problem": "You have an open problem: {obj}",
    "has_collaborator": "You work with {obj}",
    "is_responsible_for": "You're responsible for {obj}",
    "is_advocating_for": "You're advocating for {obj}",
    "is_in_conflict_with": "You're in conflict with {obj}",
    "is_inspired_by": "You're inspired by {obj}",
    "is_located_in": "You're based in {obj}",
    "is_affiliated_with": "You're affiliated with {obj}",
    "has_language_context": "You operate in {obj}",
    "is_motivated_by": "You're motivated by {obj}",
}


def humanize(predicate: str, object_name: str | None) -> str:
    """Render a (predicate, object) fact as a natural second-person statement for
    display. Falls back to a readable form for any predicate without a template, so a
    newly-added predicate never surfaces as a raw key."""
    obj = (object_name or "").strip()
    template = PREDICATE_PHRASE.get(predicate)
    if template:
        return template.format(obj=obj).strip() if obj else template.split(" {obj}")[0].strip()
    readable = predicate.replace("_", " ")
    return (f"You {readable} {obj}" if obj else f"You {readable}").strip()
