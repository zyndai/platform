"""Isolated public OAuth grant races, bindings, and connection revocation."""
import asyncio
import base64
import hashlib
import json
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi import HTTPException

from app import oauth
from app.config import settings
from app.mcp_http import ZyndTokenVerifier
from app.services.mcp_clients import revoke_client


RESOURCE = settings.mcp_resource_url
CLIENT = "public-agent"
CALLBACK = "http://127.0.0.1:49001/callback?flow=oauth"
VERIFIER = "a" * 43
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
USER = "user-1"


class Redis:
    def __init__(self):
        self.store = {}
        self.race_key = None
        self.readers = 0
        self.read_barrier = asyncio.Event()

    async def get(self, key):
        value = self.store.get(key)
        if key == self.race_key:
            self.readers += 1
            if self.readers == 2:
                self.read_barrier.set()
            await asyncio.wait_for(self.read_barrier.wait(), 2)
        else:
            await asyncio.sleep(0)
        return value

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return False
        self.store[key] = value.encode() if isinstance(value, str) else value
        await asyncio.sleep(0)
        return True

    async def getdel(self, key):
        await asyncio.sleep(0)
        return self.store.pop(key, None)

    async def delete(self, key):
        self.store.pop(key, None)


class Pool:
    def __init__(self):
        self.connections = {}
        self.inserts = 0

    async def fetchrow(self, query, *args):
        await asyncio.sleep(0)
        if "allowed_redirect_uris FROM oauth_clients" in query:
            return {"allowed_redirect_uris": [CALLBACK]}
        if "FROM oauth_clients" in query:
            return {"id": args[0]}
        if "FROM mcp_clients WHERE jti" in query:
            return self.connections.get(args[0])
        raise AssertionError(query)

    async def fetchval(self, query, *args):
        assert "tokens_revoked_at FROM users" in query
        return None

    async def execute(self, query, *args):
        await asyncio.sleep(0)
        if "INSERT INTO mcp_clients" in query:
            user_id, label, scopes, jti = args
            self.inserts += 1
            self.connections[jti] = {"id": jti, "user_id": user_id, "label": label,
                                     "scopes": scopes, "revoked_at": None}
            return "INSERT 0 1"
        if "UPDATE mcp_clients SET revoked_at" in query:
            jti, user_id = args
            row = self.connections.get(jti)
            if row and row["user_id"] == user_id and row["revoked_at"] is None:
                row["revoked_at"] = "revoked"
                return "UPDATE 1"
            return "UPDATE 0"
        if "UPDATE mcp_clients SET last_used_at" in query:
            return "UPDATE 1"
        raise AssertionError(query)


def request(redis):
    return type("Request", (), {"app": type("App", (), {
        "state": type("State", (), {"arq": redis})()})()})()


def response_data(response):
    return json.loads(response.body)


async def signed_request(state="original-state", client_id=CLIENT):
    response = await oauth.authorize(client_id=client_id, redirect_uri=CALLBACK,
                                     state=state, scope="user", code_challenge=CHALLENGE,
                                     code_challenge_method="S256")
    return parse_qs(urlsplit(response.headers["location"]).query)["zynd_oauth"][0]


async def approval(redis, state="original-state", client_id=CLIENT):
    signed = await signed_request(state, client_id)
    response = await oauth.complete(request(redis), oauth._CompleteRequest(
        req=signed, supabase_token="mock-session", decision="approve"))
    callback = parse_qs(urlsplit(response_data(response)["redirect_url"]).query)
    assert callback["state"] == [state]
    return callback["code"][0]


async def exchange(redis, code, client_id=CLIENT, **changes):
    args = dict(grant_type="authorization_code", client_id=client_id, client_secret="",
                code=code, redirect_uri=CALLBACK, code_verifier=VERIFIER, resource=RESOURCE,
                scope="user", refresh_token="")
    args.update(changes)
    return await oauth.token(request(redis), **args)


async def refresh(redis, token, client_id=CLIENT, **changes):
    args = dict(grant_type="refresh_token", client_id=client_id, client_secret="",
                code="", redirect_uri="", code_verifier="", refresh_token=token,
                resource="", scope="")
    args.update(changes)
    return await oauth.token(request(redis), **args)


@pytest.fixture
def grants():
    redis, pool = Redis(), Pool()
    with patch("app.oauth.get_pool", return_value=pool), \
         patch("app.mcp_http._get_pool", new_callable=AsyncMock, return_value=pool), \
         patch("app.oauth.supabase_identity", new_callable=AsyncMock,
               return_value=("owner@example.test", "Owner", "supabase-sub")), \
         patch("app.services.users.find_user", new_callable=AsyncMock, return_value=USER), \
         patch("app.services.persona.link_user", new_callable=AsyncMock, return_value=None):
        yield redis, pool


@pytest.mark.parametrize("decisions", [("approve", "approve"), ("approve", "deny"), ("deny", "deny")])
async def test_simultaneous_decisions_use_one_sealed_nonce(grants, decisions):
    redis, _ = grants
    signed = await signed_request()
    async def decide(value):
        return await oauth.complete(request(redis), oauth._CompleteRequest(
            req=signed, supabase_token="mock-session", decision=value))
    results = await asyncio.gather(*(decide(d) for d in decisions), return_exceptions=True)
    successes = [(decision, response_data(r)["redirect_url"])
                 for decision, r in zip(decisions, results) if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(successes) == len(failures) == 1
    assert isinstance(failures[0], HTTPException) and failures[0].status_code == 400
    winner, url = successes[0]
    callback = parse_qs(urlsplit(url).query)
    assert callback["state"] == ["original-state"]
    assert ("code" in callback) == (winner == "approve")
    assert callback.get("error", []) == (["access_denied"] if winner == "deny" else [])
    assert sum(":code:" in key for key in redis.store) == int("code" in callback)
    with pytest.raises(HTTPException):
        await decide("approve")


async def test_concurrent_code_redemption_issues_one_connection_and_pair(grants):
    redis, pool = grants
    code = await approval(redis)
    redis.race_key = oauth._grant_key("code", code)
    results = await asyncio.gather(exchange(redis, code), exchange(redis, code), return_exceptions=True)
    successes = [response_data(r) for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]
    assert redis.readers == 2
    assert len(successes) == len(failures) == 1
    assert isinstance(failures[0], HTTPException) and failures[0].detail == "invalid_grant"
    assert pool.inserts == len(pool.connections) == 1
    pair = successes[0]
    assert pair["access_token"] and pair["refresh_token"]
    assert pair["resource"] == RESOURCE and pair["scope"] == "user"
    assert pair["expires_in"] == settings.access_token_ttl_seconds
    claims = jwt.decode(pair["access_token"], settings.jwt_secret, algorithms=["HS256"],
                        audience=RESOURCE, issuer=settings.public_base_url.rstrip("/"))
    assert claims["jti"] in pool.connections and claims["scp"] == ["user"]


async def test_concurrent_refresh_rotates_once(grants):
    redis, pool = grants
    pair = response_data(await exchange(redis, await approval(redis)))
    refresh_jti = jwt.decode(pair["refresh_token"], settings.jwt_secret, algorithms=["HS256"],
                             audience=RESOURCE, issuer=settings.public_base_url.rstrip("/"))["jti"]
    redis.race_key = oauth._grant_key("refresh", refresh_jti)
    results = await asyncio.gather(refresh(redis, pair["refresh_token"]),
                                   refresh(redis, pair["refresh_token"]), return_exceptions=True)
    successes = [response_data(r) for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]
    assert redis.readers == 2
    assert len(successes) == len(failures) == 1
    assert isinstance(failures[0], HTTPException) and failures[0].detail == "invalid_grant"
    assert successes[0]["refresh_token"] != pair["refresh_token"]
    assert successes[0]["access_token"] and successes[0]["scope"] == "user"
    assert successes[0]["resource"] == RESOURCE
    assert pool.inserts == 1


@pytest.mark.parametrize("changes", [
    {"client_id": "other-agent"}, {"redirect_uri": CALLBACK + "/sibling"},
    {"redirect_uri": CALLBACK.replace("49001", "49002")},
    {"code_verifier": "wrong" * 9}, {"code_verifier": "z" * 43},
    {"resource": "https://elsewhere.example/mcp"}, {"scope": "user ingest"},
])
async def test_wrong_code_binding_does_not_consume_then_valid_succeeds(grants, changes):
    redis, pool = grants
    code = await approval(redis)
    with pytest.raises(HTTPException) as error:
        await exchange(redis, code, **changes)
    assert error.value.detail == "invalid_grant"
    assert oauth._grant_key("code", code) in redis.store
    assert pool.inserts == 0
    assert response_data(await exchange(redis, code))["refresh_token"]


@pytest.mark.parametrize("changes", [
    {"client_id": "other-agent"}, {"resource": "https://elsewhere.example/mcp"},
    {"scope": "user ingest"},
])
async def test_wrong_refresh_binding_does_not_consume_then_valid_succeeds(grants, changes):
    redis, _ = grants
    pair = response_data(await exchange(redis, await approval(redis)))
    with pytest.raises(HTTPException) as error:
        await refresh(redis, pair["refresh_token"], **changes)
    assert error.value.detail == "invalid_grant"
    assert response_data(await refresh(redis, pair["refresh_token"]))["refresh_token"] != pair["refresh_token"]


async def test_revoke_one_of_two_public_connections_blocks_only_its_access_and_refresh(grants):
    redis, pool = grants
    first = response_data(await exchange(redis, await approval(redis, client_id="agent-one"), client_id="agent-one"))
    second = response_data(await exchange(redis, await approval(redis, client_id="agent-two"), client_id="agent-two"))
    first_jti, second_jti = (jwt.decode(pair["access_token"], settings.jwt_secret,
                                         algorithms=["HS256"], audience=RESOURCE)["jti"]
                             for pair in (first, second))
    assert first_jti != second_jti and pool.inserts == 2
    verifier = ZyndTokenVerifier()
    assert await verifier.verify_token(first["access_token"]) is not None
    assert await verifier.verify_token(second["access_token"]) is not None
    assert await revoke_client(pool, USER, first_jti)
    assert await verifier.verify_token(first["access_token"]) is None
    with pytest.raises(HTTPException) as error:
        await refresh(redis, first["refresh_token"], client_id="agent-one")
    assert error.value.detail == "invalid_grant"
    assert await verifier.verify_token(second["access_token"]) is not None
    replacement = response_data(await refresh(redis, second["refresh_token"], client_id="agent-two"))
    assert await verifier.verify_token(replacement["access_token"]) is not None
    assert jwt.decode(replacement["access_token"], settings.jwt_secret,
                      algorithms=["HS256"], audience=RESOURCE)["jti"] == second_jti
