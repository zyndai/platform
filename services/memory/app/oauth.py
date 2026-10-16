"""OAuth2 authorization-code server for ChatGPT Action AND Claude OAuth 2.1.

Every client is handed to the self-hosted auth page on the memory layer
(`{public_base_url}/oauth/login`) — the layer stays platform-agnostic, with no
cards/persona dependency. The page signs the user in through Supabase (Google/
LinkedIn OIDC, the providers already trusted by app/supabase_auth.py) and POSTs
the session to /oauth/complete, which verifies the identity, resolves the
memory user, mints an auth code and redirects back to the client.

MCP connector clients (Claude DCR/CIMD, ChatGPT connector) are lookup-only:
no existing memory user → 401, never create. Legacy confidential clients
(ChatGPT Action, Hermes Deployer) keep create-on-first-seen semantics.

Both flows issue the same ZYND HS256 JWT family. Connector flows additionally:
  - RFC 8707: the `resource` indicator is validated at /authorize, sealed into
    the signed request, bound to the code, echoed at /token, and becomes the
    token audience (iss = AS issuer = PUBLIC_BASE_URL).
  - RFC 9207: an empty `iss` authorize param echoes the issuer in the callback.
  - RFC 6749 refresh rotation: public clients get single-use rotated refresh
    tokens.

Claude Connectors (OAuth 2.1 with PKCE + DCR/CIMD) put code_challenge on the
signed request so /oauth/token can still check the verifier. The older
Supabase-direct Google path (/oauth/callback + Redis state_id) remains for
in-flight handoffs only.
"""
import base64
import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
import socket
import ssl
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit

import httpx
import httpcore
import jwt
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from app.auth import (
    issue_access_token,
    issue_connector_access_token,
    issue_personal_token,
    issue_refresh_token,
    issue_rotating_refresh_token,
    verify_refresh_meta,
)
from app.config import settings
from app.services.mcp_scopes import PLUGIN_SCOPES
from app.db import get_pool
from app.supabase_auth import supabase_identity

logger = logging.getLogger("zynd.oauth")

router = APIRouter(prefix="/oauth", tags=["oauth"])


def _log_token_diag(token: str) -> None:
    """Diagnostic for a failed /oauth/complete: decode the Supabase JWT WITHOUT
    verifying (read-only) to surface why identity failed — chiefly an expired token,
    the common case when a returning browser session sends a stale access token."""
    try:
        claims = jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
        exp = claims.get("exp")
        now = int(datetime.now(timezone.utc).timestamp())
        logger.warning(
            "oauth/complete identity failed: expired=%s exp=%s now=%s provider=%s has_email=%s",
            (exp is not None and exp < now), exp, now,
            (claims.get("app_metadata") or {}).get("provider"), claims.get("email") is not None,
        )
    except Exception as exc:
        logger.warning("oauth/complete identity failed; token undecodable: %s", exc)

_CODE_PREFIX = "oauth:code:"
_PKCE_PREFIX = "oauth:pkce:"
_STATE_PREFIX = "oauth:state:"    # stored OAuth params for the Supabase-direct flow
_GRANT_PREFIX = "oauth:v2:"  # issuer and resource are included below for shared Redis
_CODE_TTL_SECONDS = 600
_OAUTH_REQ_TTL = 600  # the signed authorize request is valid for 10 minutes
_STATE_TTL_SECONDS = 600  # stored state TTL for the Supabase-direct flow


# ── Redirect URI validation ─────────────────────────────────────────────────────

def _allowed_origins() -> set[tuple[str, str | None]]:
    return {(u.scheme, u.hostname) for u in map(urlsplit, settings.allowed_redirect_prefixes)}


def _check_redirect_uri(redirect_uri: str) -> None:
    try:
        parsed = urlsplit(redirect_uri)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="redirect_uri not allowed") from exc
    if not _valid_redirect_parts(parsed):
        raise HTTPException(status_code=400, detail="redirect_uri not allowed")
    if (parsed.scheme, parsed.hostname) not in _allowed_origins():
        raise HTTPException(status_code=400, detail="redirect_uri not allowed")
    if not any(redirect_uri.startswith(p) and (
        len(redirect_uri) == len(p) or p.endswith("/") or
        redirect_uri[len(p)] in ("/", "?") or
        (redirect_uri[len(p)] == ":" and urlsplit(p).hostname in ("localhost", "127.0.0.1", "::1"))
    ) for p in settings.allowed_redirect_prefixes):
        raise HTTPException(status_code=400, detail="redirect_uri not allowed")


def _valid_redirect_parts(parsed) -> bool:
    try:
        loopback = parsed.hostname in ("localhost", "127.0.0.1", "::1")
        return bool((parsed.scheme == "https" or (parsed.scheme == "http" and loopback)) and parsed.hostname and
                    parsed.port != 0 and parsed.username is None and
                    parsed.password is None and not parsed.fragment)
    except ValueError:
        return False


def _check_dcr_redirect_uri(redirect_uri: str, allowed_uris: list[str]) -> bool:
    """Validate that a redirect_uri belongs to a registered DCR client.

    Per RFC 8252 Section 7.3, any port is allowed for localhost / 127.0.0.1
    loopback redirect URIs — the authorization server MUST accept any port number
    for these addresses. This allows Claude Code's ephemeral-port loopback redirect."""
    try:
        parsed = urlsplit(redirect_uri)
    except ValueError:
        return False
    if not _valid_redirect_parts(parsed):
        return False
    is_loopback = parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
    for allowed in allowed_uris:
        try:
            allowed_parsed = urlsplit(allowed)
        except ValueError:
            continue
        if not _valid_redirect_parts(allowed_parsed):
            continue
        if parsed.scheme != allowed_parsed.scheme:
            continue
        if parsed.hostname != allowed_parsed.hostname:
            continue
        if not is_loopback and parsed.port != allowed_parsed.port:
            continue
        if parsed.path == allowed_parsed.path and parsed.query == allowed_parsed.query:
            return True
    return False


# ── Client ID Metadata Document (draft-parecki-oauth-client-id-metadata-document) ──
# Spec: the client_id is a URL; the authorization server fetches that URL to
# obtain the client's metadata. The document MUST declare a client_id field that
# equals the URL it was fetched from (self-consistency) and a redirect_uris list.
#
# Security: the fetch URL comes from an unauthenticated caller → SSRF-shaped.
# We restrict to https://, block private/loopback hostnames by literal and IP,
# use a short timeout with no redirects, and cap the response at 64 KB.

_METADATA_FETCH_TIMEOUT = 5.0  # seconds
_METADATA_MAX_BYTES = 65_536   # 64 KB hard cap before JSON parsing
_METADATA_CACHE_TTL = 300      # 5 minutes — short enough to pick up revoked redirect_uris
_METADATA_CACHE_MAX = 256      # max entries; evict expired then oldest

# {url: (expires_monotonic, document_dict)}
_metadata_cache: dict[str, tuple[float, dict]] = {}

def _hostname_is_private(hostname: str) -> bool:
    """True for loopback/private hostnames that must not be reached server-side."""
    if hostname.lower() in ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback") or hostname.lower().endswith(".localhost"):
        return True
    try:
        addr = ipaddress.ip_address(hostname)
        return not addr.is_global
    except ValueError:
        return False


class _PinnedBackend(httpcore.AsyncNetworkBackend):
    """Pin the validated addresses at TCP connect; TLS still verifies the URL host."""

    def __init__(self, host: str, addresses: list[str]):
        self.host = host
        self.addresses = addresses
        self.backend = httpcore._backends.auto.AutoBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if host.lower().rstrip(".") != self.host:
            raise OSError("metadata host changed")
        last = None
        for address in self.addresses:
            try:
                return await self.backend.connect_tcp(address, port, timeout, local_address, socket_options)
            except OSError as exc:
                last = exc
        raise last or OSError("metadata address unavailable")

    async def connect_unix_socket(self, *args, **kwargs):
        raise OSError("unix sockets unavailable")

    async def sleep(self, seconds):
        await self.backend.sleep(seconds)


async def _metadata_addresses(host: str, port: int) -> list[str]:
    import asyncio
    try:
        records = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM), timeout=_METADATA_FETCH_TIMEOUT)
    except (OSError, asyncio.TimeoutError) as exc:
        raise HTTPException(status_code=400, detail="client_id metadata document unreachable") from exc
    addresses = list(dict.fromkeys(record[4][0] for record in records))
    if not addresses or any(_hostname_is_private(addr) for addr in addresses):
        raise HTTPException(status_code=400, detail="client_id URL must not point to a private host")
    return addresses


async def _fetch_metadata_document(client_id_url: str) -> dict:
    """Fetch and validate an OAuth Client ID Metadata Document.

    Enforces:
    - HTTPS scheme only (no HTTP, no other schemes).
    - Non-private, non-loopback hostname.
    - Short connect+read timeout with no redirects.
    - 64 KB hard cap on the response body.
    - JSON Content-Type.
    - document.client_id must equal client_id_url (prevents relay attacks).
    - document.redirect_uris must be a non-empty list.
    """
    try:
        parsed = urlsplit(client_id_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid client_id URL") from exc
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="client_id must be an https:// URL")
    try:
        valid_url = parsed.hostname and not parsed.username and not parsed.password and not parsed.fragment and parsed.port in (None, 443)
    except ValueError:
        valid_url = False
    if not valid_url:
        raise HTTPException(status_code=400, detail="client_id URL has no hostname")
    if _hostname_is_private(parsed.hostname):
        raise HTTPException(status_code=400, detail="client_id URL must not point to a private host")

    now = time.monotonic()
    cached = _metadata_cache.get(client_id_url)
    if cached and cached[0] > now:
        return cached[1]

    try:
        async with asyncio.timeout(_METADATA_FETCH_TIMEOUT):
            addresses = await _metadata_addresses(parsed.hostname.lower().rstrip("."), 443)
            transport = httpx.AsyncHTTPTransport(trust_env=False)
            await transport._pool.aclose()
            transport._pool = httpcore.AsyncConnectionPool(
                ssl_context=ssl.create_default_context(), network_backend=_PinnedBackend(parsed.hostname.lower().rstrip("."), addresses),
                max_connections=1, max_keepalive_connections=0)
            async with httpx.AsyncClient(transport=transport, trust_env=False,
                                         timeout=httpx.Timeout(_METADATA_FETCH_TIMEOUT),
                                         follow_redirects=False) as client:
                async with client.stream("GET", client_id_url, headers={"Accept": "application/json", "Accept-Encoding": "identity"}) as resp:
                    if resp.status_code != 200:
                        raise HTTPException(status_code=400, detail=f"client_id metadata fetch returned {resp.status_code}")
                    if "json" not in resp.headers.get("content-type", "").lower():
                        raise HTTPException(status_code=400, detail="client_id metadata document is not JSON")
                    body = bytearray()
                    if resp.headers.get("content-encoding", "identity").lower() != "identity":
                        raise HTTPException(status_code=400, detail="encoded metadata document unsupported")
                    async for chunk in resp.aiter_raw(chunk_size=8192):
                        if len(body) + len(chunk) > _METADATA_MAX_BYTES:
                            raise HTTPException(status_code=400, detail="client_id metadata document exceeds size limit")
                        body.extend(chunk)
    except TimeoutError as exc:
        raise HTTPException(status_code=400, detail="client_id metadata fetch timed out") from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=400, detail="client_id metadata fetch timed out") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=400, detail="client_id metadata document unreachable") from exc

    try:
        doc = json.loads(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="client_id metadata document is not valid JSON") from exc

    if not isinstance(doc, dict):
        raise HTTPException(status_code=400, detail="client_id metadata document must be a JSON object")

    # Self-consistency: document must declare client_id equal to the URL it was fetched from.
    # Without this check an attacker at https://evil.com/meta could claim client_id of
    # https://trusted.example/meta.
    if doc.get("client_id") != client_id_url:
        raise HTTPException(status_code=400, detail="client_id metadata document client_id mismatch")

    redirect_uris = doc.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        raise HTTPException(status_code=400, detail="client_id metadata document missing redirect_uris")
    if not all(isinstance(uri, str) and _check_dcr_redirect_uri(uri, [uri]) for uri in redirect_uris):
        raise HTTPException(status_code=400, detail="invalid metadata redirect_uris")

    # Cache the validated document. Evict expired entries first; if still at cap,
    # remove the oldest (dict insertion order is preserved in Python 3.7+).
    if len(_metadata_cache) >= _METADATA_CACHE_MAX:
        expired = [k for k, (exp, _) in _metadata_cache.items() if exp <= now]
        for k in expired:
            _metadata_cache.pop(k, None)
        if len(_metadata_cache) >= _METADATA_CACHE_MAX:
            _metadata_cache.pop(next(iter(_metadata_cache)), None)

    _metadata_cache[client_id_url] = (now + _METADATA_CACHE_TTL, doc)
    return doc


def _oauth_clients() -> dict[str, str]:
    """Registered confidential clients: {client_id: client_secret}. Two today —
    the ChatGPT Action and the Hermes Deployer."""
    return {
        settings.oauth_client_id: settings.oauth_client_secret,
        settings.deployer_oauth_client_id: settings.deployer_oauth_client_secret,
    }


def _is_known_client(client_id: str) -> bool:
    # Compare against every id (no early return) so the check is constant-time
    # regardless of which client_id was supplied.
    known = False
    for cid in _oauth_clients():
        known |= hmac.compare_digest(client_id, cid)
    return known


def _is_deployer_client(client_id: str) -> bool:
    return hmac.compare_digest(client_id, settings.deployer_oauth_client_id)


def _is_plugin_client(client_id: str) -> bool:
    return bool(settings.plugin_oauth_client_id and
                hmac.compare_digest(client_id, settings.plugin_oauth_client_id))


def _public_scope(client_id: str) -> str:
    return " ".join(PLUGIN_SCOPES) if _is_plugin_client(client_id) else "user"


def _plugin_callbacks() -> list[str]:
    callbacks = [uri.strip() for uri in settings.plugin_oauth_redirect_uris.split(",") if uri.strip()]
    if (not callbacks or not settings.feature_s09_mcp_clients or
            settings.plugin_oauth_client_id in _oauth_clients() or
            any(not _valid_redirect_parts(urlsplit(uri)) or urlsplit(uri).scheme != "https"
                for uri in callbacks)):
        raise HTTPException(status_code=400, detail="plugin OAuth client is not configured")
    return callbacks


def _code_user_id(stored: str) -> str:
    """Extract the user_id from a stored authorization code. New codes are JSON
    {user_id, redirect_uri}; legacy/pre-rollout codes are a bare user_id string."""
    try:
        parsed = json.loads(stored)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        return str(parsed["user_id"])
    return stored


def _resolve_code_user(stored: str, redirect_uri: str) -> str:
    """Like _code_user_id, but also enforces the redirect_uri binding (RFC 6749
    §4.1.3) for confidential clients (ChatGPT / Hermes Deployer): the code can only
    be redeemed with the exact redirect_uri it was issued for, so a leaked code
    cannot be exchanged against a different (attacker) redirect_uri. PKCE clients
    are bound by code_verifier instead, so they use _code_user_id. Legacy
    bare-string codes carry no binding. Raises ValueError on mismatch → invalid_grant.
    """
    try:
        parsed = json.loads(stored)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        if not hmac.compare_digest(redirect_uri, parsed.get("redirect_uri", "")):
            raise ValueError("redirect_uri does not match the authorization request")
        return str(parsed["user_id"])
    return stored


def _check_client(client_id: str, client_secret: str) -> None:
    ok = False
    for cid, csecret in _oauth_clients().items():
        # Evaluate BOTH comparisons before combining: `and` would short-circuit
        # the secret check when the id mismatches, leaking (via timing) which
        # client_ids are registered.
        id_ok = hmac.compare_digest(client_id, cid)
        secret_ok = hmac.compare_digest(client_secret, csecret)
        ok |= id_ok and secret_ok
    if not ok:
        raise HTTPException(status_code=401, detail="invalid client credentials")


# ── PKCE utilities (RFC 7636) ───────────────────────────────────────────────────

def _verify_code_challenge(verifier: str, challenge: str, method: str = "S256") -> bool:
    """Validate a PKCE code_verifier against its stored challenge."""
    if method == "S256" and re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return hmac.compare_digest(expected, challenge)
    elif method == "plain":
        return hmac.compare_digest(verifier, challenge)
    return False


async def _store_pkce_params(redis, code: str, challenge: str, method: str) -> None:
    """Store PKCE challenge alongside the auth code in Redis."""
    await redis.set(
        f"{_PKCE_PREFIX}{code}",
        json.dumps({"challenge": challenge, "method": method}),
        ex=_CODE_TTL_SECONDS + 60,
    )


async def _get_pkce_params(redis, code: str) -> tuple[str, str] | None:
    """Retrieve PKCE challenge + method for a code. Returns None if not PKCE."""
    raw = await redis.get(f"{_PKCE_PREFIX}{code}")
    if raw is None:
        return None
    data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
    return data["challenge"], data["method"]


async def _clear_pkce_params(redis, code: str) -> None:
    await redis.delete(f"{_PKCE_PREFIX}{code}")


# ── OAuth state storage (for Supabase-direct flow) ──────────────────────────────

async def _store_oauth_state(redis, state_id: str, state: dict) -> None:
    """Store OAuth authorize params in Redis for the Supabase-direct flow.
    Retrieved by /oauth/complete when the callback fires."""
    await redis.set(
        f"{_STATE_PREFIX}{state_id}",
        json.dumps(state),
        ex=_STATE_TTL_SECONDS,
    )


async def _get_oauth_state(redis, state_id: str) -> dict | None:
    raw = await redis.get(f"{_STATE_PREFIX}{state_id}")
    if raw is None:
        return None
    return json.loads(raw.decode() if isinstance(raw, bytes) else raw)


async def _clear_oauth_state(redis, state_id: str) -> None:
    await redis.delete(f"{_STATE_PREFIX}{state_id}")


# ── Authorize request signing (ChatGPT/persona legacy flow only) ────────────────

def _sign_oauth_request(
    redirect_uri: str, state: str, scope: str,
    code_challenge: str = "", code_challenge_method: str = "",
    resource: str = "", create_user: bool = True, iss_supported: bool = False,
    client_id: str = "", client_name: str = "",
) -> str:
    """Sign the authorize params so they survive the round-trip through the
    auth page without trusting client-supplied params. PKCE fields ride along
    so Claude can redeem the code with its verifier. `resource` (RFC 8707) is
    validated at /authorize and bound to the minted code and token audience.
    `create_user=false` makes /complete lookup-only (MCP connector path).
    `iss_supported` echoes the AS issuer per RFC 9207 (ChatGPT stable redirect)."""
    return jwt.encode(
        {
            "typ": "oauth_req",
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": scope,
            "client_id": client_id,
            "client_name": client_name,
            "nonce": secrets.token_urlsafe(24),
            "iss": settings.public_base_url.rstrip("/"),
            "aud": settings.mcp_resource_url,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method or ("S256" if code_challenge else ""),
            "resource": resource,
            "create_user": bool(create_user),
            "iss_supported": bool(iss_supported),
            "exp": datetime.now(timezone.utc) + timedelta(seconds=_OAUTH_REQ_TTL),
        },
        settings.jwt_secret, algorithm="HS256",
    )


def _verify_oauth_request(req: str) -> dict:
    try:
        payload = jwt.decode(req, settings.jwt_secret, algorithms=["HS256"],
                             audience=settings.mcp_resource_url,
                             issuer=settings.public_base_url.rstrip("/"))
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="invalid or expired authorize request") from exc
    if payload.get("typ") != "oauth_req":
        raise HTTPException(status_code=400, detail="invalid authorize request")
    return payload


def _grant_key(kind: str, nonce: str) -> str:
    namespace = hashlib.sha256((settings.public_base_url.rstrip("/") + "|" +
                                settings.mcp_resource_url).encode()).hexdigest()[:24]
    return f"{_GRANT_PREFIX}{namespace}:{kind}:{nonce}"


async def _consume(redis, key: str):
    return await redis.getdel(key)


def _invalid_grant():
    raise HTTPException(status_code=400, detail="invalid_grant")


def _redirect_response(payload: dict, **params) -> JSONResponse:
    params["state"] = payload.get("state", "")
    params["iss"] = settings.public_base_url.rstrip("/")
    redirect_uri = payload["redirect_uri"]
    return JSONResponse({"redirect_url": redirect_uri + ("&" if "?" in redirect_uri else "?") + urlencode(params)},
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"})




# ── OAuth 2.1 Authorization Server Metadata ─────────────────────────────────────

_well_known_router = APIRouter(tags=["oauth"])


@_well_known_router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata() -> dict:
    """OAuth 2.1 Authorization Server Metadata (RFC 8414)."""
    base = settings.public_base_url.rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "scopes_supported": ["user", "ingest", "offline_access", *PLUGIN_SCOPES],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "client_id_metadata_document_supported": True,
        "authorization_response_iss_parameter_supported": True,
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
            "none",  # public PKCE clients
        ],
        "revocation_endpoint_auth_methods_supported": [],
        "introspection_endpoint_auth_methods_supported": [],
    }


# ── Dynamic Client Registration (RFC 7591) ──────────────────────────────────────

class _DCRRequest(BaseModel):
    client_name: str = ""
    redirect_uris: list[str] = []
    grant_types: list[str] = ["authorization_code"]
    scopes: list[str] = ["user"]


@router.post("/register")
async def register_client(body: _DCRRequest) -> dict:
    """OAuth 2.1 Dynamic Client Registration (DCR).

    MCP clients (Claude Desktop/Web/Mobile) register themselves. Public PKCE
    clients don't receive a client_secret."""
    if not body.redirect_uris:
        raise HTTPException(status_code=400, detail="redirect_uris is required")

    for uri in body.redirect_uris:
        if not _check_dcr_redirect_uri(uri, [uri]):
            raise HTTPException(status_code=400, detail="invalid redirect_uri")

    client_id = secrets.token_urlsafe(24)
    if _is_plugin_client(client_id):
        raise HTTPException(status_code=400, detail="reserved client identifier")
    await get_pool().execute(
        """INSERT INTO oauth_clients (client_id, allowed_redirect_uris)
           VALUES ($1, $2)""",
        client_id, body.redirect_uris,
    )

    return {
        "client_id": client_id,
        "client_secret": None,
        "client_name": body.client_name,
        "redirect_uris": body.redirect_uris,
        "grant_types": body.grant_types or ["authorization_code"],
        "scopes": body.scopes or ["user"],
        "token_endpoint_auth_method": "none",
        "registration_access_token": None,
    }


# ── Authorize ───────────────────────────────────────────────────────────────────

@router.get("/authorize")
async def authorize(
    response_type: str = "code",
    client_id: str = "",
    redirect_uri: str = "",
    state: str = "",
    scope: str = "ingest",
    code_challenge: str = "",
    code_challenge_method: str = "",
    resource: str = "",
    iss: str = "",
    request: Request = None,
) -> RedirectResponse:
    """OAuth 2.1 authorize endpoint.

    Every client goes to the self-hosted auth page on the memory layer
    (api.zynd.ai/oauth/login) — cards/persona are out of the loop. Connector
    clients (DCR/CIMD) seal create_user=false (lookup-only at /complete);
    legacy confidential clients (ChatGPT Action, Hermes Deployer) seal
    create_user=true.

    RFC 8707: `resource` (when present) must be the canonical MCP resource and
    is sealed into the signed request so /token can echo + bind it.
    RFC 9207: an empty `iss` parameter signals the client wants the issuer
    echoed in the callback redirect.
    """
    if response_type != "code":
        raise HTTPException(status_code=400, detail="response_type must be 'code'")

    if resource:
        res = resource.rstrip("/")
        # Accept the canonical resource or its origin (some hosts send the
        # server URL without the /mcp path); normalize to the canonical value.
        if res != settings.mcp_resource_url and res != settings.mcp_origin.rstrip("/"):
            raise HTTPException(status_code=400, detail="unsupported resource indicator")
        resource = settings.mcp_resource_url

    is_connector_client = not _is_known_client(client_id)
    if is_connector_client:
        if code_challenge_method != "S256" or not re.fullmatch(r"[A-Za-z0-9_-]{43}", code_challenge):
            raise HTTPException(status_code=400, detail="S256 PKCE required")
        allowed_scopes = set(PLUGIN_SCOPES) if _is_plugin_client(client_id) else {"user", "ingest", "offline_access"}
        if not set(scope.split()).issubset(allowed_scopes):
            raise HTTPException(status_code=400, detail="unsupported scope")
        scope = _public_scope(client_id)
        resource = resource or settings.mcp_resource_url

    client_name = client_id
    if _is_plugin_client(client_id):
        if redirect_uri not in _plugin_callbacks():
            raise HTTPException(status_code=400, detail="redirect_uri not registered")
        client_name = "ZYND ChatGPT plugin"
    elif _is_known_client(client_id):
        _check_redirect_uri(redirect_uri)
    elif client_id.startswith("https://"):
        # Client ID Metadata Document (Claude.ai / MCP clients using a URL client_id).
        meta = await _fetch_metadata_document(client_id)
        client_name = meta.get("client_name", client_id)
        if not _check_dcr_redirect_uri(redirect_uri, meta["redirect_uris"]):
            raise HTTPException(status_code=400, detail="redirect_uri not registered")
    else:
        row = await get_pool().fetchrow(
            "SELECT allowed_redirect_uris FROM oauth_clients WHERE client_id = $1",
            client_id,
        )
        if not row:
            raise HTTPException(status_code=400, detail="unknown client_id")
        if not _check_dcr_redirect_uri(redirect_uri, row["allowed_redirect_uris"]):
            raise HTTPException(status_code=400, detail="redirect_uri not registered")

    from app.services.mcp_clients import clean_label
    req = _sign_oauth_request(
        redirect_uri, state, scope, code_challenge, code_challenge_method,
        resource=resource,
        create_user=not is_connector_client,
        iss_supported=iss == "",
        client_id=client_id, client_name=clean_label(client_name if isinstance(client_name, str) else client_id),
    )
    dest = settings.public_base_url.rstrip("/") + "/oauth/login?" + urlencode({"zynd_oauth": req})
    return RedirectResponse(dest, status_code=302)


# ── Callback HTML page (Supabase-direct flow) ───────────────────────────────────
# Supabase Auth returns the session in the URL hash (#access_token=...), not query
# params. This page extracts the hash and POSTs it to /oauth/complete, which
# retrieves the stored OAuth params from Redis, verifies the Supabase session,
# creates/looks-up the ZYND user, and mints the OAuth authorization code.

_CALLBACK_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ZYND — Completing sign-in</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;
background:#0f0f13;color:#e4e4e7;font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.spin{width:32px;height:32px;border:3px solid #333;border-top-color:#5b46e0;border-radius:50%;
animation:spin 0.6s linear infinite;margin:0 auto 16px}
@keyframes spin{to{transform:rotate(360deg)}}
p{text-align:center;opacity:0.7}
</style></head>
<body><div><div class="spin"></div><p>Completing sign-in…</p></div>
<script>
(function(){
  var hash = window.location.hash.substring(1);
  if (!hash) { document.body.innerHTML = '<p style="color:#ef4444">Sign-in failed — no session returned.</p>'; return; }
  var params = new URLSearchParams(hash);
  var token = params.get('access_token');
  if (!token) { document.body.innerHTML = '<p style="color:#ef4444">Sign-in failed — no access token.</p>'; return; }
  var stateId = new URLSearchParams(window.location.search).get('state');
  fetch('/oauth/complete', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({state_id: stateId, supabase_token: token})
  }).then(function(r){ return r.json().then(function(d){ return {ok:r.ok,data:d}; }); })
  .then(function(r){
    if (!r.ok) { document.body.innerHTML = '<p style="color:#ef4444">Sign-in failed: ' + (r.data.detail || 'unknown error') + '</p>'; return; }
    window.location.href = r.data.redirect_url;
  }).catch(function(e){ document.body.innerHTML = '<p style="color:#ef4444">Sign-in failed: ' + e.message + '</p>'; });
})();
</script></body></html>"""


@router.get("/callback", response_class=HTMLResponse)
async def callback() -> HTMLResponse:
    """HTML page that extracts the Supabase session from the URL hash and POSTs
    it to /oauth/complete. The browser is then redirected to Claude's redirect_uri
    with the OAuth authorization code."""
    return HTMLResponse(_CALLBACK_HTML)


# ── Complete ─────────────────────────────────────────────────────────────────────

class _CompleteRequest(BaseModel):
    req: str = ""                  # signed JWT (ChatGPT/persona legacy flow)
    supabase_token: str = ""       # Supabase access token
    state_id: str = ""             # Redis state key (Supabase-direct flow)
    decision: str = ""


@router.post("/consent")
async def consent(body: _CompleteRequest) -> JSONResponse:
    payload = _verify_oauth_request(body.req)
    identity = await supabase_identity(body.supabase_token)
    if not identity:
        raise HTTPException(status_code=401, detail="Sign-in could not be verified")
    if not payload.get("create_user", True):
        from app.services.users import find_user
        if await find_user(get_pool(), identity[0], identity[2]) is None:
            raise HTTPException(status_code=401, detail="No ZYND account found; create your card at cards.zynd.ai, then connect again.")
    return JSONResponse({"email": identity[0], "client_name": payload.get("client_name") or payload.get("client_id") or "Unknown client",
                         "resource": payload.get("resource") or settings.mcp_resource_url,
                         "scope": payload.get("scope", "user")},
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


async def _resolve_user_and_mint_code(
    supabase_token: str, redirect_uri: str, state: str, scope: str,
    code_challenge: str, code_challenge_method: str, redis,
    resource: str = "", create_user: bool = True, iss_supported: bool = False,
    client_id: str = "", client_name: str = "", nonce: str = "",
) -> JSONResponse:
    """Verify the Supabase identity, resolve the ZYND user, mint a
    single-use authorization code with optional PKCE params, and return the
    redirect URL for the browser.

    create_user=False (MCP connector path) is lookup-only: a verified identity
    with no existing memory user gets a 401 instead of an account."""
    identity = await supabase_identity(supabase_token)
    if not identity:
        _log_token_diag(supabase_token)
        raise HTTPException(status_code=401, detail="Sign-in could not be verified")
    email, display_name, sub = identity

    from app.services.users import find_user, resolve_user
    if create_user:
        user_id = await resolve_user(get_pool(), email, display_name, sub)
    else:
        user_id = await find_user(get_pool(), email, sub)
        if user_id is None:
            raise HTTPException(
                status_code=401,
                detail=(f"No ZYND account found for {email} — create your card "
                        "at cards.zynd.ai, then connect again."),
            )

    from app.services.persona import link_user
    agent_id = await link_user(get_pool(), user_id, sub, display_name, email)
    if agent_id:
        from app.services.persona_ingest import seed_persona_profile
        await seed_persona_profile(get_pool(), redis, user_id, sub)

    code = secrets.token_urlsafe(32)
    # Bind the code to the redirect_uri so a confidential client can only redeem it
    # with the same URI at /token (RFC 6749 §4.1.3). PKCE params (Claude) are stored
    # alongside and validated independently at /token. The RFC 8707 resource
    # indicator is stored so /token can echo it and bind the token audience.
    stored: dict = {"user_id": str(user_id), "redirect_uri": redirect_uri,
                    "client_id": client_id, "client_type": "confidential" if create_user else "public",
                    "scope": scope, "client_name": client_name, "nonce": nonce,
                    "challenge": code_challenge, "method": code_challenge_method}
    if resource:
        stored["resource"] = resource
    await redis.set(
        f"{_CODE_PREFIX}{code}" if create_user else _grant_key("code", code),
        json.dumps(stored),
        ex=_CODE_TTL_SECONDS,
    )
    if code_challenge and create_user:
        await _store_pkce_params(redis, code, code_challenge, code_challenge_method)

    params = {"code": code, "state": state, "iss": settings.public_base_url.rstrip("/")}
    separator = "&" if "?" in redirect_uri else "?"
    location = f"{redirect_uri}{separator}{urlencode(params)}"
    return JSONResponse({"redirect_url": location}, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@router.post("/complete")
async def complete(request: Request, body: _CompleteRequest) -> JSONResponse:
    """Complete the OAuth authorization flow after user authentication.

    Two paths:
      1. Signed request: body.req contains the signed JWT from /authorize,
         body.supabase_token is the Supabase session. Used by the self-hosted
         auth page (/oauth/login) for MCP connectors (lookup-only when
         create_user=false) and by cards/persona for legacy clients.
      2. Supabase-direct (Claude): body.state_id is the Redis state key from
         /authorize, body.supabase_token is the Supabase session from the
         /oauth/callback HTML page.

    Both paths verify the Supabase session, resolve the ZYND user, and mint an
    authorization code."""
    redis = request.app.state.arq
    if body.decision not in ("approve", "deny"):
        raise HTTPException(status_code=400, detail="explicit consent decision required")

    if body.state_id:
        # ── Supabase-direct flow (Claude) ──
        stored = await _get_oauth_state(redis, body.state_id)
        if not stored:
            raise HTTPException(status_code=400, detail="invalid or expired state")
        if not await supabase_identity(body.supabase_token):
            raise HTTPException(status_code=401, detail="Sign-in could not be verified")
        if not await _consume(redis, f"{_STATE_PREFIX}{body.state_id}"):
            raise HTTPException(status_code=400, detail="invalid or expired state")

        redirect_uri = stored["redirect_uri"]
        state = stored.get("state", "")
        scope = stored.get("scope", "user")
        code_challenge = stored.get("code_challenge", "")
        code_challenge_method = stored.get("code_challenge_method", "S256")
        _check_redirect_uri(redirect_uri)

        if body.decision == "deny":
            return _redirect_response(stored, error="access_denied")
        response = await _resolve_user_and_mint_code(
            body.supabase_token, redirect_uri, state, scope,
            code_challenge, code_challenge_method, redis,
        )
        return response

    # Signed req from /authorize. redirect_uri was already validated there
    # (known client, DCR, or CIMD) and sealed into the JWT — don't re-check
    # the global allowlist, which would reject ChatGPT connector callbacks.
    payload = _verify_oauth_request(body.req)
    redirect_uri = payload["redirect_uri"]
    state = payload.get("state", "")
    scope = payload.get("scope", "ingest")
    code_challenge = payload.get("code_challenge", "")
    code_challenge_method = payload.get("code_challenge_method", "S256")
    resource = payload.get("resource", "")
    create_user = payload.get("create_user", True)   # legacy requests default to create
    iss_supported = payload.get("iss_supported", False)

    identity = await supabase_identity(body.supabase_token)
    if not identity:
        raise HTTPException(status_code=401, detail="Sign-in could not be verified")
    if not create_user:
        from app.services.users import find_user
        if await find_user(get_pool(), identity[0], identity[2]) is None:
            raise HTTPException(status_code=401, detail="No ZYND account found; create your card at cards.zynd.ai, then connect again.")
    nonce = payload.get("nonce")
    if not nonce or not await redis.set(_grant_key("decision", nonce), "used", ex=_OAUTH_REQ_TTL, nx=True):
        raise HTTPException(status_code=400, detail="authorization request already completed")
    if body.decision == "deny":
        return _redirect_response(payload, error="access_denied")
    return await _resolve_user_and_mint_code(
        body.supabase_token, redirect_uri, state, scope,
        code_challenge, code_challenge_method, redis,
        resource=resource, create_user=create_user, iss_supported=iss_supported,
        client_id=payload.get("client_id", ""), client_name=payload.get("client_name", ""), nonce=nonce,
    )


# ── Token ────────────────────────────────────────────────────────────────────────

@router.post("/token")
async def token(
    request: Request,
    grant_type: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(""),
    code: str = Form(""),
    redirect_uri: str = Form(""),
    code_verifier: str = Form(""),
    refresh_token: str = Form(""),
    resource: str = Form(""),
    scope: str = Form(""),
) -> JSONResponse:
    """OAuth 2.1 token endpoint — exchange authorization code or refresh token for
    a ZYND JWT access token.

    Authorization code grant:
      Validates the code (single-use, 10-min TTL). If PKCE was used, validates
      code_verifier against the stored challenge. Codes minted for a connector
      (RFC 8707 resource indicator) require the same `resource` at redemption;
      the token is then minted with iss=AS issuer and aud=resource and the
      response echoes `resource`.

    Refresh token grant:
      Public clients get single-use rotated refresh tokens; replaying a used
      token is invalid_grant. Revoked tokens are rejected (sign-out watermark).
    """

    confidential = _is_known_client(client_id)
    if confidential:
        _check_client(client_id, client_secret)
    else:
        if client_secret:
            _invalid_grant()
        if _is_plugin_client(client_id):
            _plugin_callbacks()
        elif not client_id.startswith("https://"):
            row = await get_pool().fetchrow("SELECT id FROM oauth_clients WHERE client_id = $1", client_id)
            if not row:
                raise HTTPException(status_code=401, detail="invalid client")

    if grant_type == "authorization_code":
        redis = request.app.state.arq
        if not confidential:
            raw = await redis.get(_grant_key("code", code))
            if raw is None:
                _invalid_grant()
            try:
                grant = json.loads(raw)
            except (ValueError, TypeError):
                _invalid_grant()
            if (grant.get("client_type") != "public" or grant.get("client_id") != client_id or
                grant.get("redirect_uri") != redirect_uri or grant.get("resource") != settings.mcp_resource_url or
                grant.get("scope") != _public_scope(client_id) or
                (resource and resource.rstrip("/") not in (settings.mcp_resource_url, settings.mcp_origin.rstrip("/"))) or
                not _verify_code_challenge(code_verifier, grant.get("challenge", ""), grant.get("method", ""))):
                _invalid_grant()
            if scope and set(scope.split()) != set(grant["scope"].split()):
                _invalid_grant()
            if not await _consume(redis, _grant_key("code", code)):
                _invalid_grant()
            user_id = grant["user_id"]
            from app.services.mcp_clients import clean_label
            connection_jti = str(uuid.uuid4())
            await get_pool().execute(
                "INSERT INTO mcp_clients (user_id, label, scopes, jti) VALUES ($1, $2, $3, $4::uuid)",
                user_id, clean_label(grant.get("client_name") or client_id), grant["scope"].split(), connection_jti)
            refresh_tok, refresh_jti = issue_rotating_refresh_token(user_id, bound=True)
            await redis.set(_grant_key("refresh", refresh_jti), json.dumps({
                "v": 2, "sub": user_id, "client_id": client_id, "resource": settings.mcp_resource_url,
                "scope": grant["scope"], "connection_jti": connection_jti}), ex=settings.refresh_token_ttl_seconds)
            access_token, expires_in = issue_connector_access_token(
                user_id, settings.mcp_resource_url, connection_jti, scopes=grant["scope"].split())
            return JSONResponse({"access_token": access_token, "token_type": "Bearer", "expires_in": expires_in,
                                 "refresh_token": refresh_tok, "resource": settings.mcp_resource_url, "scope": grant["scope"]},
                                headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
        key = f"{_CODE_PREFIX}{code}"
        raw = await _consume(redis, key)
        if raw is None:
            raise HTTPException(status_code=400, detail="invalid_grant")
        stored = raw.decode() if isinstance(raw, bytes) else raw

        try:
            parsed = json.loads(stored)
        except (ValueError, TypeError):
            parsed = None
        stored_resource = parsed.get("resource", "") if isinstance(parsed, dict) else ""
        if isinstance(parsed, dict) and parsed.get("client_type") == "public":
            _invalid_grant()
        if isinstance(parsed, dict) and parsed.get("client_id") and parsed["client_id"] != client_id:
            _invalid_grant()
        if stored_resource and not hmac.compare_digest(resource, stored_resource):
            raise HTTPException(status_code=400, detail="invalid_grant")
        if not stored_resource and resource:
            # Resource only came at redemption (not at authorize): bind it if
            # it is the canonical MCP resource, so the token response echoes it.
            res = resource.rstrip("/")
            if res != settings.mcp_resource_url and res != settings.mcp_origin.rstrip("/"):
                raise HTTPException(status_code=400, detail="invalid_grant")
            stored_resource = settings.mcp_resource_url
        logger.info(
            "token exchange grant=%s client=%s stored_resource=%s provided_resource=%s",
            grant_type, (client_id or "")[:40], bool(stored_resource), bool(resource),
        )

        if isinstance(parsed, dict) and parsed.get("redirect_uri") != redirect_uri:
            _invalid_grant()
        pkce = await _get_pkce_params(redis, code)
        if pkce:
            # Preserve in-flight confidential PKCE grants while checking the
            # same exact callback that was sealed at authorization.
            challenge, method = pkce
            await _clear_pkce_params(redis, code)
            if not code_verifier:
                raise HTTPException(status_code=400, detail="code_verifier is required (PKCE)")
            if not _verify_code_challenge(code_verifier, challenge, method):
                raise HTTPException(status_code=400, detail="invalid code_verifier")
            user_id = _code_user_id(stored)
        else:
            # Confidential clients (ChatGPT, Hermes Deployer): enforce the
            # redirect_uri binding (RFC 6749 §4.1.3).
            try:
                user_id = _resolve_code_user(stored, redirect_uri)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="invalid_grant") from exc

        # The Hermes Deployer stores the token inside a long-lived agent container and
        # has no refresh loop, so hand it a personal token (mcp_token_ttl_seconds) and
        # no refresh token — the owner re-connects at expiry. Only on the initial
        # code exchange; refresh_token grants keep the standard short-lived path.
        if _is_deployer_client(client_id):
            return JSONResponse({
                "access_token": await issue_personal_token(get_pool(), user_id),
                "token_type": "bearer",
                "expires_in": settings.mcp_token_ttl_seconds,
                "scope": "ingest",
            }, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

        if stored_resource:
            # Known confidential client with explicit MCP resource: retain its
            # resource-bound token, but bind its refresh grant to this client.
            access_token, expires_in = issue_connector_access_token(user_id, stored_resource)
            refresh_tok, refresh_jti = issue_rotating_refresh_token(user_id, bound=True)
            await redis.set(
                _grant_key("confidential-refresh", refresh_jti),
                json.dumps({"v": 2, "sub": user_id, "client_id": client_id, "resource": stored_resource,
                            "scope": parsed.get("scope", "ingest") if isinstance(parsed, dict) else "ingest"}),
                ex=settings.refresh_token_ttl_seconds,
            )
            return JSONResponse({
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": expires_in,
                "refresh_token": refresh_tok,
                "resource": stored_resource,
                "scope": parsed.get("scope", "ingest") if isinstance(parsed, dict) else "ingest",
            }, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

        access_token, expires_in = issue_access_token(user_id)
        return JSONResponse({
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": expires_in,
            "refresh_token": issue_refresh_token(user_id),
            "scope": "ingest user",
        }, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    elif grant_type == "refresh_token":
        redis = request.app.state.arq
        if not confidential:
            try:
                user_id, issued_at, jti = verify_refresh_meta(refresh_token, bound=True)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="invalid_grant") from exc
            if not jti:
                _invalid_grant()
            raw = await redis.get(_grant_key("refresh", jti))
            if raw is None:
                _invalid_grant()
            try:
                grant = json.loads(raw)
            except (ValueError, TypeError):
                _invalid_grant()
            if (grant.get("v") != 2 or grant.get("sub") != user_id or grant.get("client_id") != client_id or
                grant.get("resource") != settings.mcp_resource_url or grant.get("scope") != _public_scope(client_id) or
                (resource and resource.rstrip("/") not in (settings.mcp_resource_url, settings.mcp_origin.rstrip("/"))) or
                (scope and set(scope.split()) != set(grant["scope"].split()))):
                _invalid_grant()
            connection_jti = grant.get("connection_jti")
            from app.services.mcp_clients import client_revoked
            from app.services.sessions import tokens_revoked
            if not connection_jti or await client_revoked(get_pool(), connection_jti, user_id) or await tokens_revoked(get_pool(), user_id, issued_at):
                _invalid_grant()
            if not await _consume(redis, _grant_key("refresh", jti)):
                _invalid_grant()
            access_token, expires_in = issue_connector_access_token(
                user_id, settings.mcp_resource_url, connection_jti, scopes=grant["scope"].split())
            refresh_tok, refresh_jti = issue_rotating_refresh_token(user_id, bound=True)
            await redis.set(_grant_key("refresh", refresh_jti), json.dumps(grant), ex=settings.refresh_token_ttl_seconds)
            return JSONResponse({"access_token": access_token, "token_type": "Bearer", "expires_in": expires_in,
                                 "refresh_token": refresh_tok, "resource": settings.mcp_resource_url, "scope": grant["scope"]},
                                headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
        try:
            user_id, issued_at, jti = verify_refresh_meta(refresh_token, bound=True)
        except ValueError:
            pass  # Legacy confidential no-resource refresh tokens use the old issuer.
        else:
            if not jti:
                _invalid_grant()
            key = _grant_key("confidential-refresh", jti)
            raw = await redis.get(key)
            if raw is None:
                _invalid_grant()
            try:
                grant = json.loads(raw)
            except (ValueError, TypeError):
                _invalid_grant()
            if (grant.get("v") != 2 or grant.get("sub") != user_id or grant.get("client_id") != client_id or
                grant.get("resource") != settings.mcp_resource_url or
                (resource and resource.rstrip("/") not in (settings.mcp_resource_url, settings.mcp_origin.rstrip("/"))) or
                (scope and scope != grant.get("scope"))):
                _invalid_grant()
            from app.services.sessions import tokens_revoked
            if await tokens_revoked(get_pool(), user_id, issued_at) or not await _consume(redis, key):
                _invalid_grant()
            access_token, expires_in = issue_connector_access_token(user_id, settings.mcp_resource_url)
            refresh_tok, refresh_jti = issue_rotating_refresh_token(user_id, bound=True)
            await redis.set(_grant_key("confidential-refresh", refresh_jti), json.dumps(grant), ex=settings.refresh_token_ttl_seconds)
            return JSONResponse({"access_token": access_token, "token_type": "Bearer", "expires_in": expires_in,
                                 "refresh_token": refresh_tok, "resource": settings.mcp_resource_url,
                                 "scope": grant["scope"]}, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
        try:
            user_id, issued_at, jti = verify_refresh_meta(refresh_token)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid_grant") from exc

        if jti:
            # Unbound legacy records may belong to another environment. Reject
            # without reading or consuming their shared Redis keys.
            _invalid_grant()

        from app.services.sessions import tokens_revoked
        if await tokens_revoked(get_pool(), user_id, issued_at):
            raise HTTPException(status_code=400, detail="invalid_grant")

        access_token, expires_in = issue_access_token(user_id)
        return JSONResponse({
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": expires_in,
            "refresh_token": issue_refresh_token(user_id),
            "scope": "ingest user",
        }, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    else:
        raise HTTPException(status_code=400, detail="unsupported_grant_type")
