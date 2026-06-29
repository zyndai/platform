"""Integration tests for M5 matching. MOCK_LLM embeddings are lexical, so users
with identical entity wording get identical vectors (cosine ~1.0). Real
embeddings would match on meaning, not exact words."""
import pytest

from app.config import settings
from app.db import get_pool, to_pgvector
from app.services.matching import match_users, recompute_user_embeddings, search_by_query

pytestmark = pytest.mark.integration

AUTH = {"Authorization": f"Bearer {settings.dev_bearer_token}"}

# Five intent-cluster assertions — all FINDABILITY predicates so they survive the
# v2 matching restriction (predicate, object_name, entity_type).
SHARED_INTENT = [
    ("is_building", "machine learning engineer marketplace", "project_venture"),
    ("is_building", "developer hiring platform india", "project_venture"),
    ("is_seeking", "backend cofounder engineer", "collaborator"),
    ("is_seeking", "early adopter users for marketplace", "collaborator"),
    ("open_to", "co founder collaboration", "collaborator"),
]
DISJOINT_INTENT = [
    ("is_building", "sourdough bread bakery", "project_venture"),
    ("is_building", "watercolor painting studio", "project_venture"),
    ("is_seeking", "yoga teacher class", "collaborator"),
    ("is_seeking", "pottery studio members", "collaborator"),
    ("open_to", "coffee chat gardening", "collaborator"),
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
    # is_public=true: these are seeded findability facts so matching (which only reads
    # the public card) can use them.
    await pool.execute(
        """INSERT INTO assertions (user_id, predicate, object_entity_id, confidence, source_system, decay_fn, is_public)
           VALUES ($1,$2,$3,$4,'chatgpt','none', true)""",
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
    assert bad_cluster.status_code == 200   # v2: unknown cluster falls back to full findability card


# ---- complementary search (find_people / search_by_query) ----

# Words shared with SHARED_INTENT entity names so the lexical MOCK_LLM embedding of
# this target query ranks a SHARED_INTENT user above a DISJOINT_INTENT one.
_TARGET_QUERY = "machine learning engineer marketplace developer hiring backend cofounder"


async def test_search_by_query_ranks_matching_target_first(client):
    pool = get_pool()
    caller = await _make_user("q_caller@example.com")   # no vector — pure searcher
    bob = await _make_user("q_bob@example.com")
    carol = await _make_user("q_carol@example.com")
    await _seed_many(bob, SHARED_INTENT)
    await _seed_many(carol, DISJOINT_INTENT)
    for uid in (bob, carol):
        await recompute_user_embeddings(pool, str(uid))

    results = await search_by_query(pool, str(caller), _TARGET_QUERY, "full_context")
    ids = [r["user_id"] for r in results]

    assert ids and ids[0] == str(bob)                    # target-matching user ranks first
    bob_r = next(r for r in results if r["user_id"] == str(bob))
    carol_r = next((r for r in results if r["user_id"] == str(carol)), None)
    assert carol_r is None or bob_r["similarity"] > carol_r["similarity"]


async def test_search_by_query_excludes_caller(client):
    pool = get_pool()
    caller = await _make_user("q_self@example.com")
    await _seed_many(caller, SHARED_INTENT)              # caller's own profile matches the query
    await recompute_user_embeddings(pool, str(caller))

    results = await search_by_query(pool, str(caller), _TARGET_QUERY, "full_context")
    assert str(caller) not in [r["user_id"] for r in results]   # never return the searcher


async def test_search_by_query_respects_min_assertion_gate(client):
    pool = get_pool()
    caller = await _make_user("q_g_caller@example.com")
    thin = await _make_user("q_thin@example.com")
    # only 2 public assertions -> below the default gate of 5
    await _seed(thin, "is_building", "machine learning engineer marketplace", "project_venture")
    await _seed(thin, "is_seeking", "backend cofounder engineer", "collaborator")
    await recompute_user_embeddings(pool, str(thin))

    results = await search_by_query(pool, str(caller), _TARGET_QUERY, "full_context")
    assert str(thin) not in [r["user_id"] for r in results]


async def test_search_by_query_empty_query_returns_empty(client):
    pool = get_pool()
    caller = await _make_user("q_empty@example.com")
    assert await search_by_query(pool, str(caller), "") == []
    assert await search_by_query(pool, str(caller), "   ") == []


async def test_search_by_query_empty_pool_returns_empty(client):
    # client fixture truncates user_embeddings, so the pool is empty here.
    pool = get_pool()
    caller = await _make_user("q_pool@example.com")
    assert await search_by_query(pool, str(caller), "anyone who can help with growth") == []


async def test_find_people_endpoint(client):
    bob = await _make_user("q_ep_bob@example.com")
    await _seed_many(bob, SHARED_INTENT)
    await recompute_user_embeddings(get_pool(), str(bob))

    ok = await client.get(f"/me/find-people?target={_TARGET_QUERY.replace(' ', '+')}", headers=AUTH)
    assert ok.status_code == 200
    assert isinstance(ok.json(), list)

    missing = await client.get("/me/find-people", headers=AUTH)
    assert missing.status_code == 422   # `target` is required


async def test_publish_persona_findability_makes_user_findable(client):
    from app.services.findability import get_card
    from app.services.persona_ingest import publish_persona_findability

    pool = get_pool()
    uid = await _make_user("persona_pub@example.com")
    status = {
        "deployed": True, "agent_id": "zns:abc",
        "capabilities": ["distribution marketing", "growth experiments", "paid acquisition"],
        "profile": {"organization": "Acme Labs", "location": "Berlin", "interests": ["seo"]},
    }
    published = await publish_persona_findability(pool, str(uid), status)
    assert published >= 5   # 3 expertise + interest + org + location (>= the 5-assertion gate)

    preds = {c["predicate"] for c in await get_card(pool, str(uid))}
    assert {"has_expertise_in", "is_affiliated_with", "is_located_in"} <= preds

    # declare rebuilds the match vector, so the user is immediately in the searchable pool
    found = await search_by_query(
        pool, str(await _make_user("pub_caller@example.com")),
        "growth marketing distribution expert", "full_context")
    assert str(uid) in [r["user_id"] for r in found]

    # idempotent: already has a card -> re-publish is a no-op
    assert await publish_persona_findability(pool, str(uid), status) == 0


async def test_findability_facts_are_public_by_default(client):
    from datetime import datetime, timezone

    from app.models import Turn
    from app.services.ingest import ingest_turns
    from app.worker import chunk_processor

    class _Arq:  # ingest only needs enqueue_job; we run chunk_processor by hand
        async def enqueue_job(self, *a, **k):
            return None

    pool = get_pool()
    uid = await _make_user("pub_default@example.com")
    turn = Turn(role="user",
                content="I am building a developer hiring marketplace and I believe remote work wins.",
                timestamp=datetime.now(timezone.utc))
    await ingest_turns(pool, _Arq(), str(uid), "chatgpt", [turn], min_chars=8)
    chunk_id = await pool.fetchval(
        "SELECT id FROM trace_chunks WHERE user_id=$1 ORDER BY observed_at DESC LIMIT 1", uid)
    await chunk_processor({}, str(chunk_id))   # ctx has no redis -> recompute skipped (fine)

    rows = await pool.fetch(
        "SELECT predicate, is_public FROM assertions WHERE user_id=$1 AND valid_until IS NULL", uid)
    by_pred = {r["predicate"]: r["is_public"] for r in rows}
    assert by_pred.get("is_building") is True    # findability predicate -> public by default
    assert by_pred.get("believes") is False      # everything else -> stays private
