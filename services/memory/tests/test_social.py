"""Tests for the ZYND<->persona bridge (gated + identity resolution)."""
import pytest

import app.services.social as S
from app.config import settings


async def test_social_disabled_by_default():
    # flag off (default) -> SocialDisabled before any DB/network touch (pool unused)
    with pytest.raises(S.SocialDisabled):
        await S.connect(None, "u1", "u2", "hi")


@pytest.mark.integration
async def test_connect_resolves_ids_and_calls_persona(client, monkeypatch):
    from app.db import get_pool
    pool = get_pool()
    monkeypatch.setattr(settings, "persona_enabled", True)
    me = await pool.fetchval(
        """INSERT INTO users (email, display_name, supabase_user_id) VALUES ('me@x.io','Me','sub-me')
           ON CONFLICT (email) DO UPDATE SET supabase_user_id='sub-me' RETURNING id""")
    tgt = await pool.fetchval(
        """INSERT INTO users (email, display_name, persona_agent_id) VALUES ('t@x.io','Target','zns:abc')
           ON CONFLICT (email) DO UPDATE SET persona_agent_id='zns:abc' RETURNING id""")
    seen = {}
    async def fake_introduce(sub, agent, name, msg):
        seen.update(sub=sub, agent=agent, name=name); return {"thread_id": "th1"}
    monkeypatch.setattr(S.persona, "introduce", fake_introduce)

    res = await S.connect(pool, str(me), str(tgt), "hello")
    assert res["thread_id"] == "th1"
    assert seen == {"sub": "sub-me", "agent": "zns:abc", "name": "Target"}


@pytest.mark.integration
async def test_connect_rejects_target_without_persona(client, monkeypatch):
    from app.db import get_pool
    pool = get_pool()
    monkeypatch.setattr(settings, "persona_enabled", True)
    me = await pool.fetchval(
        """INSERT INTO users (email, display_name, supabase_user_id) VALUES ('me2@x.io','Me2','sub-me2')
           ON CONFLICT (email) DO UPDATE SET supabase_user_id='sub-me2' RETURNING id""")
    tgt = await pool.fetchval(
        """INSERT INTO users (email, display_name) VALUES ('np@x.io','NoPersona')
           ON CONFLICT (email) DO NOTHING RETURNING id""") or await pool.fetchval("SELECT id FROM users WHERE email='np@x.io'")
    with pytest.raises(ValueError):
        await S.connect(pool, str(me), str(tgt), "hi")
