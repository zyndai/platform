"""Identity fallback, conditional self-heal, and database JSON representations."""
from unittest.mock import AsyncMock

import pytest

from app.services.self_context import load_self_context, normalize_socials


@pytest.mark.parametrize("display,email,persona_name,expected,heal", [
    (" Ada ", "ada@example.com", "Other", "Ada", False),
    (" \n ", "ada@example.com", " Ada ", "Ada", True),
    (None, " ada@example.com ", " ", "ada", False),
    ("", None, "", "ZYND user", False),
    ("", "@example.com", "", "ZYND user", False),
])
async def test_identity_resolution(monkeypatch, display, email, persona_name, expected, heal):
    pool = AsyncMock()
    pool.fetchrow.return_value = {"display_name": display, "email": email,
                                 "supabase_user_id": "linked-user", "socials": "{}"}
    status = AsyncMock(return_value={"name": persona_name})
    monkeypatch.setattr("app.services.self_context.persona.get_status", status)

    result = await load_self_context(pool, "owner")

    assert result["identity"]["name"] == expected
    pool.fetchrow.assert_awaited_once()
    status.assert_awaited_once_with("linked-user")
    assert pool.execute.await_count == int(heal)
    if heal:
        sql, name, uid = pool.execute.await_args.args
        assert name == "Ada" and uid == "owner"
        assert "display_name IS NULL" in sql and "btrim(display_name) = ''" in sql


async def test_failed_self_heal_preserves_resolved_context(monkeypatch):
    pool = AsyncMock()
    pool.fetchrow.return_value = {"display_name": "", "email": "ada@example.com",
                                 "supabase_user_id": "linked-user", "socials": "{}"}
    pool.execute.side_effect = RuntimeError("write unavailable")
    monkeypatch.setattr("app.services.self_context.persona.get_status",
                        AsyncMock(return_value={"name": "Ada"}))
    result = await load_self_context(pool, "owner")
    assert result["identity"]["name"] == "Ada"


async def test_concurrent_explicit_name_is_not_overwritten(monkeypatch):
    pool = AsyncMock()
    pool.fetchrow.return_value = {"display_name": "", "email": "ada@example.com",
                                 "supabase_user_id": "linked-user", "socials": "{}"}
    stored = {"name": ""}

    async def persona_status(uid):
        stored["name"] = "Explicit name"
        return {"name": "Persona name"}

    async def execute(sql, name, uid):
        assert "AND (display_name IS NULL OR btrim(display_name) = '')" in sql
        if not stored["name"].strip():
            stored["name"] = name
        return "UPDATE 0"

    pool.execute.side_effect = execute
    monkeypatch.setattr("app.services.self_context.persona.get_status", persona_status)
    await load_self_context(pool, "owner")
    assert stored["name"] == "Explicit name"


@pytest.mark.parametrize("stored", [
    {"github": " stored-github ", "twitter": "stored-x"},
    '{"github": " stored-github ", "twitter": "stored-x"}',
])
def test_socials_support_asyncpg_jsonb_and_persona_precedence(stored):
    result = normalize_socials({"profile": {"github": " ", "twitter": " persona-x "}}, stored)
    assert result["github"] == "stored-github"
    assert result["x"] == "persona-x"
    assert "twitter" not in result


@pytest.mark.parametrize("stored", ["invalid json", "[]", "null", None])
def test_invalid_or_empty_stored_socials_are_empty(stored):
    assert not any(normalize_socials(None, stored).values())
