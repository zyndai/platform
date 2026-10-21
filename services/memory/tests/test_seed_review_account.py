"""The review-account seed: sample facts must satisfy the plugin tools; guards fail before any write."""
import argparse
import importlib.util
from pathlib import Path

import pytest

from app.config import settings
from app.services.findability import DECLARE_ENTITY_TYPE, ENUM_VALUES, PRIVATE_DECLARE_ENTITY_TYPE, _APPROVE_AS
from app.services.quality import public_label_for
from app.taxonomy import FINDABILITY_PREDICATES

_spec = importlib.util.spec_from_file_location(
    "seed_review_account", Path(__file__).resolve().parents[1] / "scripts" / "seed_review_account.py")
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)


@pytest.mark.parametrize("predicate,name", seed.PENDING_POOL)
def test_pending_facts_can_be_proposed_for_the_card(predicate, name):
    mapped = _APPROVE_AS.get(predicate, predicate)
    assert predicate in PRIVATE_DECLARE_ENTITY_TYPE
    assert mapped in FINDABILITY_PREDICATES and mapped in DECLARE_ENTITY_TYPE
    assert public_label_for(mapped, name)


@pytest.mark.parametrize("predicate,name", seed.PUBLIC_POOL)
def test_public_facts_are_declarable_without_enum_values(predicate, name):
    assert predicate in DECLARE_ENTITY_TYPE and predicate not in ENUM_VALUES
    assert name.strip()


def test_pools_do_not_collide():
    pending = [(p, n.lower()) for p, n in seed.PENDING_POOL]
    public = [(p, n.lower()) for p, n in seed.PUBLIC_POOL]
    assert len(set(pending)) == len(pending) and len(set(public)) == len(public)
    # declare() on a name that is already private would publish it instead of adding a new fact.
    assert {n for _, n in pending}.isdisjoint({n for _, n in public})
    assert len(seed.PENDING_POOL) > seed.MIN_PENDING and len(seed.PUBLIC_POOL) >= seed.MIN_PUBLIC


def test_recall_fact_matches_the_review_prompt():
    assert "current project" in seed.RECALL_FACT.lower()
    assert max(map(len, (seed.RECALL_FACT, seed.HISTORY_SAVED, seed.HISTORY_REJECTED))) <= 2000


def test_plan_adds_only_what_is_missing():
    private, public = seed.plan_facts(set(), 0, 0)
    assert len(private) == seed.MIN_PENDING and len(public) == seed.MIN_PUBLIC

    first = seed.PENDING_POOL[0]
    present = {(first[0], first[1].lower())}
    private, _ = seed.plan_facts(present, 1, 0)
    assert len(private) == seed.MIN_PENDING - 1 and first not in private

    assert seed.plan_facts(set(), seed.MIN_PENDING, seed.MIN_PUBLIC) == ([], [])


def test_plan_reports_a_short_list_when_the_pool_is_used_up():
    everything = {(p, n.lower()) for p, n in seed.PENDING_POOL + seed.PUBLIC_POOL}
    assert seed.plan_facts(everything, 1, 0) == ([], [])


async def test_refuses_an_email_the_server_does_not_restrict(monkeypatch):
    monkeypatch.setattr(settings, "plugin_review_emails", "someone-else@example.test")
    monkeypatch.setenv("REVIEW_ACCOUNT_EMAIL", "openai-review@example.test")
    monkeypatch.setenv("REVIEW_ACCOUNT_PASSWORD", "x" * 40)
    args = argparse.Namespace(apply=True, reset=False, supabase_url="")
    assert await seed.run(args) == 2


async def test_refuses_a_short_password_when_applying(monkeypatch):
    monkeypatch.setattr(settings, "plugin_review_emails", "openai-review@example.test")
    monkeypatch.setenv("REVIEW_ACCOUNT_EMAIL", "openai-review@example.test")
    monkeypatch.setenv("REVIEW_ACCOUNT_PASSWORD", "short")
    args = argparse.Namespace(apply=True, reset=False, supabase_url="")
    assert await seed.run(args) == 2
