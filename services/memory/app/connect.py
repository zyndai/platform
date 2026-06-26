"""Standalone connect page: a non-ChatGPT user creates/signs into a ZYND account
and gets a long-lived token + a ready-to-paste config for their MCP client
(Claude Desktop, Cursor, …). Styled to match the ZYND dashboard (black /
Helvetica Neue / violet) with an animated-beam hero showing every AI feeding ZYND.
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
  :root{--bg:#000;--fg:#f6f6f6;--muted:#8b90a6;--accent:#8B5CF6;--accent2:#3B82F6;--line:rgba(255,255,255,.08)}
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;background:#000;color:var(--fg);
    font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;letter-spacing:-.03em;
    display:flex;align-items:center;justify-content:center;padding:40px 20px;
    background-image:radial-gradient(900px 520px at 50% -8%,rgba(139,92,246,.18),transparent 60%)}
  .wrap{width:100%;max-width:540px;text-align:center}
  .kicker{display:inline-flex;align-items:center;gap:8px;font-size:12.5px;color:var(--muted);
    border:1px solid var(--line);padding:6px 12px 6px 6px;border-radius:999px}
  .kicker .z{width:20px;height:20px;border-radius:6px;background:linear-gradient(135deg,#8B5CF6,#3B82F6);
    display:inline-flex;align-items:center;justify-content:center;font-weight:700;font-size:12px;color:#fff}
  h1{font-size:46px;line-height:1.02;font-weight:500;letter-spacing:-.04em;margin:20px 0 12px}
  .sub{color:var(--muted);font-size:15px;line-height:1.55;margin:0 auto 22px;max-width:440px}
  .beam{position:relative;width:100%;height:188px;margin:6px 0 26px}
  svg.beams{position:absolute;inset:0;width:100%;height:100%;z-index:1}
  .base{stroke:rgba(255,255,255,.09);stroke-width:1.5;fill:none}
  .flow{stroke:url(#g);stroke-width:2;fill:none;stroke-linecap:round;stroke-dasharray:14 86;
    filter:drop-shadow(0 0 5px rgba(139,92,246,.85));animation:flow 2.6s linear infinite}
  @keyframes flow{from{stroke-dashoffset:100}to{stroke-dashoffset:0}}
  .node{position:absolute;transform:translate(-50%,-50%);width:46px;height:46px;border-radius:13px;
    background:#0e0e15;border:1px solid var(--line);display:flex;align-items:center;justify-content:center;
    font-size:10px;color:#cfd2de;box-shadow:0 8px 26px rgba(0,0,0,.55);z-index:2}
  .node.center{width:62px;height:62px;border-radius:17px;background:linear-gradient(135deg,#8B5CF6,#3B82F6);
    color:#fff;font-weight:700;font-size:20px;box-shadow:0 0 42px rgba(139,92,246,.55)}
  .card{background:rgba(255,255,255,.03);border:1px solid var(--line);border-radius:18px;padding:24px 22px;text-align:left}
  label{display:block;font-size:12.5px;color:var(--muted);margin:14px 0 7px}
  input{width:100%;padding:12px 14px;border-radius:11px;font-size:15px;background:#0c0c12;
    border:1px solid var(--line);color:#fff;outline:none;font-family:inherit;letter-spacing:-.02em}
  input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(139,92,246,.22)}
  button{margin-top:20px;width:100%;padding:13px;border:0;border-radius:11px;cursor:pointer;font-size:15px;
    font-weight:500;color:#fff;font-family:inherit;letter-spacing:-.02em;background:linear-gradient(135deg,#8B5CF6,#3B82F6)}
  button:hover{filter:brightness(1.08)}
  .err{margin-bottom:8px;padding:10px 12px;border-radius:9px;font-size:13px;
    background:rgba(255,80,80,.12);border:1px solid rgba(255,80,80,.3);color:#ffb4b4}
  .foot{margin-top:14px;font-size:12px;color:#6b7088;line-height:1.5;text-align:center}
  pre{background:#0a0a10;border:1px solid var(--line);border-radius:12px;padding:14px;font-size:12px;
    overflow:auto;white-space:pre-wrap;word-break:break-all;color:#cdd2e6;
    font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  .ok{display:inline-flex;align-items:center;gap:8px;color:#8B5CF6;font-size:14px;margin-bottom:6px}
</style>"""

# Animated-beam hero: 5 AI nodes -> ZYND center, light flowing inward (the whole idea).
_BEAM = """<div class="beam">
  <svg class="beams" viewBox="0 0 540 188" preserveAspectRatio="none">
    <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#8B5CF6"/><stop offset="1" stop-color="#3B82F6"/></linearGradient></defs>
    <path class="base" d="M70 38 Q175 38 270 94" pathLength="100"/>
    <path class="flow" d="M70 38 Q175 38 270 94" pathLength="100" style="animation-delay:0s"/>
    <path class="base" d="M70 94 L270 94" pathLength="100"/>
    <path class="flow" d="M70 94 L270 94" pathLength="100" style="animation-delay:.5s"/>
    <path class="base" d="M70 150 Q175 150 270 94" pathLength="100"/>
    <path class="flow" d="M70 150 Q175 150 270 94" pathLength="100" style="animation-delay:1s"/>
    <path class="base" d="M470 56 Q365 56 270 94" pathLength="100"/>
    <path class="flow" d="M470 56 Q365 56 270 94" pathLength="100" style="animation-delay:.8s"/>
    <path class="base" d="M470 132 Q365 132 270 94" pathLength="100"/>
    <path class="flow" d="M470 132 Q365 132 270 94" pathLength="100" style="animation-delay:1.4s"/>
  </svg>
  <div class="node" style="left:13%;top:20%">GPT</div>
  <div class="node" style="left:13%;top:50%">Claude</div>
  <div class="node" style="left:13%;top:80%">Cursor</div>
  <div class="node" style="left:87%;top:30%">Gemini</div>
  <div class="node" style="left:87%;top:70%">Grok</div>
  <div class="node center" style="left:50%;top:50%">Z</div>
</div>"""

_FORM_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Connect to ZYND</title>""" + _CSS + """</head>
<body><div class="wrap">
  <div class="kicker"><span class="z">Z</span> ZYND &middot; one memory, every AI</div>
  <h1>Connect any AI<br>to your memory</h1>
  <p class="sub">ZYND turns your conversations into a memory you own — and carries it across
   ChatGPT, Claude, Cursor, and any AI you connect.</p>
  """ + _BEAM + """
  <div class="card">
    %%ERROR%%
    <form method="post" action="/connect">
      <label>Email</label>
      <input name="email" type="email" required value="%%EMAIL%%" placeholder="you@example.com" autofocus>
      <label>Password</label>
      <input name="password" type="password" required minlength="8" placeholder="At least 8 characters">
      <button type="submit">Get my token</button>
    </form>
    <p class="foot">New email creates an account. Your token is private — treat it like a password.</p>
  </div>
</div></body></html>"""

_SUCCESS_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ZYND connected</title>""" + _CSS + """</head>
<body><div class="wrap">
  <div class="kicker"><span class="z">Z</span> ZYND</div>
  <h1>You're connected</h1>
  <p class="sub">Add this to your MCP client (Claude Desktop:
   <code>claude_desktop_config.json</code>), then restart it.</p>
  <div class="card">
    <div class="ok">&#10003; Your connection config</div>
    <pre>%%CONFIG%%</pre>
    <p class="foot">Your AI now has ZYND tools: recall your context, confirm/forget facts, and find
     similar people. Lost the token? Come back here and sign in again.</p>
  </div>
</div></body></html>"""


def _form(error: str = "", email: str = "") -> str:
    err = f'<div class="err">{html.escape(error)}</div>' if error else ""
    return _FORM_HTML.replace("%%ERROR%%", err).replace("%%EMAIL%%", html.escape(email, quote=True))


def _success(token: str) -> str:
    base = settings.public_base_url.rstrip("/")
    cfg = (
        '{\n  "mcpServers": {\n    "zynd": {\n      "command": "npx",\n'
        '      "args": ["-y", "mcp-remote", "' + base + '/mcp",\n'
        '               "--header", "Authorization: Bearer ' + token + '"]\n    }\n  }\n}'
    )
    return _SUCCESS_HTML.replace("%%CONFIG%%", html.escape(cfg))


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
