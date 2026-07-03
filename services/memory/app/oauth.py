"""OAuth2 authorization-code server for ChatGPT Action AND Claude OAuth 2.1.

Two flows, both issuing the same ZYND HS256 JWT:

  ChatGPT Action (legacy, no PKCE):
    ChatGPT opens /oauth/authorize -> redirect to persona login -> persona calls
    /oauth/complete -> mint code in Redis -> ChatGPT exchanges at /oauth/token.

  Claude Connectors (OAuth 2.1 with PKCE + DCR):
    Claude discovers /.well-known/oauth-protected-resource (FastMCP) and
    /.well-known/oauth-authorization-server -> registers via DCR -> opens
    /oauth/authorize?code_challenge=... -> server stores params in Redis,
    redirects to Supabase Auth (Google) -> Supabase redirects to /oauth/callback
    (HTML page extracts session from URL hash) -> POST /oauth/complete with
    state_id + token -> server mints auth code -> Claude exchanges at /oauth/token
    with code_verifier -> gets ZYND JWT.

The Claude flow bypasses the persona frontend entirely — Supabase Auth handles
login directly. Both /token paths call the same issue_access_token() function:
OAuth is just another way to obtain the exact same JWT that MCP clients use.
"""
import base64
import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit

import jwt
from fastapi import APIRouter, Body, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from app.auth import issue_access_token, issue_refresh_token, verify_refresh_claims
from app.config import settings
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
_CODE_TTL_SECONDS = 600
_OAUTH_REQ_TTL = 600  # the signed authorize request is valid for 10 minutes
_STATE_TTL_SECONDS = 600  # stored state TTL for the Supabase-direct flow


# ── Redirect URI validation ─────────────────────────────────────────────────────

def _allowed_origins() -> set[tuple[str, str | None]]:
    return {(u.scheme, u.hostname) for u in map(urlsplit, settings.allowed_redirect_prefixes)}


def _check_redirect_uri(redirect_uri: str) -> None:
    parsed = urlsplit(redirect_uri)
    if (parsed.scheme, parsed.hostname) not in _allowed_origins():
        raise HTTPException(status_code=400, detail="redirect_uri not allowed")
    if not any(redirect_uri.startswith(p) for p in settings.allowed_redirect_prefixes):
        raise HTTPException(status_code=400, detail="redirect_uri not allowed")


def _check_dcr_redirect_uri(redirect_uri: str, allowed_uris: list[str]) -> bool:
    """Validate that a redirect_uri belongs to a registered DCR client."""
    parsed = urlsplit(redirect_uri)
    for allowed in allowed_uris:
        allowed_parsed = urlsplit(allowed)
        if parsed.scheme != allowed_parsed.scheme:
            continue
        if parsed.hostname != allowed_parsed.hostname:
            continue
        if parsed.port != allowed_parsed.port:
            continue
        if parsed.path == allowed_parsed.path or parsed.path.startswith(allowed_parsed.path.rstrip("/") + "/"):
            return True
    return False


def _check_client(client_id: str, client_secret: str) -> None:
    ok_id = hmac.compare_digest(client_id, settings.oauth_client_id)
    ok_secret = hmac.compare_digest(client_secret, settings.oauth_client_secret)
    if not (ok_id and ok_secret):
        raise HTTPException(status_code=401, detail="invalid client credentials")


# ── PKCE utilities (RFC 7636) ───────────────────────────────────────────────────

def _verify_code_challenge(verifier: str, challenge: str, method: str = "S256") -> bool:
    """Validate a PKCE code_verifier against its stored challenge."""
    if method == "S256":
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

def _sign_oauth_request(redirect_uri: str, state: str, scope: str) -> str:
    """Sign the authorize params so they survive the round-trip through the
    persona login without trusting client-supplied params."""
    return jwt.encode(
        {"typ": "oauth_req", "redirect_uri": redirect_uri, "state": state, "scope": scope,
         "exp": datetime.now(timezone.utc) + timedelta(seconds=_OAUTH_REQ_TTL)},
        settings.jwt_secret, algorithm="HS256",
    )


def _verify_oauth_request(req: str) -> dict:
    try:
        payload = jwt.decode(req, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="invalid or expired authorize request") from exc
    if payload.get("typ") != "oauth_req":
        raise HTTPException(status_code=400, detail="invalid authorize request")
    return payload


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
        "scopes_supported": ["user", "ingest", "offline_access"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
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
        _check_redirect_uri(uri)

    client_id = secrets.token_urlsafe(24)
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
    request: Request = None,
) -> RedirectResponse:
    """OAuth 2.1 authorize endpoint.

    Two paths:
      ChatGPT client_id → persona frontend login (legacy, no PKCE).
      DCR-registered client_id → Supabase Auth Google login (Claude, with PKCE).

    For DCR clients, OAuth params are stored in Redis and the user is sent
    directly to Supabase Auth. After login, the /oauth/callback HTML page
    completes the flow by posting back to /oauth/complete."""
    if response_type != "code":
        raise HTTPException(status_code=400, detail="response_type must be 'code'")

    is_chatgpt = hmac.compare_digest(client_id, settings.oauth_client_id)

    if is_chatgpt:
        # ── ChatGPT / persona legacy flow ──
        _check_redirect_uri(redirect_uri)
        req = _sign_oauth_request(redirect_uri, state, scope)
        dest = settings.persona_login_url.rstrip("/") + "/?" + urlencode({"zynd_oauth": req})
        return RedirectResponse(dest, status_code=302)

    # ── DCR-registered client (Claude) → Supabase Auth directly ──
    row = await get_pool().fetchrow(
        "SELECT allowed_redirect_uris FROM oauth_clients WHERE client_id = $1",
        client_id,
    )
    if not row:
        raise HTTPException(status_code=400, detail="unknown client_id")
    if not _check_dcr_redirect_uri(redirect_uri, row["allowed_redirect_uris"]):
        _check_redirect_uri(redirect_uri)

    # Store the OAuth params in Redis so /oauth/complete can retrieve them
    # after Supabase Auth sends the user back.
    state_id = secrets.token_urlsafe(32)
    await _store_oauth_state(request.app.state.arq, state_id, {
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": scope,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method or "S256",
    })

    # Redirect to Supabase Auth (Google login)
    supabase_authorize_url = settings.supabase_url.rstrip("/") + "/auth/v1/authorize"
    callback_url = settings.public_base_url.rstrip("/") + "/oauth/callback?state=" + state_id
    params = urlencode({
        "provider": "google",
        "redirect_to": callback_url,
        "scopes": "email profile",
    })
    return RedirectResponse(f"{supabase_authorize_url}?{params}", status_code=302)


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


async def _resolve_user_and_mint_code(
    supabase_token: str, redirect_uri: str, state: str, scope: str,
    code_challenge: str, code_challenge_method: str, redis,
) -> JSONResponse:
    """Verify the Supabase identity, resolve/create the ZYND user, mint a
    single-use authorization code with optional PKCE params, and return the
    redirect URL for the browser."""
    identity = await supabase_identity(supabase_token)
    if not identity:
        _log_token_diag(supabase_token)
        raise HTTPException(status_code=401, detail="Google sign-in could not be verified")
    email, display_name, sub = identity

    user_id = await get_pool().fetchval(
        """INSERT INTO users (email, display_name, supabase_user_id) VALUES ($1, $2, $3)
           ON CONFLICT (email) DO UPDATE SET display_name = EXCLUDED.display_name,
                 supabase_user_id = EXCLUDED.supabase_user_id RETURNING id""",
        email, display_name, sub,
    )

    from app.services.persona import link_user
    agent_id = await link_user(get_pool(), user_id, sub, display_name, email)
    if agent_id:
        from app.services.persona_ingest import seed_persona_profile
        await seed_persona_profile(get_pool(), redis, user_id, sub)

    code = secrets.token_urlsafe(32)
    await redis.set(f"{_CODE_PREFIX}{code}", str(user_id), ex=_CODE_TTL_SECONDS)

    if code_challenge:
        await _store_pkce_params(redis, code, code_challenge, code_challenge_method)

    separator = "&" if "?" in redirect_uri else "?"
    location = f"{redirect_uri}{separator}{urlencode({'code': code, 'state': state})}"
    return JSONResponse({"redirect_url": location})


@router.post("/complete")
async def complete(request: Request, body: _CompleteRequest) -> JSONResponse:
    """Complete the OAuth authorization flow after user authentication.

    Two paths:
      1. Persona frontend (ChatGPT): body.req contains the signed JWT from
         /authorize, body.supabase_token is the Supabase session.
      2. Supabase-direct (Claude): body.state_id is the Redis state key from
         /authorize, body.supabase_token is the Supabase session from the
         /oauth/callback HTML page.

    Both paths verify the Supabase session, resolve/create the ZYND user,
    and mint an authorization code."""
    redis = request.app.state.arq

    if body.state_id:
        # ── Supabase-direct flow (Claude) ──
        stored = await _get_oauth_state(redis, body.state_id)
        if not stored:
            raise HTTPException(status_code=400, detail="invalid or expired state")
        await _clear_oauth_state(redis, body.state_id)

        redirect_uri = stored["redirect_uri"]
        state = stored.get("state", "")
        scope = stored.get("scope", "user")
        code_challenge = stored.get("code_challenge", "")
        code_challenge_method = stored.get("code_challenge_method", "S256")
        _check_redirect_uri(redirect_uri)

        response = await _resolve_user_and_mint_code(
            body.supabase_token, redirect_uri, state, scope,
            code_challenge, code_challenge_method, redis,
        )
        return response

    # ── Persona frontend flow (ChatGPT, legacy) ──
    payload = _verify_oauth_request(body.req)
    redirect_uri = payload["redirect_uri"]
    state = payload.get("state", "")
    scope = payload.get("scope", "ingest")
    code_challenge = payload.get("code_challenge", "")
    code_challenge_method = payload.get("code_challenge_method", "S256")
    _check_redirect_uri(redirect_uri)

    return await _resolve_user_and_mint_code(
        body.supabase_token, redirect_uri, state, scope,
        code_challenge, code_challenge_method, redis,
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
) -> JSONResponse:
    """OAuth 2.1 token endpoint — exchange authorization code or refresh token for
    a ZYND JWT access token.

    Authorization code grant:
      Validates the code (single-use, 10-min TTL). If PKCE was used, validates
      code_verifier against the stored challenge.

    Refresh token grant:
      Issues a new access token. Revoked tokens are rejected (sign-out watermark).

    Both paths issue the same HS256 JWT — OAuth is just another way to obtain
    the exact same token format that existing MCP clients already use."""

    is_chatgpt = hmac.compare_digest(client_id, settings.oauth_client_id)
    if is_chatgpt:
        _check_client(client_id, client_secret)
    else:
        row = await get_pool().fetchrow(
            "SELECT id FROM oauth_clients WHERE client_id = $1", client_id,
        )
        if not row:
            _check_client(client_id, client_secret)

    if grant_type == "authorization_code":
        redis = request.app.state.arq
        key = f"{_CODE_PREFIX}{code}"
        raw = await redis.get(key)
        if raw is None:
            raise HTTPException(status_code=400, detail="invalid_grant")
        await redis.delete(key)  # single use
        user_id = raw.decode() if isinstance(raw, bytes) else raw

        pkce = await _get_pkce_params(redis, code)
        if pkce:
            challenge, method = pkce
            await _clear_pkce_params(redis, code)
            if not code_verifier:
                raise HTTPException(status_code=400, detail="code_verifier is required (PKCE)")
            if not _verify_code_challenge(code_verifier, challenge, method):
                raise HTTPException(status_code=400, detail="invalid code_verifier")

    elif grant_type == "refresh_token":
        try:
            user_id, issued_at = verify_refresh_claims(refresh_token)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid_grant") from exc
        from app.services.sessions import tokens_revoked
        if await tokens_revoked(get_pool(), user_id, issued_at):
            raise HTTPException(status_code=400, detail="invalid_grant")

    else:
        raise HTTPException(status_code=400, detail="unsupported_grant_type")

    access_token, expires_in = issue_access_token(user_id)
    return JSONResponse({
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "refresh_token": issue_refresh_token(user_id),
        "scope": "ingest user",
    })
