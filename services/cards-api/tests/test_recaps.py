from copy import deepcopy
from datetime import date, datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import config
from api import recaps as routes
from scraping import github
from services import recaps
from tests.fake_supabase import FakeSupabase

NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
EMAIL = "alice@example.com"
ROW = {"id": "card-a", "handle": "alice", "owner_email": EMAIL, "status": "published", "timezone": "Asia/Kolkata",
       "card": {"identity": {"name": "Alice", "links": {"github": "https://github.com/alice"}},
                "projects": [{"name": "Undated project", "url": "https://example.com"}],
                "working_on": ["Undated work"], "skills": [{"name": "Vue"}],
                "exploring": [{"title": "Vue", "url": "https://vuejs.org/", "added_at": "2026-10-10T09:00:00Z"},
                              {"title": "Old", "url": "https://old.example.com/", "added_at": "2026-09-01T00:00:00Z"}]}}


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase(agent_profile_cards=[deepcopy(ROW)])
    monkeypatch.setattr(config, "get_supabase", lambda: fake)
    monkeypatch.setattr(recaps, "current_card", lambda email: next((r for r in fake.rows("agent_profile_cards") if r["owner_email"] == email), None))
    async def contributions(*args):
        return 34
    monkeypatch.setattr(recaps, "fetch_period_contributions", contributions)
    return fake


def test_calendar_boundaries_and_quarter_rollover():
    start, end, label = recaps.period_bounds("2026-Q4", ZoneInfo("Asia/Kolkata"), NOW)
    assert label == "Q4 2026"
    assert start.isoformat() == "2026-10-01T00:00:00+05:30"
    assert end.isoformat() == "2027-01-01T00:00:00+05:30"
    assert recaps.previous_periods(datetime(2027, 1, 1, tzinfo=timezone.utc), ZoneInfo("UTC")) == ["2026-12", "2026-Q4"]
    assert recaps.previous_periods(datetime(2026, 9, 30, 20, tzinfo=timezone.utc), ZoneInfo("Asia/Kolkata")) == ["2026-09", "2026-Q3"]
    leap_start, leap_end, _ = recaps.period_bounds("2024-02", ZoneInfo("UTC"), NOW)
    assert (leap_end - leap_start).days == 29
    for period in ["2026-13", "2026-Q0", "2027-01", "0000-01", "2026-1"]:
        with pytest.raises(HTTPException):
            recaps.period_bounds(period, ZoneInfo("UTC"), NOW)


@pytest.mark.asyncio
async def test_only_dated_evidence_and_exact_period_counts(db):
    for day in [date(2026, 10, 2), date(2026, 10, 3)]:
        recaps.add_milestone(EMAIL, "shipped", "Launch", "https://example.com/launch", day)
    recaps.add_milestone(EMAIL, "learned", "Vue basics", "", date(2026, 9, 20))
    result = await recaps.generate(EMAIL, "2026-10", now=NOW)
    highlights = result["snapshot"]["highlights"]
    assert [h["kind"] for h in highlights].count("shipped") == 1
    assert any(h["kind"] == "exploring" and h["title"] == "Vue" for h in highlights)
    assert not any(h["kind"] == "learned" for h in highlights)
    assert not any("Undated" in h["title"] for h in highlights)
    assert highlights[-1]["count"] == 34
    assert result["snapshot"]["in_progress"] is True
    assert "owner_email" not in result
    with pytest.raises(HTTPException) as exc:
        recaps.public(result["id"], "alice")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_unknown_github_is_omitted_and_zero_is_preserved(db, monkeypatch):
    async def unknown(*args): return None
    monkeypatch.setattr(recaps, "fetch_period_contributions", unknown)
    db.rows("agent_profile_cards")[0]["card"]["exploring"] = []
    result = await recaps.generate(EMAIL, "2026-09", now=NOW)
    assert result["snapshot"]["github_available"] is False
    assert result["snapshot"]["highlights"] == []
    async def zero(*args): return 0
    monkeypatch.setattr(recaps, "fetch_period_contributions", zero)
    refreshed = await recaps.generate(EMAIL, "2026-09", refresh=True, now=NOW)
    assert refreshed["snapshot"]["highlights"][0]["count"] == 0


@pytest.mark.asyncio
async def test_publish_filters_hidden_facts_and_requires_current_ownership(db):
    result = await recaps.generate(EMAIL, "2026-10", now=NOW)
    with pytest.raises(HTTPException):
        recaps.update(EMAIL, result["id"], ["invented"], "hello", True)
    with pytest.raises(HTTPException):
        recaps.update(EMAIL, result["id"], [], "hello", True)
    with pytest.raises(HTTPException) as exc:
        recaps.owned("mallory@example.com", result["id"])
    assert exc.value.status_code == 404
    published = recaps.update(EMAIL, result["id"], ["github"], "My month", True)
    public = recaps.public(result["id"], "alice")
    assert public["snapshot"]["highlights"] == [result["snapshot"]["highlights"][-1]]
    assert "Vue" not in str(public)
    assert "owner_email" not in public and "selected_ids" not in public
    assert public["published_at"] == published["published_at"]
    with pytest.raises(HTTPException):
        recaps.public(result["id"], "bob")
    db.rows("agent_profile_cards")[0]["status"] = "draft"
    with pytest.raises(HTTPException):
        recaps.public(result["id"], "alice")
    db.rows("agent_profile_cards")[0]["status"] = "published"
    db.rows("agent_profile_cards")[0]["owner_email"] = "new@example.com"
    with pytest.raises(HTTPException):
        recaps.public(result["id"], "alice")
    with pytest.raises(HTTPException):
        recaps.owned(EMAIL, result["id"])


@pytest.mark.asyncio
async def test_published_snapshot_is_frozen_then_can_be_unpublished(db):
    original = await recaps.generate(EMAIL, "2026-10", now=NOW)
    recaps.update(EMAIL, original["id"], original["selected_ids"], original["caption"], True)
    recaps.add_milestone(EMAIL, "shipped", "Later launch", "", date(2026, 10, 20))
    next_recap = await recaps.generate(EMAIL, "2026-10", refresh=True, now=NOW)
    assert next_recap["snapshot"] == original["snapshot"]
    with pytest.raises(HTTPException) as exc:
        recaps.update(EMAIL, original["id"], ["github"], "Changed", True)
    assert exc.value.status_code == 409
    recaps.unpublish(EMAIL, original["id"])
    with pytest.raises(HTTPException):
        recaps.public(original["id"], "alice")
    refreshed = await recaps.generate(EMAIL, "2026-10", refresh=True, now=NOW)
    assert any(h["title"] == "Later launch" for h in refreshed["snapshot"]["highlights"])
    assert len(db.rows("card_recaps")) == 1


@pytest.mark.asyncio
async def test_hiding_a_highlight_updates_generated_caption_and_legacy_email_case(db):
    result = await recaps.generate(EMAIL, "2026-10", now=NOW)
    assert "Explored Vue" in result["caption"]
    db.rows("agent_profile_cards")[0]["owner_email"] = EMAIL.upper()
    saved = recaps.update(EMAIL, result["id"], ["github"], result["caption"], True)
    assert "Vue" not in saved["caption"]
    assert "Vue" not in str(recaps.public(result["id"], "alice"))


@pytest.mark.asyncio
async def test_schedule_is_retryable_and_dry_run_does_not_write(db):
    assert (await recaps.run_scheduled(NOW, dry_run=True))["generated"] == 2
    assert db.rows("card_recaps") == []
    first = await recaps.run_scheduled(NOW)
    second = await recaps.run_scheduled(NOW)
    assert first["generated"] == 2 and first["failed"] == 0
    assert second["existing"] == 2
    assert len(db.rows("card_recaps")) == 2
    assert len(db.rows("card_nudges")) == 2


def test_milestone_rejects_unsafe_links_and_future_dates(db):
    with pytest.raises(HTTPException): recaps.add_milestone(EMAIL, "shipped", "Thing", "http://localhost/private", date(2026, 1, 1))
    with pytest.raises(HTTPException): recaps.add_milestone(EMAIL, "shipped", "Thing", "", date(2099, 1, 1))
    with pytest.raises(HTTPException): recaps.add_milestone(EMAIL, "shipped", "   ", "", date(2026, 1, 1))


@pytest.mark.asyncio
async def test_github_uses_exact_range_and_handles_partial_errors(monkeypatch):
    monkeypatch.setattr(config, "GITHUB_TOKEN", "test-only")
    captured = []
    def handler(request):
        import json
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"data": {"user": {"contributionsCollection": {"contributionCalendar": {"totalContributions": 34}}}}})
    original_client = httpx.AsyncClient
    monkeypatch.setattr(github.httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    end = datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert await github.fetch_period_contributions("alice", start, end) == 34
    assert captured[0]["variables"] == {"login": "alice", "from": start.isoformat(), "to": "2026-09-30T23:59:59+00:00"}
    monkeypatch.setattr(github.httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"errors": [{"message": "rate limited"}]})), **kwargs))
    assert await github.fetch_period_contributions("alice", start, end) is None


def test_routes_require_existing_session_and_validate_input(db, monkeypatch):
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)
    monkeypatch.setattr(routes, "_principal", lambda auth: (_ for _ in ()).throw(HTTPException(401, "Unauthorized")))
    assert client.get("/mine/recaps").status_code == 401
    monkeypatch.setattr(routes, "_principal", lambda auth: SimpleNamespace(email=EMAIL))
    assert client.post("/mine/milestones", json={"kind": "mastered", "title": "Vue", "occurred_on": "2026-10-01"}).status_code == 422
    assert client.post("/mine/recaps", json={"period": "2026-13"}).status_code == 422
