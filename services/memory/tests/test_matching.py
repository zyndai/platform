"""Integration tests for M5 matching. MOCK_LLM embeddings are lexical, so users
with identical entity wording get identical vectors (cosine ~1.0). Real
embeddings would match on meaning, not exact words."""
import pytest

from app.config import settings
from app.db import get_pool, to_pgvector
from app.services.matching import match_users, recompute_user_embeddings

pytestmark = pytest.mark.integration

AUTH = {"Authorization": f"Bearer {settings.dev_bearer_token}"}

# Five intent-cluster assertions (predicate, object_name, entity_type).
SHARED_INTENT = [
    ("is_building", "machine learning engineer marketplace", "project_venture"),
    ("is_working_on", "API rate limit fix", "project_assignment"),
    ("intends_to", "raise seed round", "intent_project"),
    ("is_seeking", "backend cofounder engineer", "collaborator"),
    ("is_building", "developer hiring platform india", "project_venture"),
]
DISJOINT_INTENT = [
    ("is_building", "sourdough bread bakery", "project_venture"),
    ("is_working_on", "garden vegetable patch", "project_assignment"),
    ("intends_to", "run marathon race", "intent_project"),
    ("is_seeking", "yoga teacher class", "collaborator"),
    ("is_building", "watercolor painting studio", "project_venture"),
]


async def _make_user(email: str) -> str:
    return await get_pool().fetchval(
        """INSERT INTO users (email, display_name) VALUES ($1, $1)
           ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email RETURNING id""",
        email,
    )


async def _seed(uid: str, predicate: str, name: str, etype: str, confidence: float = 0.8):
    from app.services.mock_llm import mock_embed
    pool = get_pool()
    eid = await pool.fetchval(
        "INSERT INTO entities (user_id, canonical_name, entity_type, embedding) VALUES ($1,$2,$3,$4::vector) RETURNING id",
        uid, name, etype, to_pgvector(mock_embed(name)),
    )
    await pool.execute(
        """INSERT INTO assertions (user_id, predicate, object_entity_id, confidence, source_system, decay_fn)
           VALUES ($1,$2,$3,$4,'chatgpt','none')""",
        uid, predicate, eid, confidence,
    )


async def _seed_many(uid: str, rows):
    for predicate, name, etype in rows:
        await _seed(uid, predicate, name, etype)


async def test_recompute_builds_weighted_cluster_vectors(client):
    pool = get_pool()
    uid = await _make_user("recompute@example.com")
    await _seed_many(uid, SHARED_INTENT)

    built = await recompute_user_embeddings(pool, str(uid))

    assert built["intent_cluster"] == 5
    assert built["full_context"] == 5     # all predicates
    assert "belief_cluster" not in built  # no belief assertions -> no vector
    row = await pool.fetchrow(
        "SELECT assertion_count FROM user_embeddings WHERE user_id=$1 AND cluster_type='intent_cluster'", uid)
    assert row["assertion_count"] == 5


async def test_match_ranks_overlapping_user_first(client):
    pool = get_pool()
    alice = await _make_user("alice_m@example.com")
    bob = await _make_user("bob_m@example.com")      # same wording as alice
    carol = await _make_user("carol_m@example.com")  # unrelated wording

    await _seed_many(alice, SHARED_INTENT)
    await _seed_many(bob, SHARED_INTENT)
    await _seed_many(carol, DISJOINT_INTENT)
    for uid in (alice, bob, carol):
        await recompute_user_embeddings(pool, str(uid))

    matches = await match_users(pool, str(alice), "intent_cluster")
    ids = [m["user_id"] for m in matches]

    assert ids[0] == str(bob)              # most similar
    assert matches[0]["similarity"] > 0.99
    carol_match = next(m for m in matches if m["user_id"] == str(carol))
    assert carol_match["similarity"] < matches[0]["similarity"]


async def test_match_respects_min_assertion_gate(client):
    pool = get_pool()
    alice = await _make_user("alice_g@example.com")
    thin = await _make_user("thin@example.com")

    await _seed_many(alice, SHARED_INTENT)
    # thin user: only 2 intent assertions -> below the default gate of 5
    await _seed(thin, "is_building", "machine learning engineer marketplace", "project_venture")
    await _seed(thin, "intends_to", "raise seed round", "intent_project")
    for uid in (alice, thin):
        await recompute_user_embeddings(pool, str(uid))

    matches = await match_users(pool, str(alice), "intent_cluster")
    assert str(thin) not in [m["user_id"] for m in matches]


async def test_match_excludes_self(client):
    pool = get_pool()
    uid = await _make_user("solo@example.com")
    await _seed_many(uid, SHARED_INTENT)
    await recompute_user_embeddings(pool, str(uid))

    matches = await match_users(pool, str(uid), "intent_cluster")
    assert str(uid) not in [m["user_id"] for m in matches]


async def test_match_endpoint_auth_and_validation(client):
    dev_id = await get_pool().fetchval("SELECT id FROM users WHERE email=$1", settings.dev_user_email)

    ok = await client.get(f"/match/{dev_id}", headers=AUTH)
    assert ok.status_code == 200
    assert isinstance(ok.json(), list)

    forbidden = await client.get("/match/00000000-0000-0000-0000-000000000000", headers=AUTH)
    assert forbidden.status_code == 403

    bad_cluster = await client.get(f"/match/{dev_id}?cluster_type=bogus", headers=AUTH)
    assert bad_cluster.status_code == 400
