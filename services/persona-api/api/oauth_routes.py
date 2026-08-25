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
from datetime import datetime, timezone

router = APIRouter()

PENDING_STATE_TABLE = "oauth_pending_state"


def _store_pending_state(state: str, user_id: str, provider: str, code_verifier: str = None) -> None:
    """Persist OAuth state to Supabase so it survives backend restarts.

    A plain in-memory dict here meant any restart between /authorize and
    /callback (the `api` process restarts often — crashes, deploys, memory
    limits) silently dropped in-flight OAuth state, and the user got
    "Invalid or expired state" through no fault of their own.
    """
    sb = config.get_supabase()
    # Opportunistic cleanup so abandoned flows don't accumulate rows forever.
    sb.table(PENDING_STATE_TABLE).delete().lt("expires_at", datetime.now(timezone.utc).isoformat()).execute()
    sb.table(PENDING_STATE_TABLE).insert({
        "state": state,
        "user_id": user_id,
        "provider": provider,
        "code_verifier": code_verifier,
    }).execute()


def _pop_pending_state(state: str, provider: str) -> dict | None:
    """Fetch-and-delete a pending OAuth state row.

    Returns None if the state is missing, expired, or was issued for a
    different provider (mirrors the old dict-based check).
    """
    if not state:
        return None
    sb = config.get_supabase()
    resp = sb.table(PENDING_STATE_TABLE).select("*").eq("state", state).execute()
    rows = resp.data
    sb.table(PENDING_STATE_TABLE).delete().eq("state", state).execute()
    if not rows:
        return None
    row = rows[0]
    if row["provider"] != provider:
        return None
    expires_at = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > expires_at:
        return None
    return {"user_id": row["user_id"], "code_verifier": row.get("code_verifier")}


def _frontend_redirect(path: str, **params) -> RedirectResponse:
    """Redirect to a frontend path with query params safely URL-encoded.

    Provider error descriptions (e.g. LinkedIn's `Scope "..." is not
    authorized`) contain spaces, quotes and `&`, which would otherwise
    corrupt the redirect URL and the frontend's query parsing.
    """
    return RedirectResponse(f"{config.FRONTEND_URL}{path}?{urlencode(params)}")


def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _oauth_redirect_uri(provider: str) -> str:
    """Derive the OAuth callback URL from the app's public base URL.

    The backend sits behind Caddy, which serves /api/* on the same public
    origin as the frontend (config.FRONTEND_URL is env-configured per
    channel: prod vs dev). Deriving the redirect URI from it keeps the
    callback pointing at whichever channel started the flow — never a
    hardcoded host — and matches what the provider app registers.
    """
    return f"{config.FRONTEND_URL}/api/oauth/{provider}/callback"


def _identity(
    platform: str,
    platform_user_id,
    username: str,
    name: str | None = None,
    profile_url: str | None = None,
    avatar_url: str | None = None,
) -> dict:
    """Normalize a provider's /me response into one identity shape.

    platform_user_id is the provider's immutable user id (canonical
    identity); username is the display handle the enrichment pipeline
    (Apify scrapers) keys on. Merged into the token payload before
    save_tokens so it persists in api_tokens.raw_data.
    """
    out = {"platform": platform, "username": username}
    if platform_user_id is not None:
        out["platform_user_id"] = str(platform_user_id)
    if name:
        out["name"] = name
    if profile_url:
        out["profile_url"] = profile_url
    if avatar_url:
        out["avatar_url"] = avatar_url
    return out


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
    _store_pending_state(state, user["id"], "linkedin")

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
async def linkedin_callback(code: str = None, state: str = None, error: str = None, error_description: str = None):
    """Exchange LinkedIn authorization code for tokens."""
    if error or not code:
        desc = error_description or error or "authorization_denied"
        return _frontend_redirect("/dashboard/settings/accounts", oauth="linkedin", status="error", detail=desc)
    pending = _pop_pending_state(state, "linkedin")
    if not pending:
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
        return _frontend_redirect("/dashboard/settings/accounts", oauth="linkedin", status="error", detail=resp.text)

    token_data = resp.json()
    try:
        save_tokens(
            user_id=user_id,
            provider="linkedin",
            tokens=token_data,
        )
    except ValueError as e:
        return _frontend_redirect("/dashboard/settings/accounts", oauth="linkedin", status="error", detail=str(e))

    # Fetch userinfo via OIDC to pre-populate profile data for the scraper.
    try:
        async with httpx.AsyncClient() as client:
            me_resp = await client.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
            )
        if me_resp.status_code == 200:
            me_data = me_resp.json()
            name = me_data.get("name", "")
            sb = config.get_supabase()

            # Don't clobber a real scrape that's already there. This upsert
            # used to unconditionally blank profile_url and overwrite
            # raw_profile with just this OIDC placeholder — so reconnecting
            # (e.g. after being told to "disconnect and reconnect" to fix a
            # bad scrape) destroyed good data every single time instead of
            # fixing anything.
            existing = (
                sb.table("linkedin_profiles")
                .select("profile_url, raw_profile")
                .eq("user_id", user_id)
                .execute()
            )
            existing_row = existing.data[0] if existing.data else {}
            existing_raw_profile = existing_row.get("raw_profile") or {}
            has_real_data = any(
                key in existing_raw_profile
                for key in ("headline", "experience", "education", "skills", "summary")
            )

            if not has_real_data:
                # Deliberately omit `scraped_at` here — this is just OIDC
                # userinfo (full_name/sub), not a real profile scrape.
                # trigger_scrape and is_linkedin_scraped() both treat a
                # truthy `scraped_at` as "we already have good data" and skip
                # kicking off the actual Apify scrape; stamping it here left
                # raw_profile stuck at this placeholder forever, and since
                # disconnect+reconnect recreates the same placeholder, "just
                # reconnect" never actually fixed it.
                sb.table("linkedin_profiles").upsert(
                    {
                        "user_id": user_id,
                        # Preserve a profile_url the user already supplied
                        # (e.g. via the paste-URL field) rather than blanking it.
                        "profile_url": existing_row.get("profile_url") or "",
                        "raw_profile": {"full_name": name, "sub": me_data.get("sub", "")},
                    },
                    on_conflict="user_id",
                ).execute()
    except Exception:
        pass

    return _frontend_redirect("/dashboard/settings/accounts", oauth="linkedin", status="success")


# =====================================================================
# GITHUB — OAuth 2.0 (authorization code, no scopes)
# =====================================================================

@router.get("/github/authorize")
async def github_authorize(token: str):
    """Start GitHub OAuth flow.

    No scope is requested — /user returns the public profile (login,
    name, avatar) with an unscoped token, which is all we need to
    capture the username for later Apify scraping.
    """
    user = await _validate_token(token)

    state = secrets.token_urlsafe(32)
    _store_pending_state(state, user["id"], "github")

    params = {
        "client_id": config.GITHUB_CLIENT_ID,
        "redirect_uri": _oauth_redirect_uri("github"),
        "state": state,
    }
    auth_url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"
    return RedirectResponse(auth_url)


@router.get("/github/callback")
async def github_callback(code: str = None, state: str = None, error: str = None, error_description: str = None):
    """Exchange GitHub authorization code for tokens, then capture identity."""
    if error or not code:
        desc = error_description or error or "authorization_denied"
        return _frontend_redirect("/dashboard/settings/accounts", oauth="github", status="error", detail=desc)
    pending = _pop_pending_state(state, "github")
    if not pending:
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    user_id = pending["user_id"]

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            json={
                "client_id": config.GITHUB_CLIENT_ID,
                "client_secret": config.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": _oauth_redirect_uri("github"),
            },
        )

    if resp.status_code != 200:
        return _frontend_redirect("/dashboard/settings/accounts", oauth="github", status="error", detail=resp.text)

    token_data = resp.json()
    if not token_data.get("access_token"):
        return _frontend_redirect(
            "/dashboard/settings/accounts", oauth="github", status="error", detail="Token exchange failed"
        )

    # Revalidate identity via the API (GitHub recommends this over trusting
    # stale data). Best-effort — a failure here must not fail the connect.
    try:
        async with httpx.AsyncClient() as client:
            me_resp = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token_data['access_token']}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        if me_resp.status_code == 200:
            me = me_resp.json() or {}
            if me.get("login"):
                token_data.update(
                    _identity(
                        "github",
                        me.get("id"),
                        me["login"],
                        name=me.get("name"),
                        profile_url=me.get("html_url"),
                        avatar_url=me.get("avatar_url"),
                    )
                )
    except Exception:
        pass

    save_tokens(
        user_id=user_id,
        provider="github",
        tokens=token_data,
    )

    return _frontend_redirect("/dashboard/settings/accounts", oauth="github", status="success")


# =====================================================================
# REDDIT — OAuth 2.0 (authorization code, Basic auth exchange)
# =====================================================================

@router.get("/reddit/authorize")
async def reddit_authorize(token: str):
    """Start Reddit OAuth flow.

    Scope is `identity` only — /api/v1/me returns the username we need
    for later Apify scraping. `duration=temporary` gives a short-lived
    token; we have no use for long-lived Reddit access yet.
    """
    user = await _validate_token(token)

    state = secrets.token_urlsafe(32)
    _store_pending_state(state, user["id"], "reddit")

    params = {
        "client_id": config.REDDIT_CLIENT_ID,
        "response_type": "code",
        "state": state,
        "redirect_uri": _oauth_redirect_uri("reddit"),
        "scope": "identity",
        "duration": "temporary",
    }
    auth_url = f"https://www.reddit.com/api/v1/authorize?{urlencode(params)}"
    return RedirectResponse(auth_url)


@router.get("/reddit/callback")
async def reddit_callback(code: str = None, state: str = None, error: str = None, error_description: str = None):
    """Exchange Reddit authorization code for tokens, then capture identity."""
    if error or not code:
        desc = error_description or error or "authorization_denied"
        return _frontend_redirect("/dashboard/settings/accounts", oauth="reddit", status="error", detail=desc)
    pending = _pop_pending_state(state, "reddit")
    if not pending:
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    user_id = pending["user_id"]

    # Reddit requires HTTP Basic auth (client_id:client_secret) on the
    # token endpoint and a User-Agent header on every API call.
    credentials = base64.b64encode(
        f"{config.REDDIT_CLIENT_ID}:{config.REDDIT_CLIENT_SECRET}".encode()
    ).decode()
    user_agent = config.REDDIT_USER_AGENT

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://www.reddit.com/api/v1/access_token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": user_agent,
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _oauth_redirect_uri("reddit"),
            },
        )

    if resp.status_code != 200:
        return _frontend_redirect("/dashboard/settings/accounts", oauth="reddit", status="error", detail=resp.text)

    token_data = resp.json()
    if not token_data.get("access_token"):
        return _frontend_redirect(
            "/dashboard/settings/accounts", oauth="reddit", status="error", detail="Token exchange failed"
        )

    # Capture username from /api/v1/me. Best-effort — never fail the connect.
    try:
        async with httpx.AsyncClient() as client:
            me_resp = await client.get(
                "https://oauth.reddit.com/api/v1/me",
                headers={
                    "Authorization": f"Bearer {token_data['access_token']}",
                    "User-Agent": user_agent,
                },
            )
        if me_resp.status_code == 200:
            me = me_resp.json() or {}
            if me.get("name"):
                token_data.update(_identity("reddit", me.get("id"), me["name"]))
    except Exception:
        pass

    save_tokens(
        user_id=user_id,
        provider="reddit",
        tokens=token_data,
    )

    return _frontend_redirect("/dashboard/settings/accounts", oauth="reddit", status="success")


# =====================================================================
# GOOGLE — OAuth 2.0 (Calendar + Profile)
# =====================================================================

@router.get("/google/authorize")
async def google_authorize(token: str, features: str = "calendar,docs"):
    """
    Start Google OAuth flow with granular scope selection.

    Args:
        token: Supabase JWT
        features: comma-separated list of 'calendar', 'docs', 'gmail', 'sheets'

    Behaviour around `prompt=consent`:
      - First connect (no stored token): force consent so we get a
        refresh_token alongside the access_token.
      - Update with the same scopes the user already granted: skip the
        OAuth round-trip entirely and bounce back to the dashboard with
        a success state. Without this, clicking "Update Permissions" with
        no checkbox change still threw the user into Google's full
        consent screen, which felt broken.
      - Update with EXPANDING scopes: force consent so Google re-issues
        a token covering the new scope set.
    """
    user = await _validate_token(token)

    scopes = ["openid", "email", "profile"]
    # The Google Docs `documents` scope is intentionally NOT requested — the
    # Brief is stored platform-side (persona_agents.brief_content), not in
    # Google Docs. `drive.file` is retained so the agent can still manage
    # files it creates (or the user explicitly opens via a Picker).
    # Gmail is split into readonly + send (not gmail.modify/mail.google.com)
    # so the agent can search/read and send, but can't delete or manage labels.
    feature_map = {
        "calendar": "https://www.googleapis.com/auth/calendar",
        "docs": "https://www.googleapis.com/auth/drive.file",
        "gmail": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send",
    }

    selected_features = [f.strip() for f in features.split(",") if f.strip() in feature_map]
    if not selected_features:
        # Default to calendar only if none provided or invalid
        selected_features = ["calendar"]

    for feat in selected_features:
        scopes.append(feature_map[feat])

    # Each value in feature_map can itself be a space-separated list of
    # scope URLs (docs has two), so flatten before comparing as sets.
    requested_scope_set = {s for chunk in scopes for s in chunk.split() if s}

    from services.token_store import get_tokens
    existing = get_tokens(user_id=user["id"], provider="google")
    existing_scope_set: set[str] = set()
    if existing:
        existing_scope_set = {s for s in (existing.get("scope") or "").split() if s}

    # Same-or-narrower request when we already have a token → no Google
    # round-trip needed. The existing refresh_token still works.
    if existing and requested_scope_set.issubset(existing_scope_set):
        return _frontend_redirect("/dashboard", oauth="google", status="success", detail="already-granted")

    # Google's re-consent replaces the token's scope set with exactly what's
    # requested here — it does not merge with what was previously granted.
    # Carry existing scopes forward so connecting a new feature (e.g. Gmail)
    # doesn't silently revoke access already granted to another (e.g. Calendar).
    final_scope_set = requested_scope_set | existing_scope_set

    state = secrets.token_urlsafe(32)
    _store_pending_state(state, user["id"], "google")

    params = {
        "response_type": "code",
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": config.GOOGLE_REDIRECT_URI,
        "scope": " ".join(sorted(final_scope_set)),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return RedirectResponse(auth_url)


@router.get("/google/callback")
async def google_callback(code: str = None, state: str = None, error: str = None, error_description: str = None):
    """Exchange Google authorization code for tokens."""
    if error or not code:
        desc = error_description or error or "authorization_denied"
        return _frontend_redirect("/dashboard", oauth="google", status="error", detail=desc)
    pending = _pop_pending_state(state, "google")
    if not pending:
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
        return _frontend_redirect("/dashboard", oauth="google", status="error", detail=resp.text)

    token_data = resp.json()
    save_tokens(
        user_id=user_id,
        provider="google",
        tokens=token_data,
    )

    return _frontend_redirect("/dashboard", oauth="google", status="success")


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
    _store_pending_state(state, user["id"], "notion")

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
async def notion_callback(code: str = None, state: str = None, error: str = None, error_description: str = None):
    """Exchange Notion authorization code for tokens."""
    if error or not code:
        desc = error_description or error or "authorization_denied"
        return _frontend_redirect("/dashboard", oauth="notion", status="error", detail=desc)
    pending = _pop_pending_state(state, "notion")
    if not pending:
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
        return _frontend_redirect("/dashboard", oauth="notion", status="error", detail=resp.text)

    token_data = resp.json()
    # Save token. Notion tokens don't expire, so we don't worry about refresh_token.
    save_tokens(
        user_id=user_id,
        provider="notion",
        tokens=token_data,
    )

    return _frontend_redirect("/dashboard", oauth="notion", status="success")


# =====================================================================
# Helper: validate Supabase JWT to identify the user
# =====================================================================

async def _validate_token(token: str) -> dict:
    """Validate a Supabase JWT and return user info."""
    sb = config.get_supabase()
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
