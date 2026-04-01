"""
OAuth routes — custom OAuth flows to get scoped API tokens.

These are SEPARATE from Supabase login OAuth. The user logs in via
Supabase, then "connects" each platform here to get API access tokens
with specific scopes (e.g. tweet.write, w_member_social).

Flow:
  1. Frontend calls GET /api/oauth/<provider>/authorize?token=<jwt>
  2. Backend stores state + user_id, redirects to provider
  3. Provider redirects back to GET /api/oauth/<provider>/callback
  4. Backend exchanges code for tokens, stores in api_tokens table
  5. Redirects to frontend dashboard with success/error status
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
import httpx
import secrets
import hashlib
import base64
import json
from urllib.parse import urlencode

import config
from services.token_store import save_tokens

router = APIRouter()

# In-memory pending OAuth state store (use Redis in production)
_pending_oauth: dict[str, dict] = {}


def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


# =====================================================================
# LINKEDIN — OAuth 2.0 (OpenID Connect)
# =====================================================================

@router.get("/linkedin/authorize")
async def linkedin_authorize(token: str, request: Request):
    """
    Start LinkedIn OAuth flow.
    The 'token' query param is the Supabase JWT so we can identify
    the user on callback.
    """
    # Validate user from token
    user = await _validate_token(token)

    state = secrets.token_urlsafe(32)
    _pending_oauth[state] = {
        "user_id": user["id"],
        "provider": "linkedin",
    }

    params = {
        "response_type": "code",
        "client_id": config.LINKEDIN_CLIENT_ID,
        "redirect_uri": config.LINKEDIN_REDIRECT_URI,
        "scope": "openid profile email w_member_social",
        "state": state,
    }
    auth_url = f"https://www.linkedin.com/oauth/v2/authorization?{urlencode(params)}"
    return RedirectResponse(auth_url)


@router.get("/linkedin/callback")
async def linkedin_callback(code: str, state: str):
    """Exchange LinkedIn authorization code for tokens."""
    pending = _pending_oauth.pop(state, None)
    if not pending or pending["provider"] != "linkedin":
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    user_id = pending["user_id"]

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config.LINKEDIN_REDIRECT_URI,
                "client_id": config.LINKEDIN_CLIENT_ID,
                "client_secret": config.LINKEDIN_CLIENT_SECRET,
            },
        )

    if resp.status_code != 200:
        redirect_url = f"{config.FRONTEND_URL}/dashboard?oauth=linkedin&status=error&detail={resp.text}"
        return RedirectResponse(redirect_url)

    token_data = resp.json()
    save_tokens(
        user_id=user_id,
        provider="linkedin",
        tokens=token_data,
    )

    redirect_url = f"{config.FRONTEND_URL}/dashboard?oauth=linkedin&status=success"
    return RedirectResponse(redirect_url)


# =====================================================================
# TWITTER / X — OAuth 2.0 with PKCE
# =====================================================================

@router.get("/twitter/authorize")
async def twitter_authorize(token: str):
    """Start Twitter OAuth 2.0 PKCE flow."""
    user = await _validate_token(token)

    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = _generate_pkce()

    _pending_oauth[state] = {
        "user_id": user["id"],
        "provider": "twitter",
        "code_verifier": code_verifier,
    }

    params = {
        "response_type": "code",
        "client_id": config.TWITTER_CLIENT_ID,
        "redirect_uri": config.TWITTER_REDIRECT_URI,
        "scope": "tweet.read tweet.write users.read dm.read dm.write offline.access",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"https://twitter.com/i/oauth2/authorize?{urlencode(params)}"
    return RedirectResponse(auth_url)


@router.get("/twitter/callback")
async def twitter_callback(code: str, state: str):
    """Exchange Twitter authorization code for tokens (with PKCE)."""
    pending = _pending_oauth.pop(state, None)
    if not pending or pending["provider"] != "twitter":
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    user_id = pending["user_id"]
    code_verifier = pending["code_verifier"]

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.twitter.com/2/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config.TWITTER_REDIRECT_URI,
                "client_id": config.TWITTER_CLIENT_ID,
                "code_verifier": code_verifier,
            },
            auth=(config.TWITTER_CLIENT_ID, config.TWITTER_CLIENT_SECRET),
        )

    if resp.status_code != 200:
        redirect_url = f"{config.FRONTEND_URL}/dashboard?oauth=twitter&status=error&detail={resp.text}"
        return RedirectResponse(redirect_url)

    token_data = resp.json()
    save_tokens(
        user_id=user_id,
        provider="twitter",
        tokens=token_data,
    )

    redirect_url = f"{config.FRONTEND_URL}/dashboard?oauth=twitter&status=success"
    return RedirectResponse(redirect_url)


# =====================================================================
# GOOGLE — OAuth 2.0 (Calendar + Profile)
# =====================================================================

@router.get("/google/authorize")
async def google_authorize(token: str, features: str = "calendar,docs"):
    """
    Start Google OAuth flow with granular scope selection.
    
    Args:
        token: Supabase JWT
        features: comma-separated list of 'calendar', 'docs'
    """
    user = await _validate_token(token)

    state = secrets.token_urlsafe(32)
    _pending_oauth[state] = {
        "user_id": user["id"],
        "provider": "google",
    }

    scopes = ["openid", "email", "profile"]
    feature_map = {
        "calendar": "https://www.googleapis.com/auth/calendar",
        "docs": "https://www.googleapis.com/auth/documents https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.metadata.readonly",
        "gmail": "https://www.googleapis.com/auth/gmail.modify",
        "sheets": "https://www.googleapis.com/auth/spreadsheets",
    }
    
    
    selected_features = [f.strip() for f in features.split(",") if f.strip() in feature_map]
    if not selected_features:
        # Default to all if none provided or invalid
        selected_features = ["calendar", "docs"]
        
    for feat in selected_features:
        scopes.append(feature_map[feat])

    params = {
        "response_type": "code",
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": config.GOOGLE_REDIRECT_URI,
        "scope": " ".join(scopes),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return RedirectResponse(auth_url)


@router.get("/google/callback")
async def google_callback(code: str, state: str):
    """Exchange Google authorization code for tokens."""
    pending = _pending_oauth.pop(state, None)
    if not pending or pending["provider"] != "google":
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    user_id = pending["user_id"]

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config.GOOGLE_REDIRECT_URI,
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
            },
        )

    if resp.status_code != 200:
        redirect_url = f"{config.FRONTEND_URL}/dashboard?oauth=google&status=error&detail={resp.text}"
        return RedirectResponse(redirect_url)

    token_data = resp.json()
    save_tokens(
        user_id=user_id,
        provider="google",
        tokens=token_data,
    )

    redirect_url = f"{config.FRONTEND_URL}/dashboard?oauth=google&status=success"
    return RedirectResponse(redirect_url)


# =====================================================================
# ── Notion OAuth ─────────────────────────────────────────────────────
# =====================================================================

@router.get("/notion/authorize")
async def notion_authorize(token: str):
    """
    Start Notion OAuth flow.
    Note: Notion doesn't use granular scopes in the URL; 
    the user selects allowed pages in the Notion pop-up.
    """
    user = await _validate_token(token)

    state = secrets.token_urlsafe(32)
    _pending_oauth[state] = {
        "user_id": user["id"],
        "provider": "notion",
    }

    params = {
        "owner": "user",
        "client_id": config.NOTION_CLIENT_ID,
        "redirect_uri": config.NOTION_REDIRECT_URI,
        "response_type": "code",
        "state": state,
    }
    auth_url = f"https://api.notion.com/v1/oauth/authorize?{urlencode(params)}"
    return RedirectResponse(auth_url)


@router.get("/notion/callback")
async def notion_callback(code: str, state: str):
    """Exchange Notion authorization code for tokens."""
    pending = _pending_oauth.pop(state, None)
    if not pending or pending["provider"] != "notion":
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    user_id = pending["user_id"]

    # Notion requires Basic Auth or client_id/client_secret in the body
    # for the token exchange endpoint.
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.notion.com/v1/oauth/token",
            json={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config.NOTION_REDIRECT_URI,
            },
            auth=(config.NOTION_CLIENT_ID, config.NOTION_CLIENT_SECRET)
        )

    if resp.status_code != 200:
        redirect_url = f"{config.FRONTEND_URL}/dashboard?oauth=notion&status=error&detail={resp.text}"
        return RedirectResponse(redirect_url)

    token_data = resp.json()
    # Save token. Notion tokens don't expire, so we don't worry about refresh_token.
    save_tokens(
        user_id=user_id,
        provider="notion",
        tokens=token_data,
    )

    redirect_url = f"{config.FRONTEND_URL}/dashboard?oauth=notion&status=success"
    return RedirectResponse(redirect_url)


# =====================================================================
# Helper: validate Supabase JWT to identify the user
# =====================================================================

async def _validate_token(token: str) -> dict:
    """Validate a Supabase JWT and return user info."""
    from supabase import create_client
    sb = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
    try:
        result = sb.auth.get_user(token)
        if not result or not result.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {
            "id": result.user.id,
            "email": result.user.email,
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Auth error: {str(e)}")
