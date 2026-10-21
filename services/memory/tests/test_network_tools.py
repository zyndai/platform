"""MCP tools for saved searches, match controls, report/block and the connection brief."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.mcp_http as m
from app.services import people_discovery as pd
from app.services import people_results as pr
from app.services.mcp_scopes import tool_visible

NET = "app.mcp_http.cards_network_tools"


@pytest.fixture(autouse=True)
def pool():
    with patch("app.mcp_http._get_pool", AsyncMock(return_value=MagicMock())):
        yield


async def test_saved_searches_dispatch_by_action_and_clip_input():
    with patch(f"{NET}.add_saved_search", AsyncMock(return_value={"ok": True})) as add, \
         patch(f"{NET}.remove_saved_search", AsyncMock(return_value={"ok": True})) as remove, \
         patch(f"{NET}.saved_searches", AsyncMock(return_value={"ok": True, "searches": []})) as lst:
        await m.saved_searches(action="add", q="x" * 500, role="investor", label="Seed", uid="u1")
        assert add.await_args.args[2] == "x" * 200 and add.await_args.args[3] == "investor" and add.await_args.args[6] == "Seed"
        await m.saved_searches(action="remove", search_id=" abc ", uid="u1")
        assert remove.await_args.args[2] == "abc"
        await m.saved_searches(uid="u1")
        lst.assert_awaited_once()


@pytest.mark.parametrize("action,kind,remove", [
    ("hide_person", "hide_person", False), ("mute_topic", "mute_topic", False), ("less_like_this", "less_like_this", False),
    ("undo_hide_person", "hide_person", True), ("undo_mute_topic", "mute_topic", True)])
async def test_tune_matches_maps_actions_to_preference_calls(action, kind, remove):
    with patch(f"{NET}.change_preference", AsyncMock(return_value={"ok": True})) as change:
        await m.tune_matches(action=action, value="  crypto  ", uid="u1")
    args, kwargs = change.await_args
    assert args[2:] == (kind, "crypto") and kwargs == {"remove": remove}


async def test_tune_matches_shows_and_rejects_unknown_actions():
    with patch(f"{NET}.preferences", AsyncMock(return_value={"ok": True, "preferences": {}})) as show, \
         patch(f"{NET}.change_preference", AsyncMock()) as change:
        await m.tune_matches(action="show", uid="u1")
        bad = await m.tune_matches(action="delete_everything", value="x", uid="u1")
    show.assert_awaited_once()
    change.assert_not_awaited()
    assert bad["ok"] is False


async def test_report_and_block_use_the_right_endpoint_and_clean_the_handle():
    with patch(f"{NET}.report_card", AsyncMock(return_value={"ok": True})) as report, \
         patch(f"{NET}.block_card", AsyncMock(return_value={"ok": True})) as block:
        await m.report_or_block_card(handle="@spammer", reason="spam", details="d" * 2000, uid="u1")
        assert report.await_args.args[2:4] == ("spammer", "spam") and len(report.await_args.args[4]) == 1000
        await m.report_or_block_card(handle="@spammer", action="block", uid="u1")
        assert block.await_args.args[2] == "spammer"


async def test_connection_brief_passes_the_connection_id_through():
    with patch(f"{NET}.brief", AsyncMock(return_value={"ok": True, "brief": {}})) as brief:
        assert (await m.connection_brief("c-1", uid="u1"))["ok"] is True
    assert brief.await_args.args[2] == "c-1"


def test_the_new_tools_need_the_people_scope():
    for tool in ("saved_searches", "tune_matches", "report_or_block_card", "connection_brief"):
        assert tool_visible(tool, ["people:message"]) and tool_visible(tool, ["user"]) and not tool_visible(tool, ["memory:write"])


# ── preferences and display ───────────────────────────────────────────────────────

def person(handle, headline="", why=(), name=None, skills=()):
    return {"handle": handle, "name": name or handle.title(), "headline": headline, "why": list(why), "skills": list(skills)}


def test_apply_preferences_hides_people_and_mutes_whole_topics_only():
    people = [person("a"), person("b", "Crypto trading lead"), person("c", "Crypto researcher"), person("d", skills=["Trading", "Crypto"])]
    prefs = {"hide_person": ["A"], "mute_topic": ["crypto trading"]}
    assert [p["handle"] for p in pr.apply_preferences(people, prefs)] == ["c"]      # d has both words across its skills
    assert pr.apply_preferences(people, {}) is people and pr.apply_preferences(people, {"mute_topic": ["  "]}) is people


def test_apply_preferences_ignores_topics_inside_longer_words():
    assert len(pr.apply_preferences([person("a", "Cryptography professor")], {"mute_topic": ["crypto"]})) == 1


@pytest.mark.parametrize("days,phrase", [(0, " (this week)"), (7, " (this week)"), (14, " (2 weeks ago)"),
                                          (90, " (3 months ago)"), (None, ""), (-3, ""), ("x", "")])
def test_why_says_how_current_an_approved_fact_is(days, phrase):
    assert pd._why([{"type": "memory", "text": "Backs dev tools", "age_days": days}]) == [f"Approved fact: Backs dev tools{phrase}"]


def test_cards_params_carry_less_like_handles_only():
    q = pd.parse_target_heuristic("investor")
    params = pd.cards_search_params("investor", 5, q, "me", ["dull", "../bad", "boring"])
    assert params["less_like"] == "dull,boring"
    assert "less_like" not in pd.cards_search_params("investor", 5, q)


def test_verified_badges_are_limited_to_known_providers():
    (row,) = pd.shape_cards([{"handle": "ada", "claimed": True, "verified": ["linkedin", "made_up", "github"]}], 5)
    assert row["verified"] == ["linkedin", "github"]
