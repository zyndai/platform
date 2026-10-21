"""Read an owner-exported JSON file and propose corrections. Never writes to a service.

Usage: python scripts/audit_profile_facts.py /path/to/context-export.json
Accepts get_my_context packets (facts) and portable exports (assertions).
Review the proposals with the owner before using the existing correction/review UI.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.quality import PLACEHOLDER_TOKENS, TOPIC_PREDICATES, historical_learning, is_atomic_topic


def proposals(data: dict) -> list[dict]:
    result = []
    for fact in data.get("facts", data.get("assertions", [])):
        predicate = fact.get("predicate", "")
        value = fact.get("object", "")
        if not isinstance(value, str):
            continue
        historical = historical_learning(value) if predicate == "is_learning" else None
        if historical:
            result.append({"original": fact, "suggested": {"predicate": historical[0], "object": historical[1], "half_life_days": None}, "requires_owner_review": True})
        elif value.strip().casefold() in PLACEHOLDER_TOKENS or (predicate in TOPIC_PREDICATES and not is_atomic_topic(value)):
            result.append({"original": fact, "suggested": "Review and correct or forget this invalid topic", "requires_owner_review": True})
    return result


if __name__ == "__main__":
    print(json.dumps({"dry_run": True, "proposals": proposals(json.loads(Path(sys.argv[1]).read_text()))}, indent=2))
