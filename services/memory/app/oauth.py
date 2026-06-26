"""Minimal OAuth2 authorization-code server for the ChatGPT Action.

Flow: ChatGPT opens /oauth/authorize -> user submits email on the consent page
-> /oauth/login issues a single-use code and redirects back to ChatGPT ->
ChatGPT exchanges the code at /oauth/token for a JWT access token -> the Action
sends that token as Bearer to /ingest.

DEV-GRADE — see docs/CHATGPT_PLUGIN.md:
  * Login is email-only (no password). Replace with password/magic-link auth.
  * No PKCE. Single confidential client. HTTPS assumed in production.
The OAuth plumbing (codes, redirect allowlist, single client, JWT issuance) is
real and production-shaped; only the user-authentication step is a stub.
"""
import hmac
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.auth import issue_access_token, issue_refresh_token, verify_refresh_token
from app.config import settings
from app.db import get_pool
from app.passwords import MIN_PASSWORD_LENGTH, hash_password, verify_password

router = APIRouter(prefix="/oauth", tags=["oauth"])

_CODE_PREFIX = "oauth:code:"
_CODE_TTL_SECONDS = 600


def _check_redirect_uri(redirect_uri: str) -> None:
    if not any(redirect_uri.startswith(p) for p in settings.allowed_redirect_prefixes):
        raise HTTPException(status_code=400, detail="redirect_uri not allowed")


def _check_client(client_id: str, client_secret: str) -> None:
    ok_id = hmac.compare_digest(client_id, settings.oauth_client_id)
    ok_secret = hmac.compare_digest(client_secret, settings.oauth_client_secret)
    if not (ok_id and ok_secret):
        raise HTTPException(status_code=401, detail="invalid client credentials")


@router.get("/authorize", response_class=HTMLResponse)
async def authorize(
    request: Request,
    response_type: str = "code",
    client_id: str = "",
    redirect_uri: str = "",
    state: str = "",
    scope: str = "ingest",
) -> HTMLResponse:
    if response_type != "code":
        raise HTTPException(status_code=400, detail="response_type must be 'code'")
    if not hmac.compare_digest(client_id, settings.oauth_client_id):
        raise HTTPException(status_code=400, detail="unknown client_id")
    _check_redirect_uri(redirect_uri)

    return HTMLResponse(_consent_page(redirect_uri, state, scope))


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    redirect_uri: str = Form(...),
    state: str = Form(""),
    scope: str = Form("ingest"),
):
    """Email + password sign-in / sign-up. New email creates an account; an
    existing one is verified. On bad input the consent page is re-rendered with
    an error (no redirect)."""
    _check_redirect_uri(redirect_uri)
    email = email.strip().lower()

    if len(password) < MIN_PASSWORD_LENGTH:
        return HTMLResponse(_consent_page(
            redirect_uri, state, scope, email=email,
            error=f"Password must be at least {MIN_PASSWORD_LENGTH} characters."), status_code=400)

    pool = get_pool()
    row = await pool.fetchrow("SELECT id, password_hash FROM users WHERE email = $1", email)
    if row is None:
        # New account.
        user_id = await pool.fetchval(
            "INSERT INTO users (email, display_name, password_hash) VALUES ($1, $1, $2) RETURNING id",
            email, hash_password(password))
    elif row["password_hash"] is None:
        # Legacy/OAuth-only row with no password yet — set it on first sign-in.
        user_id = row["id"]
        await pool.execute("UPDATE users SET password_hash = $1 WHERE id = $2", hash_password(password), user_id)
    elif verify_password(password, row["password_hash"]):
        user_id = row["id"]
    else:
        return HTMLResponse(_consent_page(
            redirect_uri, state, scope, email=email, error="Incorrect password."), status_code=401)

    code = secrets.token_urlsafe(32)
    await request.app.state.arq.set(f"{_CODE_PREFIX}{code}", str(user_id), ex=_CODE_TTL_SECONDS)
    separator = "&" if "?" in redirect_uri else "?"
    location = f"{redirect_uri}{separator}{urlencode({'code': code, 'state': state})}"
    return RedirectResponse(location, status_code=302)


def _consent_page(redirect_uri: str, state: str, scope: str, error: str = "", email: str = "") -> str:
    error_html = f'<p class="err">{error}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect to ZYND</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    background:radial-gradient(1200px 600px at 50% -10%, #2a2350, #0d0b1f 60%);
    color:#e7e6f0; padding:24px;
  }}
  .card {{
    width:100%; max-width:420px; background:rgba(255,255,255,0.04);
    border:1px solid rgba(255,255,255,0.08); border-radius:18px; padding:36px 32px;
    box-shadow:0 30px 80px rgba(0,0,0,0.45);
  }}
  .brand {{ display:flex; align-items:center; gap:10px; margin-bottom:22px; }}
  .logo {{ width:34px; height:34px; border-radius:9px;
    background:linear-gradient(135deg,#7c5cff,#4d8cff); display:flex; align-items:center;
    justify-content:center; font-weight:700; color:#fff; font-size:18px; }}
  .brand b {{ font-size:18px; letter-spacing:1px; }}
  h1 {{ font-size:22px; margin:0 0 8px; }}
  p.sub {{ margin:0 0 22px; color:#a7a4c0; font-size:14.5px; line-height:1.5; }}
  label {{ display:block; font-size:13px; color:#b9b6d4; margin:14px 0 8px; }}
  input {{
    width:100%; padding:13px 14px; border-radius:11px; font-size:15px;
    background:#15132b; border:1px solid rgba(255,255,255,0.12); color:#fff; outline:none;
  }}
  input:focus {{ border-color:#7c5cff; box-shadow:0 0 0 3px rgba(124,92,255,0.25); }}
  button {{
    margin-top:22px; width:100%; padding:13px; border:0; border-radius:11px; cursor:pointer;
    font-size:15px; font-weight:600; color:#fff; background:linear-gradient(135deg,#7c5cff,#4d8cff);
  }}
  button:hover {{ filter:brightness(1.08); }}
  .err {{ margin:14px 0 0; padding:10px 12px; border-radius:9px; font-size:13px;
    background:rgba(255,80,80,0.12); border:1px solid rgba(255,80,80,0.3); color:#ffb4b4; }}
  .foot {{ margin-top:18px; font-size:12px; color:#7d7a98; line-height:1.5; }}
</style>
</head>
<body>
  <div class="card">
    <div class="brand"><div class="logo">Z</div><b>ZYND</b></div>
    <h1>Connect ChatGPT to ZYND</h1>
    <p class="sub">Sign in or create an account. Your conversations become a private,
      evolving context graph &mdash; owned by you, usable by any AI you allow.</p>
    {error_html}
    <form method="post" action="/oauth/login">
      <input type="hidden" name="redirect_uri" value="{redirect_uri}">
      <input type="hidden" name="state" value="{state}">
      <input type="hidden" name="scope" value="{scope}">
      <label for="email">Email</label>
      <input id="email" name="email" type="email" required placeholder="you@example.com" value="{email}" autofocus>
      <label for="password">Password</label>
      <input id="password" name="password" type="password" required minlength="8" placeholder="At least 8 characters">
      <button type="submit">Continue</button>
    </form>
    <p class="foot">New here? Just pick a password to create your account. You can revoke access anytime.</p>
  </div>
</body></html>"""


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
