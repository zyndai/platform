"""What find_people sends to Cards, pinned against the cases Cards' scorer is tested on.

tests/fixtures/people_golden.json is shared with services/cards-api/tests/test_search_golden.py,
which runs these exact parameters through the Cards scorer over its golden corpus. Together they
test the whole path memory -> Cards that used to be tested only in halves: Cards' golden set used
hand-written filters, so memory sending topics as required skills shipped unnoticed.
"""
import json
import pathlib

import pytest

from app.services import people_discovery as discovery
from app.services.people_query import detect_intent, parse_target_heuristic

CASES = json.loads((pathlib.Path(__file__).parent / "fixtures" / "people_golden.json").read_text())["cases"]


@pytest.fixture(autouse=True)
def v2(monkeypatch):
    monkeypatch.setattr(discovery.settings, "feature_people_search_v2", True)


@pytest.mark.parametrize("case", CASES, ids=[c["target"] for c in CASES])
def test_memory_sends_cards_the_recorded_parameters(case):
    intent = detect_intent(case["target"])
    assert (intent.kind, intent.name, intent.company) == (case["intent"], case["name"], case["company"])
    params = discovery.cards_search_params(case["target"], 10, parse_target_heuristic(case["target"]))
    assert params == case["params"]


def test_no_case_sends_a_guess_as_a_required_skill():
    for case in CASES:
        skills = case["params"].get("skills", "")
        assert skills == "" or skills in {"rust"}, case["target"]    # only an explicit "knows Rust"


def test_every_case_relaxes_so_a_strict_filter_never_empties_the_answer():
    assert all(case["params"]["relax"] == "true" for case in CASES)
