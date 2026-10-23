from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

import config
from api import owner_home as routes
from models.card import AgentProfileCard
from services import owner_home, owner_notifications as notifications
from services.completeness import completeness


def card(**kwargs):
    return AgentProfileCard(id="c1", handle="alice", **kwargs)


def test_completeness_empty_and_three_action_limit():
    result = completeness(card())
    assert result["score"] == 0
    assert len(result["actions"]) == 3
    assert result["actions"][0]["href"] == "/p/alice/edit#identity"


def test_completeness_does_not_require_private_memory():
    result = completeness(card(identity={"name": "Alice", "headline": "Engineer", "avatar_url": "https://a.test/a", "links": {"github": "https://github.com/a"}}, summary="Hi", skills=[{"name": "Python"}], projects=[{"name": "Project"}], working_on=["Project"], zynd_memory=[{"object": "Python"}]))
    assert result == {"score": 100, "actions": []}


def test_expiring_seeking_boundary_and_stable_deduplication():
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    facts = [{"predicate": "is_seeking", "object": "cofounder", "approved_at": (now - timedelta(days=4)).isoformat()}]
    c = card(zynd_memory=facts)
    first = owner_home.nudge_candidates(c, 0, now)
    assert len(first) == 1
    assert first[0]["dedupe_key"] == owner_home.nudge_candidates(c, 0, now + timedelta(days=1))[0]["dedupe_key"]
    assert owner_home.nudge_candidates(c, 0, now + timedelta(days=3)) == []
    assert owner_home.nudge_candidates(c, 0, now - timedelta(seconds=1)) == []


def test_activity_flag_off_means_unavailable_not_zero(monkeypatch):
    monkeypatch.setattr(config, "FEATURE_S04_EVENTS", False)
    sb = MagicMock()
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    result = owner_home.activity("alice")
    assert result["views"] is None
    assert result["chat_topics"] == []
    sb.assert_not_called()


def test_available_matching_queries_are_grouped_and_redacted():
    sb = MagicMock()
    q = sb.table.return_value
    for method in ("select", "eq", "gte", "order", "limit"):
        getattr(q, method).return_value = q
    q.execute.return_value.data = [{"meta": {"endpoint": "ask", "query": "Python engineer"}},
                                  {"meta": {"endpoint": "ask", "query": "Python engineer"}},
                                  {"meta": {"endpoint": "ask", "query": "Ask private@example.com"}},
                                  {"meta": {"endpoint": "data.json", "query": "ignored"}}]
    result = owner_home.query_summaries(sb, "alice", "2026-10-05")
    assert result == [{"query": "Python engineer", "count": 2}, {"query": "Ask [redacted]", "count": 1}]


def test_chat_topics_group_categories_and_ignore_text():
    sb = MagicMock()
    q = sb.table.return_value
    for method in ("select", "eq", "gte", "order", "limit"):
        getattr(q, method).return_value = q
    q.execute.return_value.data = [
        {"meta": {"category": "contact", "chars": 12, "query": "email me at secret@example.com"}},
        {"meta": {"category": "work", "chars": 20}},
        {"meta": {"category": "contact", "chars": 8}},
        {"meta": {"category": "nope", "chars": 4}},
        {"meta": {}},
    ]
    assert owner_home.chat_topics(sb, "alice", "2026-10-05") == [
        {"category": "contact", "count": 2},
        {"category": "work", "count": 1},
    ]


def test_activity_real_counts_are_owner_handle_scoped(monkeypatch):
    monkeypatch.setattr(config, "FEATURE_S04_EVENTS", True)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    sb = MagicMock()
    q = sb.table.return_value
    q.select.return_value = q
    q.eq.return_value = q
    q.gte.return_value = q
    q.execute.side_effect = [
        SimpleNamespace(count=7), SimpleNamespace(count=2), SimpleNamespace(count=3),
        SimpleNamespace(data=[]), SimpleNamespace(data=[]),
    ]
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    result = owner_home.activity("alice")
    assert result["views"] == 7 and result["agent_hits"] == 5
    assert result["intro_requests"] is None
    assert result["chat_topics"] == []
    assert ("handle", "alice") in [call.args for call in q.eq.call_args_list]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "FEATURE_S10_HOME", True)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    monkeypatch.setattr(routes, "_principal", lambda auth: SimpleNamespace(email="alice@example.com") if auth == "Bearer owner" else (_ for _ in ()).throw(routes.HTTPException(401, "Unauthorized")))
    app = FastAPI()
    app.include_router(routes.router, prefix="/cards")
    return TestClient(app)


def test_status_requires_auth(client):
    assert client.get("/cards/mine/status").status_code == 401


def test_status_flag_off(client, monkeypatch):
    monkeypatch.setattr(config, "FEATURE_S10_HOME", False)
    assert client.get("/cards/mine/status", headers={"Authorization": "Bearer owner"}).status_code == 404


def test_status_uses_verified_email(client, monkeypatch):
    status = AsyncMock(return_value={"handle": "alice"})
    monkeypatch.setattr(owner_home, "status", status)
    response = client.get("/cards/mine/status?email=other@example.com", headers={"Authorization": "Bearer owner"})
    assert response.json() == {"handle": "alice"}
    status.assert_awaited_once_with("alice@example.com")


def test_section_rejects_server_owned_fields(client, monkeypatch):
    called = MagicMock()
    monkeypatch.setattr(routes, "rpc", called)
    response = client.patch("/cards/by-handle/alice/sections/summary", headers={"Authorization": "Bearer owner"}, json={"patch": {"status": "published"}, "expected": {"status": "private"}})
    assert response.status_code == 422
    called.assert_not_called()


def test_sparse_section_expectation_is_translated_without_losing_lock_check(client, monkeypatch):
    raw = {"id": "c1", "identity": {"name": "Alice"}}
    original = AgentProfileCard.model_validate(raw)
    sb = MagicMock()
    q = sb.table.return_value
    for method in ("select", "eq", "ilike", "limit"):
        getattr(q, method).return_value = q
    q.execute.return_value.data = [{"card": raw, "handle": "alice"}]
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    monkeypatch.setattr(routes, "ping_revalidate", lambda *args: None)
    updated = original.model_dump(mode="json")
    updated["identity"]["name"] = "Alice Updated"
    updated["updated_at"] = "2026-10-12T00:00:00Z"
    operation = MagicMock(return_value=updated)
    monkeypatch.setattr(routes, "rpc", operation)
    response = client.patch("/cards/by-handle/alice/sections/identity", headers={"Authorization": "Bearer owner"}, json={"patch": {"identity": updated["identity"]}, "expected": {"identity": original.model_dump(mode="json")["identity"]}})
    assert response.status_code == 200
    assert operation.call_args.args[1]["p_expected"] == {"identity": {"name": "Alice"}}


def _identity_save(client, monkeypatch, stored, patch_identity, expected_identity):
    raw = {"id": "c1", "identity": stored}
    sb = MagicMock()
    q = sb.table.return_value
    for method in ("select", "eq", "ilike", "limit"):
        getattr(q, method).return_value = q
    q.execute.return_value.data = [{"card": raw, "handle": "alice"}]
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    monkeypatch.setattr(routes, "ping_revalidate", lambda *args: None)
    operation = MagicMock(return_value={**AgentProfileCard.model_validate(raw).model_dump(mode="json"), "updated_at": "2026-10-12T00:00:00Z"})
    monkeypatch.setattr(routes, "rpc", operation)
    # The editor sends the full serialized identity, defaults included.
    full = lambda identity: AgentProfileCard.model_validate({"id": "c1", "identity": identity}).model_dump(mode="json")["identity"]
    response = client.patch("/cards/by-handle/alice/sections/identity", headers={"Authorization": "Bearer owner"}, json={"patch": {"identity": full(patch_identity)}, "expected": {"identity": full(expected_identity)}})
    return response, operation


def test_photo_drift_from_avatar_self_heal_does_not_conflict(client, monkeypatch):
    # The editor loaded the old LinkedIn photo; the self-heal has since stored a new one.
    response, operation = _identity_save(
        client, monkeypatch, {"name": "Alice", "avatar_url": "https://media.licdn.com/healed"},
        {"name": "Alicia", "avatar_url": "https://media.licdn.com/old"},
        {"name": "Alice", "avatar_url": "https://media.licdn.com/old"})
    assert response.status_code == 200
    sent = operation.call_args.args[1]
    assert sent["p_patch"]["identity"]["name"] == "Alicia"
    assert sent["p_patch"]["identity"]["avatar_url"] == "https://media.licdn.com/healed"
    assert sent["p_expected"]["identity"]["avatar_url"] == "https://media.licdn.com/healed"


def test_editor_cannot_set_the_photo(client, monkeypatch):
    response, operation = _identity_save(
        client, monkeypatch, {"name": "Alice", "avatar_url": "https://media.licdn.com/li.jpg"},
        {"name": "Alice", "avatar_url": "https://cdn.example/mine.jpg"},
        {"name": "Alice", "avatar_url": "https://media.licdn.com/li.jpg"})
    assert response.status_code == 200
    assert operation.call_args.args[1]["p_patch"]["identity"]["avatar_url"] == "https://media.licdn.com/li.jpg"


def test_other_identity_drift_still_conflicts(client, monkeypatch):
    response, operation = _identity_save(
        client, monkeypatch, {"name": "Renamed elsewhere", "avatar_url": "https://media.licdn.com/li.jpg"},
        {"name": "Alice", "avatar_url": "https://media.licdn.com/li.jpg"},
        {"name": "Alice", "avatar_url": "https://media.licdn.com/li.jpg"})
    assert response.status_code == 409
    operation.assert_not_called()


def test_rpc_conflict_returns_409(monkeypatch):
    sb = MagicMock()
    sb.rpc.return_value.execute.side_effect = APIError({"code": "40001", "message": "changed", "details": None, "hint": None})
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    with pytest.raises(routes.HTTPException) as exc:
        routes.rpc("s10_save_section", {})
    assert exc.value.status_code == 409


def test_memory_refresh_uses_atomic_system_patch_when_s10_enabled(monkeypatch):
    from services import cards, embed
    monkeypatch.setattr(config, "FEATURE_S10_HOME", True)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    monkeypatch.setattr(config, "get_supabase", lambda: MagicMock())
    patch = MagicMock(return_value={"id": "c1", "handle": "alice", "summary": "Concurrent owner edit", "updated_at": "2026-10-12T00:00:00Z", "zynd_memory": []})
    monkeypatch.setattr(cards, "patch_system_fields", patch)
    monkeypatch.setattr(embed, "embed_text", lambda text: [])
    assert cards.update_card_memory("alice", []) is True
    patch.assert_called_once_with("alice", {"zynd_memory": []})


def test_digest_html_escapes_owner_data_and_links_to_inbox(monkeypatch):
    monkeypatch.setattr(config, "SITE_BASE_URL", "https://cards.test")
    data = {"name": "<script>Alice</script>", "handle": "alice", "inbox_count": 2,
            "activity": {"available": True, "views": 9, "agent_hits": 3, "queries": [{"query": '<img src=x onerror="bad">'}]},
            "completeness": {"score": 80}}
    body, html = notifications.render_weekly(data, "https://cards.test/unsubscribe")
    assert "9 human views" in body and "/p/alice/edit#inbox" in body
    assert "<script>" not in html and "<img" not in html
    assert "Unsubscribe" in html
    assert "mailto:" not in html


def test_delivery_duplicate_constraint_skips_send(monkeypatch):
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.side_effect = APIError({"code": "23505", "message": "duplicate", "details": None, "hint": None})
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    assert notifications.claim_delivery("alice@example.com", "weekly", "2026-W42") is None


def test_iso_week_handles_year_boundary():
    assert notifications.week_key(datetime(2027, 1, 1, tzinfo=timezone.utc)) == "2026-W53"


def test_noop_mailer_is_no_send(monkeypatch):
    from services.mailer import get_mailer
    monkeypatch.setattr(config, "S10_MAILER", "noop")
    assert get_mailer().enabled is False


@pytest.mark.asyncio
async def test_weekly_job_is_idempotent_per_owner_and_honors_optout(monkeypatch):
    monkeypatch.setattr(config, "FEATURE_S10_HOME", True)
    monkeypatch.setattr(config, "FEATURE_S10_DIGEST", True)
    monkeypatch.setattr(config, "SUPABASE_DB_SCHEMA", "cards")
    row = {"id": "c1", "handle": "alice", "status": "published", "owner_email": "alice@example.com", "unsubscribe_token": "token", "notification_prefs": {"weekly_digest": True, "email_nudges": False}}
    q = MagicMock()
    for method in ("select", "neq", "order", "range", "update", "eq"):
        getattr(q, method).return_value = q
    q.not_.is_.return_value = q
    q.execute.return_value.data = [row]
    sb = MagicMock()
    sb.table.return_value = q
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    data = {"handle": "alice", "name": "Alice", "activity": {"available": True, "views": 3, "agent_hits": 1, "queries": []}, "inbox_count": 0, "completeness": {"score": 80}, "nudges": [], "notification_prefs": row["notification_prefs"]}
    monkeypatch.setattr(owner_home, "status", AsyncMock(return_value=data))
    monkeypatch.setattr(owner_home, "current_row", lambda email: row)
    adapter = MagicMock(enabled=True)
    monkeypatch.setattr(notifications, "get_mailer", lambda: adapter)
    claimed = set()
    def claim(email, kind, period):
        key = (email, kind, period)
        if key in claimed: return None
        claimed.add(key)
        return "delivery1"
    monkeypatch.setattr(notifications, "claim_delivery", claim)
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    first = await notifications.run_notifications(now=now)
    second = await notifications.run_notifications(now=now + timedelta(days=1))
    assert first["sent"] == 1 and second["sent"] == 0
    adapter.send.assert_called_once()
    row["notification_prefs"]["weekly_digest"] = False
    await notifications.run_notifications(now=now + timedelta(days=7))
    assert adapter.send.call_count == 1


def test_timezone_requires_auth(client):
    assert client.patch("/cards/mine/timezone", json={"timezone": "Asia/Kolkata"}).status_code == 401


def test_timezone_is_saved_for_the_verified_owner_only(client, monkeypatch):
    sb = MagicMock()
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    response = client.patch("/cards/mine/timezone?email=other@example.com", headers={"Authorization": "Bearer owner"},
                            json={"timezone": " America/Los_Angeles "})
    assert response.status_code == 200
    assert response.json() == {"timezone": "America/Los_Angeles"}
    q = sb.table.return_value
    q.update.assert_called_once_with({"timezone": "America/Los_Angeles"})
    q.update.return_value.ilike.assert_called_once_with("owner_email", "alice@example.com")


@pytest.mark.parametrize("bad", ["", "Not/AZone", "../etc/passwd", "x" * 65])
def test_timezone_rejects_unknown_zones(client, monkeypatch, bad):
    sb = MagicMock()
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    response = client.patch("/cards/mine/timezone", headers={"Authorization": "Bearer owner"}, json={"timezone": bad})
    assert response.status_code == 422
    sb.table.assert_not_called()


def test_unsubscribe_get_does_not_mutate_preferences(client, monkeypatch):
    sb = MagicMock()
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    response = client.get("/cards/notifications/unsubscribe/11111111-1111-4111-8111-111111111111")
    assert response.status_code == 200 and 'method="post"' in response.text
    sb.table.assert_not_called()


def test_unsubscribe_updates_all_cards_for_only_matching_owner(client, monkeypatch):
    sb = MagicMock()
    q = sb.table.return_value
    q.select.return_value.eq.return_value.execute.return_value.data = [{"owner_email": "alice@example.com"}]
    monkeypatch.setattr(config, "get_supabase", lambda: sb)
    response = client.post("/cards/notifications/unsubscribe/11111111-1111-4111-8111-111111111111")
    assert response.status_code == 200
    q.update.assert_called_once_with({"notification_prefs": {"weekly_digest": False, "email_nudges": False}})
    q.update.return_value.ilike.assert_called_once_with("owner_email", "alice@example.com")


def test_identity_save_can_pick_and_clear_an_edition(client, monkeypatch):
    edition = {"id": "mumbai-26", "mood": "dusk", "here_for": "speaking"}
    response, operation = _identity_save(
        client, monkeypatch, {"name": "Alice"},
        {"name": "Alice", "edition": edition},
        {"name": "Alice"})
    assert response.status_code == 200
    # Stored normalized: an edition picked without a banner gets the default one.
    assert operation.call_args.args[1]["p_patch"]["identity"]["edition"] == {**edition, "banner": "waterfront"}

    response, operation = _identity_save(
        client, monkeypatch, {"name": "Alice", "edition": edition},
        {"name": "Alice", "edition": None},
        {"name": "Alice", "edition": edition})
    assert response.status_code == 200
    assert "edition" not in operation.call_args.args[1]["p_patch"]["identity"]
