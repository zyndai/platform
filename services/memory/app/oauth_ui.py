"""Self-hosted OAuth sign-in page for MCP connectors (Claude / ChatGPT).

Platform-agnostic: the memory layer signs the user in itself through Supabase
(Google / LinkedIn OIDC) — the providers already trusted by app.supabase_auth.py
— with no cards/persona dependency. After sign-in, the page POSTs the Supabase
session to /oauth/complete (same origin), which resolves the EXISTING memory
user (lookup-only; never creates) and returns the redirect URL back to the
connector's registered callback.

Mounted in app/main.py. Supabase configuration comes from the primary trusted
project (first entry of TRUSTED_SUPABASE_PROJECTS); the callback URL
{public_base_url}/oauth/login/callback must be registered as an allowed
redirect in that Supabase project.
"""
import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.config import settings

router = APIRouter(prefix="/oauth", tags=["oauth"])

_CSS = """<style>
  :root{--bg:#000;--fg:#f6f6f6;--muted:#8b90a6;--accent:#8B5CF6;--accent2:#3B82F6;--line:rgba(255,255,255,.08)}
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;background:#000;color:var(--fg);
    font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;letter-spacing:-.03em;
    display:flex;align-items:center;justify-content:center;padding:40px 20px;
    background-image:radial-gradient(900px 520px at 50% -8%,rgba(139,92,246,.18),transparent 60%)}
  .wrap{width:100%;max-width:440px;text-align:center}
  .kicker{display:inline-flex;align-items:center;gap:8px;font-size:12.5px;color:var(--muted);
    border:1px solid var(--line);padding:6px 12px 6px 6px;border-radius:999px}
  .kicker .z{width:20px;height:20px;border-radius:6px;background:linear-gradient(135deg,#8B5CF6,#3B82F6);
    display:inline-flex;align-items:center;justify-content:center;font-weight:700;font-size:12px;color:#fff}
  h1{font-size:32px;line-height:1.05;font-weight:500;letter-spacing:-.04em;margin:20px 0 10px}
  .sub{color:var(--muted);font-size:14.5px;line-height:1.55;margin:0 auto 24px;max-width:380px}
  .card{background:rgba(255,255,255,.03);border:1px solid var(--line);border-radius:18px;padding:22px}
  button{margin-top:14px;width:100%;padding:13px;border:0;border-radius:11px;cursor:pointer;font-size:15px;
    font-weight:500;color:#fff;font-family:inherit;letter-spacing:-.02em;background:linear-gradient(135deg,#8B5CF6,#3B82F6)}
  button:first-of-type{margin-top:0}
  button:hover{filter:brightness(1.08)}
  .err{margin-bottom:10px;padding:12px 14px;border-radius:9px;font-size:13px;line-height:1.5;
    background:rgba(255,80,80,.12);border:1px solid rgba(255,80,80,.3);color:#ffb4b4;text-align:left}
  .spinner{width:28px;height:28px;border:3px solid #333;border-top-color:var(--accent);border-radius:50%;
    animation:spin .7s linear infinite;margin:0 auto 12px}
  @keyframes spin{to{transform:rotate(360deg)}}
  .foot{margin-top:16px;font-size:12px;color:#6b7088;line-height:1.5}
  a{color:#8B5CF6}
</style>"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title>" + _CSS + "</head><body>" + body + "</body></html>"
    )


def _supabase_project() -> tuple[str, str] | None:
    projects = settings.trusted_supabase_project_list
    if not projects:
        return None
    url, key = projects[0]
    if not (url and key):
        return None
    return url.rstrip("/"), key


def _js_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "")
        .replace("</", "<\\/")
    )
    return f'"{escaped}"'


_LOGIN_BODY = """<div class="wrap">
  <div class="kicker"><span class="z">Z</span> ZYND &middot; connect your memory</div>
  <h1>Sign in to ZYND</h1>
  <p class="sub">Verify your account so your AI can use ZYND tools. Connector
   connections need an existing ZYND account &mdash; new accounts are created
   on cards.zynd.ai.</p>
  <div class="card">
    %%ERROR%%
    <button data-provider="google">Continue with Google</button>
    <button data-provider="linkedin_oidc">Continue with LinkedIn</button>
  </div>
  <p class="foot">By continuing you agree to share your verified email with ZYND.</p>
</div>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<script>
(function(){
  var REQ = %%REQ%%;
  var SUPABASE_URL = %%SUPABASE_URL%%;
  var SUPABASE_ANON_KEY = %%SUPABASE_ANON_KEY%%;
  var CALLBACK = %%CALLBACK%%;
  var key = "zynd_oauth_req";
  if (REQ) { try { sessionStorage.setItem(key, REQ); } catch(e) {} }
  var pending = REQ || sessionStorage.getItem(key);
  if (!pending) {
    document.body.innerHTML = '<div class="wrap"><div class="card"><div class="err">' +
      'Missing connection request &mdash; go back to your AI app and start the connection again.</div></div></div>';
    return;
  }
  if (window.supabase === undefined) {
    document.body.innerHTML = '<div class="wrap"><div class="card"><div class="err">' +
      'Sign-in library failed to load &mdash; refresh the page to retry.</div></div></div>';
    return;
  }
  var sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  function showError(msg){
    var card = document.querySelector('.card');
    var div = document.createElement('div'); div.className='err';
    div.textContent = msg; card.insertBefore(div, card.firstChild);
  }
  function done(token) {
    fetch('/oauth/complete', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({req: pending, supabase_token: token})
    }).then(function(r){ return r.json().then(function(d){ return {ok:r.ok, data:d}; }); })
    .then(function(r){
      if (!r.ok) {
        showError(r.data.detail || 'Sign-in failed &mdash; please try again.');
        return;
      }
      try { sessionStorage.removeItem(key); } catch(e) {}
      window.location.href = r.data.redirect_url;
    }).catch(function(){ showError('Sign-in failed &mdash; please try again.'); });
  }
  document.querySelectorAll('button[data-provider]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var provider = btn.getAttribute('data-provider');
      sb.auth.signInWithOAuth({provider: provider, options: {redirectTo: CALLBACK}})
        .then(function(r){ if (r.error) { showError(r.error.message); } });
    });
  });
  // Already signed in (same browser) -> complete immediately.
  sb.auth.getSession().then(function(r){
    if (r.data && r.data.session && r.data.session.access_token) done(r.data.session.access_token);
  });
})();
</script>"""

_CALLBACK_BODY = """<div class="wrap">
  <div class="kicker"><span class="z">Z</span> ZYND &middot; connect your memory</div>
  <div class="card">
    <div class="spinner"></div>
    <p class="sub" id="msg">Completing sign-in&hellip;</p>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<script>
(function(){
  var SUPABASE_URL = %%SUPABASE_URL%%;
  var SUPABASE_ANON_KEY = %%SUPABASE_ANON_KEY%%;
  var key = "zynd_oauth_req";
  var req = sessionStorage.getItem(key) || %%REQ%%;
  function fail(msg){
    var card = document.querySelector('.card');
    card.innerHTML = '<div class="err">' + msg + '</div>' +
      '<p class="foot"><a href="/oauth/login">Try again</a></p>';
  }
  if (!req) { fail('Missing connection request &mdash; start the connection again in your AI app.'); return; }
  if (window.supabase === undefined) { fail('Sign-in library failed to load &mdash; refresh to retry.'); return; }
  var sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  sb.auth.getSession().then(function(r){
    if (r.error || !r.data || !r.data.session) { fail('Sign-in failed &mdash; no session returned.'); return; }
    fetch('/oauth/complete', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({req: req, supabase_token: r.data.session.access_token})
    }).then(function(resp){ return resp.json().then(function(d){ return {ok:resp.ok, data:d}; }); })
    .then(function(r){
      if (!r.ok) { fail(r.data.detail || 'Sign-in failed &mdash; please try again.'); return; }
      try { sessionStorage.removeItem(key); } catch(e) {}
      window.location.href = r.data.redirect_url;
    }).catch(function(){ fail('Sign-in failed &mdash; please try again.'); });
  });
})();
</script>"""


def _render_login(req: str, error: str = "") -> HTMLResponse:
    project = _supabase_project()
    if not project:
        return _page("ZYND", """<div class="wrap"><div class="card"><div class="err">"""
                     "OAuth sign-in is not configured on this server.</div></div></div>")
    url, key = project
    body = _LOGIN_BODY
    body = body.replace("%%ERROR%%", f'<div class="err">{html.escape(error)}</div>' if error else "")
    body = body.replace("%%REQ%%", _js_string(req))
    body = body.replace("%%SUPABASE_URL%%", _js_string(url))
    body = body.replace("%%SUPABASE_ANON_KEY%%", _js_string(key))
    body = body.replace("%%CALLBACK%%", _js_string(settings.public_base_url.rstrip("/") + "/oauth/login/callback"))
    return _page("Sign in to ZYND", body)


def _render_callback(req_param: str) -> HTMLResponse:
    project = _supabase_project()
    if not project:
        return _page("ZYND", """<div class="wrap"><div class="card"><div class="err">"""
                     "OAuth sign-in is not configured on this server.</div></div></div>")
    url, key = project
    body = _CALLBACK_BODY
    body = body.replace("%%REQ%%", _js_string(req_param))
    body = body.replace("%%SUPABASE_URL%%", _js_string(url))
    body = body.replace("%%SUPABASE_ANON_KEY%%", _js_string(key))
    return _page("Completing sign-in", body)


@router.get("/login", response_class=HTMLResponse)
async def login(request: Request) -> HTMLResponse:
    """Sign-in page for MCP connector OAuth. Embeds the signed authorize
    request (`zynd_oauth`) so it survives the Supabase provider round-trip."""
    req = request.query_params.get("zynd_oauth", "")
    return _render_login(req)


@router.get("/login/callback", response_class=HTMLResponse)
async def login_callback(request: Request) -> HTMLResponse:
    """Post-provider callback. Supabase OAuth PKCE returns the session through
    the URL; supabase-js completes the exchange, then this page POSTs the
    session to /oauth/complete and follows the connector redirect."""
    req = request.query_params.get("zynd_oauth", "")
    return _render_callback(req)