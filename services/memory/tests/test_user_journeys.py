"""Real-world user-lifecycle simulation tests for ZYND.

These are SCENARIO tests, not unit tests. Each walks through what a real human
does — Alice signs up, remembers her first facts, curates her graph, tries to
connect with people, manages her brief, disconnects, publishes a page. Every
dependency (Postgres, Redis, Supabase, the persona service) is mocked, so the
whole file runs with no infrastructure.

MCP tools are the module-level functions in `app.mcp_http`. FastMCP normally
injects the caller's user id via `Depends(_uid)`; we bypass that by passing the
`uid=` / `suid=` kwarg directly.
"""
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.server.auth import AccessToken

import app.mcp_http as m
from app.auth import issue_access_token, verify_access_claims
from app.config import settings
from app.connect import connect as connect_route


@pytest.fixture
def packet_dependencies():
    pool = AsyncMock()
    pool.fetchrow.return_value = {
        "display_name": "Alice", "email": "alice@example.com",
        "supabase_user_id": None, "socials": {},
    }
    token = AccessToken(token="test", client_id="test-uid", scopes=["memory:write"])
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)), \
         patch("app.mcp_http.get_card", AsyncMock(return_value=[])), \
         patch("app.mcp_http.brief_tools.read_my_brief", AsyncMock(return_value={"success": True, "content": ""})):
        yield pool, token


# ── Journey 1: New user signs up and remembers her first facts ─────────────────


async def test_new_user_signs_up_and_receives_a_working_token():
    # given — Alice has never used ZYND; the account does not exist yet
    new_user_id = "11111111-1111-1111-1111-111111111111"
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=None)          # no existing user row
    pool.fetchval = AsyncMock(side_effect=[new_user_id, 1])  # INSERT id, then token_version

    # when — she submits the /connect signup form with a fresh email + password
    with patch("app.connect.get_pool", return_value=pool):
        response = await connect_route(email="Alice@Example.com", password="strongpass1")

    # then — she gets an MCP config carrying a real, decodable ZYND token for her id
    assert response.status_code == 200
    assert "mcpServers" in response.body.decode()
    assert "Authorization: Bearer" in response.body.decode()
    pool.fetchval.assert_awaited()   # a brand-new account was actually created


async def test_returning_user_signs_in_with_correct_password():
    # given — Alice already has an account with a known password
    existing_id = "22222222-2222-2222-2222-222222222222"
    from app.passwords import hash_password
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value={"id": existing_id, "password_hash": hash_password("strongpass1")})
    pool.fetchval = AsyncMock(return_value=1)  # token_version bump during personal-token mint

    # when — she signs back in with the same password
    with patch("app.connect.get_pool", return_value=pool):
        response = await connect_route(email="alice@example.com", password="strongpass1")

    # then — she is let in and NO new account is created (one fetchval: the version bump)
    assert response.status_code == 200
    assert "Authorization: Bearer" in response.body.decode()
    assert pool.fetchval.await_count == 1


async def test_signup_rejects_a_too_short_password():
    # given — Alice fat-fingers a 2-char password
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=None)

    # when
    with patch("app.connect.get_pool", return_value=pool):
        response = await connect_route(email="alice@example.com", password="ab")

    # then — the form is rejected before any DB write happens
    assert response.status_code == 400


async def test_user_remembers_her_first_durable_fact():
    # given — a signed-in user shares a real fact about what she is building
    uid = "test-uid"
    pool, arq = MagicMock(), MagicMock()

    # when — the assistant saves a full sentence through the unified write tool
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)), \
         patch("app.mcp_http._get_arq", AsyncMock(return_value=arq)), \
         patch("app.mcp_http.ingest_turns", AsyncMock(return_value=(1, 0))) as ingest:
        result = await m.report_user_info(text="I am building a Rust microservices platform", uid=uid)

    # then — the fact is accepted and enqueued for background extraction
    assert result["saved"] is True
    ingest.assert_awaited_once()


async def test_free_text_report_rejects_text_that_is_too_short():
    # given — the assistant tries to save a fragment below the 8-char floor
    # when
    result = await m.report_user_info(text="hi", uid="test-uid")

    # then — nothing is saved and the reason explains the minimum length
    assert result["saved"] is False
    assert "too short" in result["reason"]


async def test_free_text_report_rejects_a_duplicate_fact():
    # given — the same fact was already remembered (ingest reports 0 inserted)
    pool, arq = MagicMock(), MagicMock()

    # when — the assistant tries to remember it a second time
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)), \
         patch("app.mcp_http._get_arq", AsyncMock(return_value=arq)), \
         patch("app.mcp_http.ingest_turns", AsyncMock(return_value=(0, 1))):
        result = await m.report_user_info(text="I am building a Rust microservices platform", uid="test-uid")

    # then — it is de-duplicated, not double-counted
    assert result["saved"] is False
    assert "already remembered" in result["reason"]


async def test_user_reads_back_her_context_after_signing_up(packet_dependencies):
    # given — background processing has not produced any facts yet
    pool, token = packet_dependencies

    # when — she asks the assistant what ZYND knows about her
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)), \
         patch("app.mcp_http.active_context", AsyncMock(return_value=[])) as active:
        result = await m.get_my_context(uid="test-uid", token=token)

    assert result["facts"] == []
    assert result["identity"]["name"] == "Alice"
    assert result["present"] == ["identity"]
    active.assert_awaited_once()


# ── Journey 2: User curates her fact graph ─────────────────────────────────────


async def test_user_asks_for_context_on_a_specific_topic(packet_dependencies):
    # given — she has facts and wants only the ones about Rust
    pool, token = packet_dependencies
    rust_fact = {"statement": "You're building a Rust platform", "predicate": "is_building", "object": "Rust platform"}

    # when — a topic is supplied, get_my_context routes through the topic slice
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)), \
         patch("app.mcp_http.context_slice", AsyncMock(return_value=[rust_fact])) as slice_fn, \
         patch("app.mcp_http.active_context", AsyncMock(return_value=[])) as active:
        result = await m.get_my_context(topic="rust", uid="test-uid", token=token)

    # then — the topic-relevant slice is returned, not the whole graph
    assert result["facts"] == [rust_fact]
    assert result["identity"]["name"] == "Alice"
    slice_fn.assert_awaited_once()
    active.assert_not_awaited()


async def test_user_confirms_a_fact_is_correct():
    # given — ZYND remembers she has_skill Rust and she confirms it
    pool = MagicMock()

    # when
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)), \
         patch("app.mcp_http.confirm_fact", AsyncMock(return_value={"predicate": "has_skill", "object": "Rust"})) as confirm:
        result = await m.confirm_fact_tool("has_skill", "Rust", uid="test-uid")

    # then — the tool reports the confirmation succeeded with the stored fact
    assert result["confirmed"] is True
    assert result["predicate"] == "has_skill" and result["object"] == "Rust"
    confirm.assert_awaited_once()


async def test_user_forgets_an_outdated_fact():
    # given — she tells the assistant an old-project fact is no longer true
    pool = MagicMock()

    # when
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)), \
         patch("app.mcp_http.forget_fact", AsyncMock(return_value={"predicate": "is_building", "object": "old project"})) as forget, \
         patch("app.mcp_http.card_sync.notify_cards_refresh", AsyncMock()) as notify:
        result = await m.forget_fact_tool("is_building", "old project", uid="test-uid")

    # then — the fact is soft-deleted and cards-api is notified to refresh the snapshot
    assert result["forgotten"] is True
    assert result["predicate"] == "is_building" and result["object"] == "old project"
    forget.assert_awaited_once()
    notify.assert_awaited_once_with(pool, "test-uid")


async def test_forgetting_a_fact_that_does_not_exist_reports_false():
    # given — the predicate/object pair matches nothing in her graph
    pool = MagicMock()

    # when
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)), \
         patch("app.mcp_http.forget_fact", AsyncMock(return_value=None)), \
         patch("app.mcp_http.near_matches", AsyncMock(return_value=[
             {"predicate": "is_building", "object": "other project", "confidence": 0.5, "is_public": False},
         ])):
        result = await m.forget_fact_tool("is_building", "never existed", uid="test-uid")

    # then — the tool honestly reports nothing was forgotten and offers near-matches
    assert result["forgotten"] is False
    assert result["matches"][0]["predicate"] == "is_building"


async def test_confirming_a_fact_that_does_not_exist_reports_false():
    # given — the predicate/object pair matches nothing in her graph
    pool = MagicMock()

    # when
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)), \
         patch("app.mcp_http.confirm_fact", AsyncMock(return_value=None)), \
         patch("app.mcp_http.near_matches", AsyncMock(return_value=[])):
        result = await m.confirm_fact_tool("has_skill", "Nope", uid="test-uid")

    # then — the tool honestly reports nothing was confirmed
    assert result["confirmed"] is False
    assert result["matches"] == []


async def test_user_exports_her_full_context_as_signed_jsonld():
    # given — a real active graph the export builder will sign
    uid = "22222222-2222-2222-2222-222222222222"
    assertions = [
        {"predicate": "is_building", "object": "Rust platform", "object_type": "concept",
         "confidence": 0.9, "observed_at": "2026-08-01T00:00:00+00:00"},
    ]
    # active-graph rows the export SQL would return
    rows = [{
        "predicate": a["predicate"], "object": a["object"], "object_type": a["object_type"],
        "confidence": a["confidence"], "observed_at": None,
    } for a in assertions]
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=rows)

    # when — she asks the assistant to export/back up her ZYND profile
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)):
        result = await m.export_my_context(uid=uid)

    # then — she gets portable, tamper-evident JSON-LD she owns
    assert result["@context"] == "https://zynd.io/schema/v1"
    assert result["@type"] == "UserContext"
    assert result["user_id"] == uid
    assert isinstance(result["assertions"], list) and len(result["assertions"]) == 1

    # and — the HMAC signature actually verifies over the exported assertions
    payload = json.dumps(result["assertions"], sort_keys=True, separators=(",", ":"))
    expected = hmac.new(settings.jwt_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    assert result["signature"] == expected


# ── Journey 3: User tries to connect with others (cold start) ──────────────────


async def test_new_user_finds_no_similar_users_yet():
    # given — a brand-new user whose matching vectors have not been computed
    pool = MagicMock()

    # when — she asks for people like her
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)), \
         patch("app.mcp_http.match_users", AsyncMock(return_value=[])) as match:
        result = await m.find_similar_users(uid="test-uid")

    # then — an empty list comes back (no matches, no error)
    assert result == []
    match.assert_awaited_once()


async def test_user_searches_for_a_target_person_and_gets_no_matches():
    # given — no findable ZYND user matches her target description yet
    pool = MagicMock()

    # when — she looks for a seed-stage investor in dev tools
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)), \
         patch("app.mcp_http.search_by_query", AsyncMock(return_value=[])) as search:
        result = await m.find_people("seed-stage investor in dev tools", uid="test-uid")

    # then — the search returns [] rather than fabricating people
    assert result == []
    search.assert_awaited_once()


# ── Journey 4: User manages her brief and todos ────────────────────────────────


async def test_user_with_no_persona_has_an_empty_brief(packet_dependencies):
    # The packet fixture has no linked persona and an empty brief service result.
    with patch("app.mcp_http.active_context", AsyncMock(return_value=[])):
        result = await m.get_my_context(uid="test-uid", token=packet_dependencies[1])

    # then — the tool reports the brief simply does not exist yet
    assert result["brief"] is None
    assert "brief" not in result["present"]


async def test_user_appends_a_line_to_her_brief():
    # given — an existing brief she wants to extend
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"brief_content": "Founder building ZYND.", "description": ""}
    ]
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    # when
    with patch("app.tools.brief._sb", return_value=sb):
        result = await m.append_to_my_brief("Working on ZYND integration", suid="suid-abc")

    # then — the appended text is echoed back on success
    assert result["success"] is True
    assert result["appended"] == "Working on ZYND integration"


async def test_appending_empty_text_to_the_brief_is_rejected():
    # given / when — she appends an empty string
    result = await m.append_to_my_brief("", suid="suid-abc")

    # then — the tool refuses and explains the input was empty
    assert result["success"] is False
    assert "empty" in result["error"].lower()


async def test_user_replaces_her_entire_brief():
    # given — she wants to overwrite the brief wholesale
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    # when
    with patch("app.tools.brief._sb", return_value=sb):
        result = await m.replace_my_brief("New content", suid="suid-abc")

    # then — the new content is confirmed
    assert result["success"] is True
    assert result["content"] == "New content"


async def test_user_clears_her_brief():
    # given — she wants a blank slate
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    # when
    with patch("app.tools.brief._sb", return_value=sb):
        result = await m.clear_my_brief(suid="suid-abc")

    # then — the brief is emptied
    assert result["success"] is True
    assert result["content"] == ""


async def test_user_adds_a_todo_to_her_brief():
    # given — a fresh todo she wants tracked
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "todo-uuid-1"}]

    # when
    with patch("app.tools.brief._sb", return_value=sb):
        result = await m.add_todo("Ship the MCP server", suid="suid-abc")

    # then — the todo is created and its id is returned
    assert result["success"] is True
    assert result["todo_id"] == "todo-uuid-1"


async def test_adding_an_empty_todo_is_rejected():
    # given / when — she submits a blank todo title
    result = await m.add_todo("", suid="suid-abc")

    # then — nothing is created
    assert result["success"] is False


# ── Journey 5: User disconnects and her old token stops working ────────────────


async def test_user_disconnects_and_is_signed_out_everywhere():
    # given — a signed-in user who asks to disconnect ZYND
    pool = MagicMock()

    # when — disconnect imports revoke_user_tokens lazily from the sessions module
    from app.services import sessions as sess_mod
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)), \
         patch.object(sess_mod, "revoke_user_tokens", AsyncMock()) as revoke:
        result = await m.disconnect(uid="test-uid")

    # then — every one of her tokens is revoked and she is told to reconnect
    assert result["status"] == "signed_out"
    revoke.assert_awaited_once()


async def test_old_token_is_rejected_after_the_user_disconnects():
    # given — a valid token she was using before signing out
    uid = "33333333-3333-3333-3333-333333333333"
    token = issue_access_token(uid)[0]
    _, issued_at, _ = verify_access_claims(token)  # token itself is structurally valid

    verifier = m.ZyndTokenVerifier()
    pool = MagicMock()

    # when — after disconnect, the revocation watermark is now AFTER the token's iat
    from app.services import sessions as sess_mod
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)), \
         patch.object(sess_mod, "tokens_revoked", AsyncMock(return_value=True)):
        result = await verifier.verify_token(token)

    # then — the stale token no longer authenticates
    assert result is None


# ── Journey 6: User publishes a page ───────────────────────────────────────────


async def test_user_publishes_an_html_page_and_gets_a_live_url():
    # given — a signed-in user whose persona id resolves for permanent hosting
    uid = "44444444-4444-4444-4444-444444444444"
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value={"supabase_user_id": "suid-xyz"})

    fake_pages = MagicMock()
    fake_pages.create_page = AsyncMock(return_value={
        "success": True, "url": "https://zynd.io/p/abc123", "slug": "abc123", "title": "Test",
    })

    # when — she asks to publish some HTML as a shareable page
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)), \
         patch.dict("sys.modules", {"app.services.pages_agent": fake_pages}):
        result = await m.publish_page(
            content="<h1>Hello</h1>", title="Test", format="html", uid=uid,
        )

    # then — she gets a live public URL back
    assert result["success"] is True
    assert result["url"] == "https://zynd.io/p/abc123"
    fake_pages.create_page.assert_awaited_once()


# ── Journey 7: Social links (persona features gated off) ───────────────────────


async def test_setting_social_links_is_gated_while_persona_is_disabled():
    # given — persona_enabled is False (the default), so social ops are gated
    pool = MagicMock()

    # when — she tries to save her LinkedIn URL
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)):
        result = await m.set_social_links(linkedin="https://linkedin.com/in/alice", uid="test-uid")

    # then — the op degrades gracefully instead of raising
    assert result["ok"] is False
    assert "coming soon" in result["hint"].lower()


async def test_viewing_socials_returns_empty_when_no_persona_is_linked(packet_dependencies):
    # given — her user row has no supabase_user_id, so no persona profile exists
    _, token = packet_dependencies

    # when — she asks to see her saved social links
    with patch("app.mcp_http.active_context", AsyncMock(return_value=[])):
        result = await m.get_my_context(uid="test-uid", token=token)

    # An empty section is absent from present, not a failed packet.
    assert not any(result["socials"].values())
    assert "socials" not in result["present"]


# Journey 8: Startup packet loading and graceful degradation


async def test_context_packet_loads_with_full_persona_context(packet_dependencies):
    # given — a user with a persona profile, some facts, and a brief
    uid = "55555555-5555-5555-5555-555555555555"
    pool, token = packet_dependencies
    pool.fetchrow = AsyncMock(return_value={
        "display_name": "Alice", "email": "alice@example.com",
        "supabase_user_id": "suid-alice", "socials": {},
    })
    facts = [{"statement": "You're building a Rust microservices platform"}]

    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)), \
         patch("app.mcp_http.active_context", AsyncMock(return_value=facts)), \
         patch("app.services.self_context.persona") as persona_mod, \
         patch("app.mcp_http.brief_tools.read_my_brief", AsyncMock(return_value={"success": True, "content": "Working on ZYND"})) as brief:
        persona_mod.get_status = AsyncMock(return_value={"name": "Alice", "description": "Founder"})
        # when
        packet = await m.get_my_context(uid=uid, token=token)

    assert packet["identity"] == {"name": "Alice", "email": "alice@example.com"}
    assert packet["facts"] == facts
    assert packet["profile"]["description"] == "Founder"
    assert packet["brief"] == "Working on ZYND"
    persona_mod.get_status.assert_awaited_once_with("suid-alice")
    brief.assert_awaited_once_with("suid-alice")


async def test_context_packet_still_loads_when_persona_service_is_down(packet_dependencies):
    # given — the persona service raises, but the rest of ZYND is healthy
    uid = "66666666-6666-6666-6666-666666666666"
    pool, token = packet_dependencies
    pool.fetchrow = AsyncMock(return_value={
        "display_name": "  ", "email": " bob@example.com ",
        "supabase_user_id": "suid-bob", "socials": {},
    })

    with patch("app.mcp_http._get_pool", AsyncMock(return_value=pool)), \
         patch("app.mcp_http.active_context", AsyncMock(return_value=[])), \
         patch("app.services.self_context.persona") as persona_mod, \
         patch("app.mcp_http.brief_tools.read_my_brief", AsyncMock(return_value={"success": False})):
        persona_mod.get_status = AsyncMock(side_effect=RuntimeError("persona service down"))
        # when
        packet = await m.get_my_context(uid=uid, token=token)

    assert packet["identity"]["name"] == "bob"
    assert packet["profile"] is None
    assert packet["brief"] is None
    assert packet["facts"] == []
    assert packet["present"] == ["identity"]
