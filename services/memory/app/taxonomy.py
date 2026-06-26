"""Single source of truth for predicates, decay, entity types, and clusters.

Brief §14.8: a new predicate requires a migration + prompt update + decay_fn.
Adding one here (and to the extraction prompt) is that change in one place.
"""

# Predicate -> decay half-life in days. None = no decay. (Brief §4.)
PREDICATE_HALFLIFE_DAYS: dict[str, int | None] = {
    "is_learning": 30,
    "has_expertise_in": 540,        # 18 months
    "is_building": 60,
    "is_working_on": 14,
    "intends_to": 21,
    "believes": 90,
    "values": 365,
    "is_located_in": None,
    "is_affiliated_with": None,
    "is_frustrated_by": 45,
    "is_inspired_by": 180,           # 6 months
    "has_skill": 730,                # 2 years
    "recently_changed_stance_on": 30,
    "is_seeking": 7,
    "has_collaborator": None,
}

ALLOWED_PREDICATES: frozenset[str] = frozenset(PREDICATE_HALFLIFE_DAYS)

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

# Cluster -> predicates it is built from (brief §10.1). Used in M5 matching.
CLUSTER_PREDICATES: dict[str, frozenset[str]] = {
    "intent_cluster": frozenset({"is_building", "is_working_on", "intends_to", "is_seeking"}),
    "belief_cluster": frozenset({"believes", "values", "recently_changed_stance_on"}),
    "skill_cluster": frozenset({"has_skill", "has_expertise_in", "is_learning"}),
    "concept_cluster": frozenset({"is_frustrated_by", "is_inspired_by", "is_affiliated_with"}),
    "full_context": ALLOWED_PREDICATES,
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
