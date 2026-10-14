"""Provenance on the card, and the evidence sentence staying owner-only."""
import hashlib

import pytest

from app.config import settings
from app.db import get_pool, to_pgvector
from app.services.findability import get_card, get_card_for_owner
from app.services.mock_llm import mock_embed

pytestmark = pytest.mark.integration

SENTENCE = "The user has a tool: Codex"


async def _dev_uid() -> str:
    return await get_pool().fetchval("SELECT id FROM users WHERE email = $1", settings.dev_user_email)


async def _public_fact(uid, predicate, name, *, chunk_system=None, chunk_text=None,
                       source_system="user_confirmed", source="declared"):
    pool = get_pool()
    chunk_id = None
    if chunk_system:
        chunk_id = await pool.fetchval(
            "INSERT INTO trace_chunks (user_id, source_system, raw_text, content_hash) "
            "VALUES ($1,$2,$3,$4) RETURNING id", uid, chunk_system, chunk_text,
            hashlib.sha256(f"{uid}:{chunk_text}".encode()).hexdigest())
    eid = await pool.fetchval(
        "INSERT INTO entities (user_id,canonical_name,entity_type,embedding) "
        "VALUES ($1,$2,'skill_technical',$3::vector) RETURNING id",
        uid, name, to_pgvector(mock_embed(name)))
    await pool.execute(
        "INSERT INTO assertions (user_id,predicate,object_entity_id,confidence,source_system,source,"
        "trace_chunk_id,decay_fn,is_public,approved_at) "
        "VALUES ($1,$2,$3,0.9,$4,$5,$6,'none',true,now())",
        uid, predicate, eid, source_system, source, chunk_id)


async def test_public_card_has_provenance_but_never_evidence(client):
    uid = await _dev_uid()
    await _public_fact(uid, "uses_tool", "Codex", chunk_system="cards_mcp", chunk_text=SENTENCE)

    [fact] = await get_card(get_pool(), str(uid))
    assert fact["provenance"] == "agent"
    assert "evidence" not in fact
    assert SENTENCE not in repr(fact)  # the person's own words must not leak publicly


async def test_owner_view_includes_the_evidence_sentence(client):
    uid = await _dev_uid()
    await _public_fact(uid, "uses_tool", "Codex", chunk_system="cards_mcp", chunk_text=SENTENCE)

    [fact] = await get_card_for_owner(get_pool(), str(uid))
    assert fact["provenance"] == "agent"
    assert fact["evidence"] == SENTENCE


async def test_approved_agent_fact_still_reads_as_agent(client):
    # Approval rewrites the assertion's own source_system to user_confirmed.
    uid = await _dev_uid()
    await _public_fact(uid, "uses_tool", "Codex", chunk_system="cards_mcp",
                       chunk_text=SENTENCE, source_system="user_confirmed", source="declared")
    [fact] = await get_card(get_pool(), str(uid))
    assert fact["provenance"] == "agent"


async def test_fact_without_a_chunk_is_you_with_no_evidence(client):
    uid = await _dev_uid()
    await _public_fact(uid, "has_expertise_in", "Compliance engineering")

    [fact] = await get_card_for_owner(get_pool(), str(uid))
    assert fact["provenance"] == "you"
    assert fact["evidence"] is None


async def test_profile_and_chat_origins(client):
    uid = await _dev_uid()
    await _public_fact(uid, "has_expertise_in", "Backend", chunk_system="persona_seeded",
                       chunk_text="Backend developer at Acme")
    await _public_fact(uid, "is_learning", "Rust", chunk_system="claude",
                       chunk_text="I'm learning Rust", source="inferred", source_system="claude")
    got = {f["object"]: f["provenance"] for f in await get_card(get_pool(), str(uid))}
    assert got == {"Backend": "profile", "Rust": "chat"}
