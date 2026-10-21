"""Audit regressions use synthetic profiles and never call live services."""
import asyncio
from datetime import date
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest
from fastapi import HTTPException

from api import onboard
from models.card import AgentProfileCard, CardSynthesis
from services import cards, owner_home, search
from services.card_view import build_card_view
from services.jobs import create_job, get_job
from services.profile_dates import experience_years
from services import beacons


def test_topics_are_clean_across_card_and_view():
    card = AgentProfileCard(id="test", skills=[{"name": "general"}, {"name": "Python"}, {"name": "python"},
        {"name": "I founded a company. We built a community for thousands of people."}],
        can_help_with=["misc", "Developer Relations"], zynd_memory=[
            {"predicate": "has_expertise_in", "object": "general"},
            {"predicate": "is_learning", "object": "Founder of Example, a large developer community"},
            {"predicate": "has_expertise_in", "object": "Next.js"}])
    assert [s.name for s in card.skills] == ["Python"]
    view = build_card_view(card, claimed=True)
    assert view.can_help_with == ["Next.js", "Developer Relations"]
    assert [f.text for f in view.facts] == ["Next.js"]


def test_experience_counts_concurrent_jobs_once_and_ignores_unknown_dates():
    jobs = [{"start_date": "Jan 2020", "end_date": "Dec 2022"},
            {"start_date": "Jan 2021", "end_date": "Present"},
            {"start_date": "unknown", "end_date": "Present"}]
    assert experience_years(jobs, date(2026, 1, 1)) == 6
    assert experience_years([{"start_date": "2020"}]) is None
    assert experience_years([{"start_date": "2030", "end_date": "2020"}]) is None


def test_search_enforces_language_and_location_before_limit(monkeypatch):
    def row(handle, location, skill):
        return {"handle": handle, "owner_email": "owner@example.test", "embedding": [1, 0], "card":
                AgentProfileCard(id=handle, identity={"name": handle, "headline": "Engineer", "location": location},
                    skills=[{"name": skill}]).model_dump()}
    rows = [row("wrong-city", "Ghaziabad", "Rust"), row("wrong-skill", "Bangalore", "Python")]
    rows += [row(f"noise-{i}", "Delhi", "Python") for i in range(205)]
    rows += [row("right", "Bengaluru, India", "Rust")]
    monkeypatch.setattr(cards, "list_published_rows", lambda **kw: rows)
    monkeypatch.setattr(search, "embed_text", lambda q: [1, 0])
    monkeypatch.setattr(search, "_candidates", lambda *a: (_ for _ in ()).throw(AssertionError("must not limit before filtering")))
    results = search.search_agents("who knows Rust in Bangalore", limit=1)
    assert [r["handle"] for r in results] == ["right"]
    assert search.search_agents("who knows Go in Bangalore") == []


def test_social_aliases_are_candidates_not_merge_authority(monkeypatch):
    row = {"id": "a", "card": {"identity": {"links": {"github": "https://www.github.com/Alice/?tab=repositories", "x": "https://twitter.com/Alice"}}}}
    other = {"id": "b", "handle": "alice-duplicate", "owner_email": "different@example.test", "card":
             {"identity": {"name": "Alice", "links": {"github": "http://github.com/alice", "x": "https://x.com/alice/"}}}}
    monkeypatch.setattr(cards, "list_published_rows", lambda **kw: [other])
    result = owner_home.possible_duplicates("alice@example.test", row)
    assert result[0]["matched_socials"] == ["github.com/alice", "x.com/alice"]
    assert result[0]["mergeable"] is False
    assert "owner_email" not in result[0]


def test_inaccessible_source_warns_while_other_source_survives(monkeypatch):
    async def fake(url):
        return ("linkedin", "", None) if "linkedin" in url else ("website", "A real public profile", None)
    monkeypatch.setattr(onboard, "_safe_fetch_url", fake)
    monkeypatch.setattr(onboard, "synthesize_card", lambda *a, **kw: CardSynthesis(identity={"name": "Alice"}))
    job_id = create_job()
    asyncio.run(onboard._run_pipeline(job_id, ["https://linkedin.com/in/private", "https://example.test"], None))
    job = get_job(job_id)
    assert job.status == "ready"
    assert job.url_warnings[0]["code"] == "inaccessible"


def test_pipeline_deadline_produces_terminal_error(monkeypatch):
    async def slow(*a):
        await asyncio.sleep(10)
    monkeypatch.setattr(onboard, "_build_pipeline", slow)
    monkeypatch.setattr(onboard, "PIPELINE_TIMEOUT_SECONDS", 0.01)
    job_id = create_job()
    asyncio.run(onboard._run_pipeline(job_id, ["https://example.test"], None))
    assert get_job(job_id).status == "error"
    assert "too long" in get_job(job_id).error


def test_beacon_expiry_is_exact_and_never_stored_in_durable_embeddings():
    from services.embed import card_search_text
    now = datetime.now(timezone.utc)
    card = AgentProfileCard(id="beacon", beacon={"text": "Looking for unobtainium", "created_at": now - timedelta(days=7), "expires_at": now})
    assert beacons.active_beacon(card, now) is None
    assert build_card_view(card, claimed=True).beacon is None
    card.beacon.created_at = now - timedelta(days=6)
    card.beacon.expires_at = now + timedelta(seconds=30)
    assert "unobtainium" not in card_search_text(card)
    view = build_card_view(card, claimed=True)
    assert view.beacon.text == "Looking for unobtainium"
    assert view.facts[-1].type == "broadcast_beacon"


def test_beacon_compare_and_swap_preserves_concurrent_edits(monkeypatch):
    import config
    sb, q = MagicMock(), MagicMock()
    sb.table.return_value = q
    for name in ("select", "eq", "ilike", "neq", "limit", "update"):
        getattr(q, name).return_value = q
    q.execute.side_effect = [MagicMock(data=[{"id": "a", "card": {"summary": "existing biography"}, "updated_at": "previous-version"}]), MagicMock(data=[])]
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    with pytest.raises(HTTPException) as error:
        beacons.save_beacon("alice", "alice@example.test", "Looking for reviewers")
    assert error.value.status_code == 409
    assert ("updated_at", "previous-version") in [call.args for call in q.eq.call_args_list]
    assert q.update.call_args.args[0]["card"]["summary"] == "existing biography"


def test_beacon_write_uses_existing_owner_authority(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api import owner_home as routes
    from types import SimpleNamespace
    import config
    monkeypatch.setattr(config, "FEATURE_S10_HOME", True)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    monkeypatch.setattr(routes, "_principal", lambda auth: SimpleNamespace(email="alice@example.test") if auth == "Bearer owner" else (_ for _ in ()).throw(HTTPException(401, "Unauthorized")))
    save = MagicMock(return_value=None)
    monkeypatch.setattr(beacons, "save_beacon", save)
    monkeypatch.setattr(routes, "ping_revalidate", lambda *a: None)
    app = FastAPI()
    app.include_router(routes.router, prefix="/cards")
    with TestClient(app) as client:
        assert client.put("/cards/by-handle/alice/beacon", json={"text": "Hello"}).status_code == 401
        save.assert_not_called()
        assert client.put("/cards/by-handle/alice/beacon", json={"text": " "}, headers={"Authorization": "Bearer owner"}).status_code == 422
        assert client.put("/cards/by-handle/alice/beacon", json={"text": "Looking for reviewers", "email": "spoof@example.test"}, headers={"Authorization": "Bearer owner"}).status_code == 200
    save.assert_called_once_with("alice", "alice@example.test", "Looking for reviewers")


def test_skill_proof_and_demo_come_from_real_repository_metadata():
    from services.skill_evidence import attach_evidence
    synth = CardSynthesis(skills=[{"name": "Python"}, {"name": "Rust"}], projects=[{"name": "example", "url": "https://github.com/alice/example"}])
    attach_evidence(synth, {"repos": [{"full_name": "alice/example", "html_url": "https://github.com/alice/example", "language": "Python", "homepage": "https://example.test", "stargazers_count": 12}]})
    assert synth.skills[0].evidence[0].url == "https://github.com/alice/example"
    assert synth.skills[1].evidence == []
    assert synth.projects[0].demo_url == "https://example.test"
    assert synth.projects[0].stars == 12


def test_long_post_snippets_indicate_truncation():
    original = "A complete post " * 80
    snippet = cards.clean_excerpt(original)
    assert len(snippet) <= 500 and snippet.endswith("…")
    assert cards.clean_excerpt(snippet) == snippet
