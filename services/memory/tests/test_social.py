"""Tests for the ZYND<->persona bridge (gating, identity resolution, consent gate)."""
import pytest

import app.services.social as S
from app.config import settings


async def test_social_disabled_by_default():
    with pytest.raises(S.SocialDisabled):
        await S.connect(None, "u1", "u2", "hi")


async def _mk(pool, email, name, *, sub=None, agent=None, findable=False):
    uid = await pool.fetchval(
        """INSERT INTO users (email, display_name, supabase_user_id, persona_agent_id)
           VALUES ($1,$2,$3,$4)
           ON CONFLICT (email) DO UPDATE SET supabase_user_id=EXCLUDED.supabase_user_id,
                 persona_agent_id=EXCLUDED.persona_agent_id RETURNING id""",
        email, name, sub, agent)
    if findable:
        eid = await pool.fetchval(
            "INSERT INTO entities (user_id, canonical_name, entity_type) VALUES ($1,'x','skill_domain') RETURNING id", uid)
        await pool.execute(
            """INSERT INTO assertions (user_id, predicate, object_entity_id, confidence, source_system, decay_fn, is_public)
               VALUES ($1,'is_building',$2,0.8,'chatgpt','none',true)""", uid, eid)
    return str(uid)


@pytest.mark.integration
async def test_connect_to_findable_target_calls_persona(client, monkeypatch):
    from app.db import get_pool
    pool = get_pool()
    monkeypatch.setattr(settings, "persona_enabled", True)
    me = await _mk(pool, "me@x.io", "Me", sub="sub-me")
    tgt = await _mk(pool, "t@x.io", "Target", agent="zns:abc", findable=True)
    seen = {}
    async def fake_introduce(sub, agent, name, msg): seen.update(sub=sub, agent=agent); return {"thread_id": "th1"}
    monkeypatch.setattr(S.persona, "introduce", fake_introduce)
    res = await S.connect(pool, me, tgt, "hello")
    assert res["thread_id"] == "th1" and seen == {"sub": "sub-me", "agent": "zns:abc"}


@pytest.mark.integration
async def test_connect_rejects_non_findable_target(client, monkeypatch):
    from app.db import get_pool
    pool = get_pool()
    monkeypatch.setattr(settings, "persona_enabled", True)
    me = await _mk(pool, "me2@x.io", "Me2", sub="sub-me2")
    tgt = await _mk(pool, "priv@x.io", "Private", agent="zns:xyz", findable=False)  # has persona, not findable
    with pytest.raises(ValueError):
        await S.connect(pool, me, tgt, "hi")


async def test_set_social_rejects_bad_url(monkeypatch):
    monkeypatch.setattr(settings, "persona_enabled", True)
    with pytest.raises(ValueError):
        await S.set_social(None, "u", {"linkedin": "javascript:alert(1)"})
