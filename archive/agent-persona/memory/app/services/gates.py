"""v2 sensitive gates: a pre-LLM scan for health / politics / immigration signals.

When a gate trips, the predicates it guards are withheld from auto-extraction — ZYND
never silently stores sensitive inferences. The user can still declare such things
explicitly via the findability card. Signal lists are from the v2 predicate reference.
"""
GATE_SIGNALS: dict[str, frozenset[str]] = {
    "health": frozenset({
        "doctor", "hospital", "diagnosis", "medication", "therapy", "symptoms", "condition",
        "surgery", "mental health", "anxiety", "depression", "postpartum", "grief", "burnout",
        "cancer", "chronic", "disability", "treatment"}),
    "politics": frozenset({
        "vote", "party", "politician", "election", "protest", "activist", "government",
        "policy", "referendum", "ballot"}),
    "immigration": frozenset({
        "visa", "asylum", "undocumented", "citizenship", "deportation", "refugee",
        "green card", "immigration", "border", "work permit"}),
}

# Gate guarding each predicate (v2 reference "Gate" column). Absent = ungated.
# "health/imm" = withheld if either a health OR immigration gate trips.
PREDICATE_GATE: dict[str, str] = {
    "believes": "politics",
    "is_located_in": "immigration",
    "is_navigating": "health/imm",
    "is_transitioning": "health",
    "is_experiencing": "health",
    "is_processing": "health",
}


def detect_gates(text: str) -> set[str]:
    """Return the gates ('health','politics','immigration') the text trips."""
    lower = (text or "").lower()
    return {gate for gate, signals in GATE_SIGNALS.items() if any(s in lower for s in signals)}


def is_gated(predicate: str, tripped: set[str]) -> bool:
    """True if `predicate` must be withheld from auto-extraction given the tripped gates."""
    gate = PREDICATE_GATE.get(predicate)
    if gate is None:
        return False
    if gate == "health/imm":
        return bool(tripped & {"health", "immigration"})
    return gate in tripped
