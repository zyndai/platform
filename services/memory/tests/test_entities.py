"""Integration tests for M3 cosine entity resolution (brief §5.3).

With MOCK_LLM the embedding is the hashing trick, so cosine == word-set overlap:
reordered words -> identical vector -> similarity 1.0 -> merge. Real embeddings
would also merge true synonyms ("LLMs" / "large language models").
"""
import pytest

from app.config import settings
from app.db import get_pool
from app.services.entities import resolve_entity

pytestmark = pytest.mark.integration


async def _uid() -> str:
    return await get_pool().fetchval("SELECT id FROM users WHERE email = $1", settings.dev_user_email)


async def test_same_word_set_merges_and_records_alias(client):
    pool = get_pool()
    uid = await _uid()
    async with pool.acquire() as conn:
        id1 = await resolve_entity(conn, uid, "Rust async runtimes", "skill_technical")
        id2 = await resolve_entity(conn, uid, "async runtimes Rust", "skill_technical")

    assert id1 == id2  # merged onto one node
    assert await pool.fetchval("SELECT count(*) FROM entities") == 1
    aliases = await pool.fetchval("SELECT aliases FROM entities WHERE id = $1", id1)
    assert "async runtimes Rust" in aliases


async def test_distinct_names_stay_separate(client):
    pool = get_pool()
    uid = await _uid()
    async with pool.acquire() as conn:
        a = await resolve_entity(conn, uid, "Rust async runtimes", "skill_technical")
        b = await resolve_entity(conn, uid, "Python web frameworks", "skill_technical")

    assert a != b
    assert await pool.fetchval("SELECT count(*) FROM entities") == 2


async def test_same_name_different_type_not_merged(client):
    # Type-scoped: a skill "Rust" must not collapse into a concept "Rust".
    pool = get_pool()
    uid = await _uid()
    async with pool.acquire() as conn:
        skill = await resolve_entity(conn, uid, "Rust", "skill_technical")
        concept = await resolve_entity(conn, uid, "Rust", "concept_topic")

    assert skill != concept
    assert await pool.fetchval("SELECT count(*) FROM entities") == 2


async def test_exact_repeat_does_not_duplicate(client):
    pool = get_pool()
    uid = await _uid()
    async with pool.acquire() as conn:
        first = await resolve_entity(conn, uid, "distributed systems", "concept_field")
        again = await resolve_entity(conn, uid, "distributed systems", "concept_field")

    assert first == again
    assert await pool.fetchval("SELECT count(*) FROM entities") == 1
