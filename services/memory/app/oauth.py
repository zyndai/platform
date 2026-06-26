"""OAuth2 authorization-code server for the ChatGPT Action.

Flow: ChatGPT opens /oauth/authorize -> we redirect to the dashboard's Google
(Supabase) login (the same identity as the dashboard and MCP) -> after sign-in the
dashboard calls /oauth/complete with the verified Google session -> we mint a
single-use code and hand it back to ChatGPT -> ChatGPT exchanges it at /oauth/token
for a JWT -> the Action sends that token as Bearer to /ingest.

The OAuth plumbing (codes, redirect allowlist, single confidential client, JWT
issuance) is production-shaped. User authentication is delegated to Supabase Google,
so a user has ONE identity across GPT, MCP, and the dashboard (keyed by email).
"""
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit

import jwt
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from app.auth import issue_access_token, issue_refresh_token, verify_refresh_token
from app.config import settings
from app.db import get_pool
from app.supabase_auth import supabase_identity

router = APIRouter(prefix="/oauth", tags=["oauth"])

_CODE_PREFIX = "oauth:code:"
_CODE_TTL_SECONDS = 600
_OAUTH_REQ_TTL = 600  # the signed authorize request is valid for 10 minutes


def _allowed_origins() -> set[tuple[str, str | None]]:
    return {(u.scheme, u.hostname) for u in map(urlsplit, settings.allowed_redirect_prefixes)}


def _check_redirect_uri(redirect_uri: str) -> None:
    # Host-origin allowlist (not bare startswith) so "http://localhost.evil.com"
    # can't spoof the "http://localhost" prefix → prevents open-redirect / code theft.
    parsed = urlsplit(redirect_uri)
    if (parsed.scheme, parsed.hostname) not in _allowed_origins():
        raise HTTPException(status_code=400, detail="redirect_uri not allowed")
    if not any(redirect_uri.startswith(p) for p in settings.allowed_redirect_prefixes):
        raise HTTPException(status_code=400, detail="redirect_uri not allowed")


def _check_client(client_id: str, client_secret: str) -> None:
    ok_id = hmac.compare_digest(client_id, settings.oauth_client_id)
    ok_secret = hmac.compare_digest(client_secret, settings.oauth_client_secret)
    if not (ok_id and ok_secret):
        raise HTTPException(status_code=401, detail="invalid client credentials")


def _sign_oauth_request(redirect_uri: str, state: str, scope: str) -> str:
    """Sign the ChatGPT authorize params so they survive the round-trip through the
    dashboard Google login without trusting client-supplied state in between."""
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


@router.get("/authorize")
async def authorize(
    response_type: str = "code",
    client_id: str = "",
    redirect_uri: str = "",
    state: str = "",
    scope: str = "ingest",
) -> RedirectResponse:
    """Hand the user off to the dashboard's Google (Supabase) login. The signed `req`
    carries the ChatGPT authorize params so the dashboard can complete the flow."""
    if response_type != "code":
        raise HTTPException(status_code=400, detail="response_type must be 'code'")
    if not hmac.compare_digest(client_id, settings.oauth_client_id):
        raise HTTPException(status_code=400, detail="unknown client_id")
    _check_redirect_uri(redirect_uri)

    req = _sign_oauth_request(redirect_uri, state, scope)
    dest = settings.dashboard_url.rstrip("/") + "/authorize?" + urlencode({"req": req})
    return RedirectResponse(dest, status_code=302)


class _CompleteRequest(BaseModel):
    req: str
    supabase_token: str


@router.post("/complete")
async def complete(request: Request, body: _CompleteRequest) -> JSONResponse:
    """Called by the dashboard authorize page after Google sign-in: verify the Google
    identity, resolve the ZYND user by email, and mint the single-use authorization
    code ChatGPT will exchange at /token. Returns the URL to send the browser back to."""
    payload = _verify_oauth_request(body.req)
    redirect_uri = payload["redirect_uri"]
    state = payload.get("state", "")
    _check_redirect_uri(redirect_uri)  # re-validate the signed value before redirecting

    identity = await supabase_identity(body.supabase_token)
    if not identity:
        raise HTTPException(status_code=401, detail="Google sign-in could not be verified")
    email, display_name = identity

    user_id = await get_pool().fetchval(
        """INSERT INTO users (email, display_name) VALUES ($1, $2)
           ON CONFLICT (email) DO UPDATE SET display_name = EXCLUDED.display_name RETURNING id""",
        email, display_name,
    )
    code = secrets.token_urlsafe(32)
    await request.app.state.arq.set(f"{_CODE_PREFIX}{code}", str(user_id), ex=_CODE_TTL_SECONDS)
    separator = "&" if "?" in redirect_uri else "?"
    location = f"{redirect_uri}{separator}{urlencode({'code': code, 'state': state})}"
    return JSONResponse({"redirect_url": location})


@router.post("/token")
async def token(
    request: Request,
    grant_type: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...),
    code: str = Form(""),
    redirect_uri: str = Form(""),
    refresh_token: str = Form(""),
) -> JSONResponse:
    _check_client(client_id, client_secret)

    if grant_type == "authorization_code":
        redis = request.app.state.arq
        key = f"{_CODE_PREFIX}{code}"
        raw = await redis.get(key)
        if raw is None:
            raise HTTPException(status_code=400, detail="invalid_grant")
        await redis.delete(key)  # single use
        user_id = raw.decode() if isinstance(raw, bytes) else raw
    elif grant_type == "refresh_token":
        try:
            user_id = verify_refresh_token(refresh_token)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid_grant") from exc
    else:
        raise HTTPException(status_code=400, detail="unsupported_grant_type")

    access_token, expires_in = issue_access_token(user_id)
    return JSONResponse({
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "refresh_token": issue_refresh_token(user_id),
        "scope": "ingest",
    })
