"""Standalone connect page: a non-ChatGPT user creates/signs into a ZYND account
and gets a long-lived token + a ready-to-paste config for their MCP client
(Claude Desktop, Cursor, …). Reuses the same email+password auth as OAuth.
"""
import html

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse

from app.auth import issue_personal_token
from app.config import settings
from app.db import get_pool
from app.passwords import MIN_PASSWORD_LENGTH, hash_password, verify_password

router = APIRouter(tags=["connect"])

_CSS = """<style>
  *{box-sizing:border-box} body{margin:0;min-height:100vh;display:flex;align-items:center;
   justify-content:center;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
   background:radial-gradient(1200px 600px at 50% -10%,#2a2350,#0d0b1f 60%);color:#e7e6f0;padding:24px}
  .card{width:100%;max-width:560px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);
   border-radius:18px;padding:34px 30px;box-shadow:0 30px 80px rgba(0,0,0,.45)}
  .brand{display:flex;align-items:center;gap:10px;margin-bottom:18px}
  .logo{width:32px;height:32px;border-radius:9px;background:linear-gradient(135deg,#7c5cff,#4d8cff);
   display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff}
  h1{font-size:21px;margin:0 0 8px} p.sub{margin:0 0 22px;color:#a7a4c0;font-size:14px;line-height:1.5}
  label{display:block;font-size:13px;color:#b9b6d4;margin:14px 0 8px}
  input{width:100%;padding:12px 14px;border-radius:11px;font-size:15px;background:#15132b;
   border:1px solid rgba(255,255,255,.12);color:#fff;outline:none}
  input:focus{border-color:#7c5cff;box-shadow:0 0 0 3px rgba(124,92,255,.25)}
  button{margin-top:20px;width:100%;padding:13px;border:0;border-radius:11px;cursor:pointer;font-size:15px;
   font-weight:600;color:#fff;background:linear-gradient(135deg,#7c5cff,#4d8cff)}
  pre{background:#0f0d22;border:1px solid rgba(255,255,255,.1);border-radius:11px;padding:14px;
   font-size:12.5px;overflow:auto;white-space:pre-wrap;word-break:break-all}
  .err{margin-top:14px;padding:10px 12px;border-radius:9px;font-size:13px;background:rgba(255,80,80,.12);
   border:1px solid rgba(255,80,80,.3);color:#ffb4b4}
  code{color:#b9acff}
</style>"""


def _form(error: str = "", email: str = "") -> str:
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Connect to ZYND</title>{_CSS}</head>
<body><div class="card">
  <div class="brand"><div class="logo">Z</div><b>ZYND</b></div>
  <h1>Connect any AI to your ZYND memory</h1>
  <p class="sub">Sign in or create an account to get a token for your MCP client
   (Claude Desktop, Cursor, etc.). New email = new account.</p>
  {err}
  <form method="post" action="/connect">
    <label>Email</label>
    <input name="email" type="email" required value="{html.escape(email, quote=True)}" placeholder="you@example.com" autofocus>
    <label>Password</label>
    <input name="password" type="password" required minlength="8" placeholder="At least 8 characters">
    <button type="submit">Get my token</button>
  </form>
</div></body></html>"""


def _success(token: str) -> str:
    base = settings.public_base_url.rstrip("/")
    cfg = (
        '{\n  "mcpServers": {\n    "zynd": {\n      "command": "npx",\n'
        '      "args": ["-y", "mcp-remote", "' + base + '/mcp",\n'
        '               "--header", "Authorization: Bearer ' + token + '"]\n    }\n  }\n}'
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ZYND connected</title>{_CSS}</head>
<body><div class="card">
  <div class="brand"><div class="logo">Z</div><b>ZYND</b></div>
  <h1>You're connected ✅</h1>
  <p class="sub">Add this to your MCP client config (Claude Desktop:
   <code>claude_desktop_config.json</code>), then restart it. Keep this token private —
   it's like a password.</p>
  <pre>{html.escape(cfg)}</pre>
  <p class="sub">Your AI now has ZYND tools: recall your context, confirm/forget facts,
   and find similar people. Lost the token? Just come back here and sign in again.</p>
</div></body></html>"""


@router.get("/connect", response_class=HTMLResponse)
async def connect_form() -> HTMLResponse:
    return HTMLResponse(_form())


@router.post("/connect", response_class=HTMLResponse)
async def connect(email: str = Form(...), password: str = Form(...)) -> HTMLResponse:
    email = email.strip().lower()
    if len(password) < MIN_PASSWORD_LENGTH:
        return HTMLResponse(_form(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", email),
                            status_code=400)
    pool = get_pool()
    row = await pool.fetchrow("SELECT id, password_hash FROM users WHERE email = $1", email)
    if row is None:
        user_id = await pool.fetchval(
            "INSERT INTO users (email, display_name, password_hash) VALUES ($1,$1,$2) RETURNING id",
            email, hash_password(password))
    elif row["password_hash"] and verify_password(password, row["password_hash"]):
        user_id = row["id"]
    else:
        # Wrong password, or a password-less existing account (self-heal/legacy). Never
        # set a password on an existing account from this unauthenticated endpoint
        # (account-takeover vector).
        return HTMLResponse(_form("Incorrect password.", email), status_code=401)

    return HTMLResponse(_success(issue_personal_token(str(user_id))))
