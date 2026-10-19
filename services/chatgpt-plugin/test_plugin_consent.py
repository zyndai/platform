"""Consent boundaries without an external Redis or Postgres service."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import json
import uuid

import pytest
from fastapi import HTTPException

import plugin_review
from app.config import settings
import plugin_consent as consent

OWNER = str(uuid.uuid4())
OTHER = str(uuid.uuid4())
JTI = str(uuid.uuid4())


class Redis:
    def __init__(self):
        self.data = {}
        self.sets = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    async def delete(self, key):
        self.data.pop(key, None)

    async def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    async def smembers(self, key):
        return self.sets.get(key, set())

    async def srem(self, key, value):
        self.sets.get(key, set()).discard(value)

    async def expire(self, key, ttl):
        return True


class Pool:
    def __init__(self):
        self.consents = {}
        self.facts = []
        self.revoked = False
        self.fail_fact = False

    async def fetch(self, sql, *args):
        assert "FROM assertions" in sql
        return []

    async def fetchval(self, sql, *args):
        if "FROM mcp_clients" in sql:
            return None if self.revoked or args != (JTI, OWNER) else 1
        if "INSERT INTO memory_plugin_consents" in sql:
            proposal, uid, jti, client, action, content_hash, version, decision, status, nonce_hash, expiry = args
            cid = uuid.uuid4()
            self.consents[proposal] = dict(id=cid, user_id=uid, decision=decision,
                                           status=status, nonce_hash=nonce_hash)
            return cid
        if "INSERT INTO memory_plugin_facts" in sql:
            if self.fail_fact:
                raise RuntimeError("database insert failed")
            self.facts.append(args[1])
            return uuid.uuid4()
        raise AssertionError(sql)

    async def fetchrow(self, sql, *args):
        if "FROM memory_plugin_consents" in sql:
            return self.consents.get(args[0])
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        if "pg_advisory_xact_lock" in sql or "UPDATE memory_plugin_consents" in sql:
            return "OK"
        raise AssertionError(sql)

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        before = dict(self.consents)
        try:
            yield
        except BaseException:
            self.consents = before
            raise


async def draft():
    pool, redis = Pool(), Redis()
    proposal = await consent.create_proposal(pool, redis, OWNER, "save_memory", "Exact fact: café.",
                                             source_connection_id=JTI)
    return pool, redis, proposal["id"]


async def test_draft_is_temporary_and_owner_bound():
    pool, redis, proposal_id = await draft()
    assert pool.facts == [] and pool.consents == {}
    assert (await consent.get_review(pool, redis, OWNER, proposal_id))["text"] == "Exact fact: café."
    with pytest.raises(consent.ConsentError) as err:
        await consent.get_review(pool, redis, OTHER, proposal_id)
    assert err.value.status_code == 404
    assert len((await consent.list_pending(pool, redis, OWNER))["data"]) == 1


async def test_exact_save_and_same_nonce_retry():
    pool, redis, proposal_id = await draft()
    nonce = (await consent.preview(pool, redis, OWNER, proposal_id))["nonce"]
    assert await consent.decide(pool, redis, OWNER, proposal_id, nonce, "approve") == {"status": "saved_privately"}
    assert pool.facts == ["Exact fact: café."]
    assert await consent.decide(pool, redis, OWNER, proposal_id, nonce, "approve") == {"status": "saved_privately"}
    assert len(pool.facts) == 1
    with pytest.raises(consent.ConsentError) as err:
        await consent.decide(pool, redis, OWNER, proposal_id, nonce, "reject")
    assert err.value.status_code == 409
    assert (await consent.list_pending(pool, redis, OWNER))["data"] == []


async def test_reject_does_not_store_fact_and_expired_preview_denied():
    pool, redis, proposal_id = await draft()
    nonce = (await consent.preview(pool, redis, OWNER, proposal_id))["nonce"]
    redis.data.pop("plugin:preview:" + __import__("hashlib").sha256(nonce.encode()).hexdigest())
    with pytest.raises(consent.ConsentError):
        await consent.decide(pool, redis, OWNER, proposal_id, nonce, "approve")
    nonce = (await consent.preview(pool, redis, OWNER, proposal_id))["nonce"]
    assert (await consent.decide(pool, redis, OWNER, proposal_id, nonce, "reject"))["status"] == "rejected"
    assert pool.facts == []


async def test_revocation_and_database_failure_fail_closed():
    pool, redis, proposal_id = await draft()
    nonce = (await consent.preview(pool, redis, OWNER, proposal_id))["nonce"]
    pool.revoked = True
    with pytest.raises(consent.ConsentError):
        await consent.decide(pool, redis, OWNER, proposal_id, nonce, "approve")
    pool.revoked = False
    pool.fail_fact = True
    with pytest.raises(RuntimeError):
        await consent.decide(pool, redis, OWNER, proposal_id, nonce, "approve")
    assert pool.consents == {} and pool.facts == []


async def test_expired_and_foreign_nonce_do_not_save():
    pool, redis, proposal_id = await draft()
    nonce = (await consent.preview(pool, redis, OWNER, proposal_id))["nonce"]
    with pytest.raises(consent.ConsentError):
        await consent.decide(pool, redis, OWNER, proposal_id, "wrong", "approve")
    data = json.loads(redis.data[consent._key(proposal_id)])
    data["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    redis.data[consent._key(proposal_id)] = json.dumps(data)
    with pytest.raises(consent.ConsentError):
        await consent.decide(pool, redis, OWNER, proposal_id, nonce, "approve")
    assert pool.facts == []


async def test_web_gate_requires_real_supabase_link(monkeypatch):
    monkeypatch.setattr(settings, "feature_plugin_consent", True, raising=False)
    with pytest.raises(HTTPException) as err:
        await plugin_review._owner("Bearer plugin-jwt")
    assert err.value.status_code == 401
    with patch.object(plugin_review, "supabase_identity", AsyncMock(return_value=("owner@example.com", "Owner", "sub"))), \
         patch.object(plugin_review, "get_pool") as get_pool:
        get_pool.return_value.fetchrow = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as err:
            await plugin_review._owner("Bearer supabase-token")
        assert err.value.status_code == 403
        get_pool.return_value.fetchrow.assert_awaited_once()
        assert "supabase_user_id" in get_pool.return_value.fetchrow.await_args.args[0]
