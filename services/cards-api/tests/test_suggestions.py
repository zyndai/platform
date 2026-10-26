"""People search Phase 2: suggestions are searches on the owner's behalf (services/suggestions.py)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import config
from models.card import AgentProfileCard
from services import network, suggested_people, suggestions
from services import search as search_service
from tests.fake_supabase import FakeSupabase

NOW = datetime.now(timezone.utc)
ME = "00000000-0000-0000-0000-000000000001"


def uid(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


def row(n, handle, headline, *, claimed=True, location="", company="", **fields):
    work = [{"title": headline, "company": company}] if company else None
    card = AgentProfileCard(id=f"c-{handle}", status="published", handle=handle,
                            identity={"name": handle.title(), "headline": headline, "location": location,
                                      "avatar_url": f"https://img/{handle}", "links": {}},
                            work_experience=work, **fields)
    return {"id": f"c-{handle}", "handle": handle, "status": "published", "owner_user_id": uid(n) if claimed else None,
            "owner_email": f"{handle}@example.com" if claimed else None, "unsubscribe_token": f"0000000{n}-0000-4000-8000-000000000000",
            "card": card.model_dump(mode="json")}


def base_rows():
    return [
        row(1, "me", "Founder building AI agents", location="Pune, India",
            connect_with=["Investors"], working_on=["Building with AI"]),
        row(2, "ann", "Seed investor in AI", connect_with=["Founders"]),          # wants to meet founders: two-way
        row(3, "ivy", "Angel investor", location="Pune, India"),
        row(4, "fred", "Founder of a fintech", connect_with=["Investors"]),        # wants what I want: not for me
        row(5, "dev", "Backend engineer"),
    ]


@pytest.fixture
def world(monkeypatch):
    sb = FakeSupabase(agent_profile_cards=base_rows())
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    monkeypatch.setattr(network, "_sb", lambda: sb)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    monkeypatch.setattr(config, "FEATURE_NETWORK_CONTROLS", False)
    monkeypatch.setattr(config, "MEMORY_SERVICE_TOKEN", "")              # no outside search
    monkeypatch.setattr(search_service, "embed_text", lambda q: [])       # no embedding service in tests
    return sb


def me(sb):
    return next(r for r in sb.rows("agent_profile_cards") if r["handle"] == "me")


def add(sb, *rows):
    for r in rows:
        sb.new_row("agent_profile_cards", r)


def handles(people):
    return [p["handle"] for p in people]


# ── who: complementary, not lookalikes ─────────────────────────────────────────────────

def test_a_founder_who_wants_investors_gets_investors_not_other_founders(world):
    people = suggestions.compute(me(world))
    assert set(handles(people)) == {"ann", "ivy"}
    assert "fred" not in handles(people)               # wants the same thing as me; that is not a reason to meet


def test_people_who_want_to_meet_someone_like_the_owner_come_first(world):
    ann, ivy = suggestions.compute(me(world))
    assert ann["handle"] == "ann" and ann["two_way"] is True and ann["two_way_kinds"] == ["Founders"]
    assert ivy["two_way"] is False
    assert ann["why"][0] == "Wants to meet founders like you"
    assert ann["target"] == "Investor · AI"


def test_reasons_are_specific(world):
    (ann, ivy) = suggestions.compute(me(world))
    for p in (ann, ivy):
        assert p["why"] and len(p["why"]) <= suggestions.MAX_WHY
        assert not set(p["why"]) & set(suggestions._GENERIC_REASONS)
    assert "Angel investor" in ivy["why"]                      # the headline that made them an investor


def test_nearby_people_rank_a_little_higher(world):
    ivy = next(p for p in suggestions.compute(me(world)) if p["handle"] == "ivy")
    plain = search_service.search_agents(role="investor", topics="AI", relax=True, keep_role=True)
    raw = next(r for r in plain if r["handle"] == "ivy")["match_score"]
    assert ivy["score"] == pytest.approx(min(raw * suggestions.NEAR_CITY, 1.0), abs=0.001)


def test_a_card_with_only_free_text_still_gets_suggestions(world):
    add(world, row(9, "kim", "Designer", connect_with=["climate fund partners"]),
        row(10, "cli", "Partner at a climate fund"))
    kim = next(r for r in world.rows("agent_profile_cards") if r["handle"] == "kim")
    assert "cli" in handles(suggestions.compute(kim))


def test_unclaimed_owner_or_nothing_to_search_with_gets_nobody(world):
    add(world, row(11, "ghost", "Investor", claimed=False, connect_with=["Founders"]), row(12, "blank", ""))
    rows = {r["handle"]: r for r in world.rows("agent_profile_cards")}
    assert suggestions.compute(rows["ghost"]) == []
    assert suggestions.compute(rows["blank"]) == []


# ── who can't be suggested ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["pending", "accepted", "declined", "blocked", "revoked"])
@pytest.mark.parametrize("i_asked", [True, False])
def test_anyone_with_a_connection_row_is_never_suggested(world, status, i_asked):
    a, b = (ME, uid(2)) if i_asked else (uid(2), ME)
    ac, bc = ("c-me", "c-ann") if i_asked else ("c-ann", "c-me")
    world.new_row("connections", {"connection_key": "k", "requester_user_id": a, "requester_card_id": ac,
                                  "recipient_user_id": b, "recipient_card_id": bc, "status": status})
    assert handles(suggestions.compute(me(world))) == ["ivy"]


def test_unclaimed_reported_hidden_and_dismissed_people_are_never_suggested(world, monkeypatch):
    add(world, row(20, "unc", "Investor", claimed=False), row(21, "rep", "Investor"),
        row(22, "hid", "Investor"), row(23, "nope", "Investor"))
    world.new_row("card_reports", {"reporter_user_id": ME, "target_card_id": "c-rep", "reason": "spam"})
    world.new_row("card_suggestion_impressions", {"card_id": "c-me", "candidate_card_id": "c-nope",
                                                  "surface": "digest", "action": "not_relevant"})
    monkeypatch.setattr(config, "FEATURE_NETWORK_CONTROLS", True)
    world.new_row("match_preferences", {"user_id": ME, "kind": "hide_person", "value": "hid"})
    assert set(handles(suggestions.compute(me(world)))) == {"ann", "ivy"}


def test_less_like_this_ranks_similar_people_down(world, monkeypatch):
    add(world, row(24, "sim", "Seed investor in AI", skills=[{"name": "Fundraising"}]),
        row(25, "dis", "Seed investor in AI", skills=[{"name": "Fundraising"}]))
    monkeypatch.setattr(config, "FEATURE_NETWORK_CONTROLS", True)
    before = {p["handle"]: p["score"] for p in suggestions.compute(me(world))}
    world.new_row("match_preferences", {"user_id": ME, "kind": "less_like_this", "value": "dis"})
    after = {p["handle"]: p["score"] for p in suggestions.compute(me(world))}
    assert after["sim"] < before["sim"]


# ── what each surface shows ─────────────────────────────────────────────────────────────

def test_at_most_one_person_per_company_and_two_per_target(world):
    add(world, row(30, "a1", "Investor", company="Acme Ventures"), row(31, "a2", "Investor", company="Acme Ventures"),
        row(32, "b1", "Investor", company="Beta Capital"))
    people = suggestions.for_owner_row(me(world), "owner_home", k=10)["people"]
    assert len(people) == suggestions.MAX_PER_TARGET
    companies = [p["company"] for p in people if p["company"]]
    assert len(companies) == len(set(companies))


def test_digest_skips_people_it_emailed_in_the_last_two_weeks(world):
    ann = next(p for p in suggestions.compute(me(world)) if p["handle"] == "ann")
    world.new_row("card_suggestion_impressions", {"card_id": "c-me", "candidate_card_id": "c-ann", "surface": "digest",
                                                  "score": ann["score"], "shown_at": (NOW - timedelta(days=3)).isoformat()})
    assert handles(suggestions.for_owner_row(me(world), "digest", k=2)["people"]) == ["ivy"]
    # Owner home is not cooled down: it would change on every page load.
    assert "ann" in handles(suggestions.for_owner_row(me(world), "owner_home", k=2)["people"])


def test_digest_shows_someone_again_after_the_cooldown_or_when_they_match_much_better(world):
    ann = next(p for p in suggestions.compute(me(world)) if p["handle"] == "ann")
    old = world.new_row("card_suggestion_impressions", {
        "card_id": "c-me", "candidate_card_id": "c-ann", "surface": "digest", "score": ann["score"],
        "shown_at": (NOW - timedelta(days=suggestions.COOLDOWN_DAYS + 1)).isoformat()})
    assert "ann" in handles(suggestions.for_owner_row(me(world), "digest", k=2)["people"])
    old.update({"shown_at": (NOW - timedelta(days=1)).isoformat(), "score": ann["score"] - suggestions.RESHOW_GAIN - 0.01})
    assert "ann" in handles(suggestions.for_owner_row(me(world), "digest", k=2)["people"])


def test_digest_rotates_people_day_to_day(world):
    add(world, *[row(40 + i, f"inv{i}", "Seed investor in AI") for i in range(6)])
    seen_days = []
    for day in range(3):
        people = suggestions.for_owner_row(me(world), "digest", k=2)["people"]
        suggestions.record_impressions("c-me", "digest", people)
        seen_days.append(set(handles(people)))
    assert seen_days[0] and not (seen_days[0] & seen_days[1]) and not (seen_days[1] & seen_days[2])


# ── stored suggestions ──────────────────────────────────────────────────────────────────

def test_refresh_stores_the_top_people_per_claimed_card(world):
    stats = suggestions.refresh_all()
    assert stats["errors"] == 0 and stats["cards"] == 5
    mine = [r for r in world.rows("card_suggestions") if r["card_id"] == "c-me"]
    assert {r["candidate_card_id"] for r in mine} == {"c-ann", "c-ivy"}
    assert all(len([r for r in world.rows("card_suggestions") if r["card_id"] == c]) <= suggestions.TOP_N
               for c in {r["card_id"] for r in world.rows("card_suggestions")})
    suggestions.refresh_all(handle="me")                           # replaces, never duplicates
    assert len([r for r in world.rows("card_suggestions") if r["card_id"] == "c-me"]) == 2


def test_surfaces_read_the_stored_list_and_recheck_todays_exclusions(world, monkeypatch):
    suggestions.refresh_all(handle="me")
    monkeypatch.setattr(suggestions, "compute", lambda *a, **k: pytest.fail("a fresh stored list is read, not computed"))
    assert handles(suggestions.for_owner_row(me(world), "owner_home", k=4)["people"]) == ["ann", "ivy"]
    world.new_row("connections", {"connection_key": "k", "requester_user_id": ME, "requester_card_id": "c-me",
                                  "recipient_user_id": uid(2), "recipient_card_id": "c-ann", "status": "pending"})
    assert handles(suggestions.for_owner_row(me(world), "owner_home", k=4)["people"]) == ["ivy"]


def test_a_stale_stored_list_is_computed_again(world):
    suggestions.refresh_all(handle="me")
    for r in world.rows("card_suggestions"):
        r["computed_at"] = (NOW - timedelta(hours=suggestions.FRESH_HOURS + 1)).isoformat()
    for r in world.rows("card_suggestions"):
        r["candidate_card_id"] = "c-dev"                       # what the stale list said no longer counts
    assert handles(suggestions.for_owner_row(me(world), "owner_home", k=4)["people"]) == ["ann", "ivy"]


class NoSuggestionTables(FakeSupabase):
    """The database before packages/db cards 0031 is applied."""

    def table(self, name):
        if name.startswith("card_suggestion"):
            raise RuntimeError('relation "cards.card_suggestions" does not exist (42P01)')
        return super().table(name)


def test_everything_works_live_before_the_migration_is_applied(monkeypatch, world):
    sb = NoSuggestionTables(agent_profile_cards=base_rows())
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    monkeypatch.setattr(network, "_sb", lambda: sb)
    row_ = me(sb)
    assert handles(suggestions.for_owner_row(row_, "digest", k=2)["people"]) == ["ann", "ivy"]
    assert suggestions.record_impressions("c-me", "digest", [{"card_id": "c-ann"}]) == 0
    assert suggestions.refresh_all()["table_missing"] is True


# ── feedback ────────────────────────────────────────────────────────────────────────────

def test_hide_is_recorded_and_the_person_is_not_suggested_again(world):
    suggestions.record_impressions("c-me", "owner_home", [{"card_id": "c-ann", "score": 0.7}])
    assert suggestions.feedback(me(world), "ann", "hide") == {"ok": True, "handle": "ann", "action": "hide"}
    (imp,) = world.rows("card_suggestion_impressions")
    assert imp["action"] == "hide"
    assert "ann" not in handles(suggestions.compute(me(world)))
    assert world.rows("match_preferences") == []                # network controls are off


def test_feedback_also_teaches_search_when_network_controls_are_on(world, monkeypatch):
    monkeypatch.setattr(config, "FEATURE_NETWORK_CONTROLS", True)
    suggestions.feedback(me(world), "ann", "hide")
    suggestions.feedback(me(world), "ivy", "not_relevant")
    prefs = {(r["kind"], r["value"]) for r in world.rows("match_preferences")}
    assert prefs == {("hide_person", "ann"), ("less_like_this", "ivy")}


def test_feedback_rejects_unknown_actions_people_and_yourself(world):
    with pytest.raises(HTTPException):
        suggestions.feedback(me(world), "ann", "love")
    with pytest.raises(HTTPException):
        suggestions.feedback(me(world), "nobody", "hide")
    with pytest.raises(HTTPException):
        suggestions.feedback(me(world), "me", "hide")


def test_a_connection_request_marks_the_suggestion_connected(world):
    suggestions.record_impressions("c-me", "digest", [{"card_id": "c-ann", "score": 0.7}])
    network.request_connection(ME, "ann")
    (imp,) = world.rows("card_suggestion_impressions")
    assert imp["action"] == "connect"


def test_owner_home_records_one_impression_per_person_per_day(world):
    people = [{"card_id": "c-ann", "score": 0.7}, {"card_id": "c-ivy", "score": 0.5}]
    assert suggestions.record_impressions("c-me", "owner_home", people) == 2
    assert suggestions.record_impressions("c-me", "owner_home", people) == 0
    assert suggestions.record_impressions("c-me", "digest", people) == 2


@pytest.fixture
def home_app(world):
    from api import owner_home as owner_home_api
    app = FastAPI()
    app.include_router(owner_home_api.router, prefix="/cards")
    return TestClient(app)


def test_email_links_only_act_on_post(world, home_app):
    url = f"/cards/suggestions/feedback/{me(world)['unsubscribe_token']}/ann/hide"
    page = home_app.get(url)
    assert page.status_code == 200 and "Hide this person?" in page.text and 'method="post"' in page.text
    assert world.rows("card_suggestion_impressions") == []      # a mail scanner opening the link changes nothing
    done = home_app.post(url)
    assert done.status_code == 200 and "Hidden" in done.text
    assert world.rows("card_suggestion_impressions")[0]["action"] == "hide"


def test_email_links_need_a_real_token_and_action(world, home_app):
    assert home_app.post("/cards/suggestions/feedback/11111111-1111-4111-8111-111111111111/ann/hide").status_code == 404
    token = me(world)["unsubscribe_token"]
    assert home_app.post(f"/cards/suggestions/feedback/{token}/ann/delete").status_code == 404


def test_refresh_route_needs_the_cron_secret(world, monkeypatch):
    from api import internal
    monkeypatch.setattr(config, "CRON_SECRET", "s3cret")
    app = FastAPI()
    app.include_router(internal.router, prefix="/internal")
    client = TestClient(app)
    assert client.post("/internal/suggestions/refresh").status_code == 401
    ok = client.post("/internal/suggestions/refresh?handle=me", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200 and ok.json()["cards"] == 1


# ── outside people ──────────────────────────────────────────────────────────────────────

def test_outside_people_only_when_zynd_has_too_few(world, monkeypatch):
    monkeypatch.setattr(suggested_people, "outside_for", lambda card, people: [{"name": "Pat", "linkedin_url": "u"}])
    assert suggestions.for_owner_row(me(world), "owner_home", k=4)["outside"] == []        # ann and ivy
    world.new_row("connections", {"connection_key": "k", "requester_user_id": ME, "requester_card_id": "c-me",
                                  "recipient_user_id": uid(2), "recipient_card_id": "c-ann", "status": "accepted"})
    assert suggestions.for_owner_row(me(world), "owner_home", k=4)["outside"] == [{"name": "Pat", "linkedin_url": "u"}]


# ── owner home ──────────────────────────────────────────────────────────────────────────

def test_owner_home_shows_suggestions_and_records_them_once(world):
    from services import owner_home
    block = owner_home.suggested_people(me(world))
    assert handles(block["people"]) == ["ann", "ivy"] and block["outside"] == []
    assert len(world.rows("card_suggestion_impressions")) == 2
    owner_home.suggested_people(me(world), record=False)              # the digest preview records nothing
    assert len(world.rows("card_suggestion_impressions")) == 2


def test_owner_home_survives_a_suggestions_failure(world, monkeypatch):
    from services import owner_home
    monkeypatch.setattr(suggestions, "for_owner_row", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert owner_home.suggested_people(me(world)) == {"people": [], "outside": []}


def test_owner_feedback_route_uses_the_signed_in_owner(world, home_app, monkeypatch):
    from api import owner_home as owner_home_api
    monkeypatch.setattr(owner_home_api, "email_for", lambda authorization: "me@example.com")
    monkeypatch.setattr(owner_home_api.owner_home, "current_row", lambda email: me(world))
    ok = home_app.post("/cards/mine/suggestions/ann/feedback", json={"action": "not_relevant"})
    assert ok.status_code == 200 and ok.json() == {"ok": True, "handle": "ann", "action": "not_relevant"}
    assert home_app.post("/cards/mine/suggestions/ann/feedback", json={"action": "delete"}).status_code == 422
