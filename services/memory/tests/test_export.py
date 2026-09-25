import pytest

from app.config import settings
from app.db import get_pool, to_pgvector
from app.services.export import build_jsonld_export, context_slice, _sign

AUTH = {"Authorization": f"Bearer {settings.dev_bearer_token}"}


# ---- Unit ----

def test_sign_is_deterministic_and_payload_sensitive():
    a = [{"predicate": "is_learning", "object": "Rust", "confidence": 0.9}]
    b = [{"predicate": "is_learning", "object": "Go", "confidence": 0.9}]
    assert _sign(a) == _sign(a)
    assert _sign(a) != _sign(b)


# ---- Integration ----

pytestmark_integration = pytest.mark.integration


async def _dev_uid() -> str:
    return await get_pool().fetchval("SELECT id FROM users WHERE email = $1", settings.dev_user_email)


async def _seed(uid, predicate, name, etype, confidence):
    from app.services.mock_llm import mock_embed
    pool = get_pool()
    eid = await pool.fetchval(
        "INSERT INTO entities (user_id,canonical_name,entity_type,embedding) VALUES ($1,$2,$3,$4::vector) RETURNING id",
        uid, name, etype, to_pgvector(mock_embed(name)))
    await pool.execute(
        "INSERT INTO assertions (user_id,predicate,object_entity_id,confidence,source_system,decay_fn) VALUES ($1,$2,$3,$4,'chatgpt','none')",
        uid, predicate, eid, confidence)


@pytest.mark.integration
async def test_jsonld_export_structure(client):
    uid = await _dev_uid()
    await _seed(uid, "is_building", "ML engineer marketplace", "project_venture", 0.9)
    await _seed(uid, "is_learning", "Rust async runtimes", "skill_technical", 0.7)

    packet = await build_jsonld_export(get_pool(), str(uid))

    assert packet["@context"] == "https://zynd.io/schema/v1"
    assert packet["@type"] == "UserContext"
    assert packet["user_id"] == str(uid)
    assert packet["exported_at"]
    assert len(packet["signature"]) == 64  # sha256 hex
    assert len(packet["assertions"]) == 2
    assert packet["assertions"][0]["predicate"] == "is_building"  # highest confidence first


@pytest.mark.integration
async def test_context_slice_ranks_by_topic_relevance(client):
    uid = await _dev_uid()
    await _seed(uid, "is_learning", "Rust async runtimes", "skill_technical", 0.8)
    await _seed(uid, "is_building", "sourdough bread bakery", "project_venture", 0.8)

    slice_ = await context_slice(get_pool(), str(uid), "Rust async performance tuning", k=20)

    assert slice_[0]["object"] == "Rust async runtimes"
    assert slice_[0]["relevance"] > slice_[-1]["relevance"]


@pytest.mark.integration
async def test_context_slice_drops_low_confidence(client):
    uid = await _dev_uid()
    await _seed(uid, "is_learning", "Rust async runtimes", "skill_technical", 0.35)  # below 0.4 floor

    slice_ = await context_slice(get_pool(), str(uid), "Rust async", k=20)
    assert slice_ == []


@pytest.mark.integration
async def test_me_graph_returns_callers_own_facts(client):
    dev_id = await _dev_uid()
    await _seed(dev_id, "is_building", "context graph", "project_venture", 0.8)
    r = await client.get("/me/graph", headers=AUTH)
    assert r.status_code == 200
    objects = {a["object"] for a in r.json()}
    assert "context graph" in objects


@pytest.mark.integration
async def test_export_and_context_endpoints(client):
    dev_id = await _dev_uid()
    await _seed(dev_id, "is_building", "ML engineer marketplace", "project_venture", 0.9)

    exported = await client.get(f"/export/{dev_id}", headers=AUTH)
    assert exported.status_code == 200
    assert exported.json()["@type"] == "UserContext"

    ctx = await client.post(f"/context/{dev_id}", headers=AUTH, json={"topic": "marketplace", "k": 5})
    assert ctx.status_code == 200
    assert isinstance(ctx.json(), list)

    forbidden = await client.get("/export/00000000-0000-0000-0000-000000000000", headers=AUTH)
    assert forbidden.status_code == 403
