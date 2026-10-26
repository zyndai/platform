"""Self-hosted OAuth sign-in and explicit consent for MCP connectors.

Platform-agnostic: the memory layer signs the user in itself through Supabase
(Google / LinkedIn OIDC) — the providers already trusted by app.supabase_auth.py
— with no cards/persona dependency. After sign-in, the server verifies the
session and displays the existing account before an explicit Allow or Cancel.

Mounted in app/main.py. Supabase configuration comes from the primary trusted
project (first entry of TRUSTED_SUPABASE_PROJECTS); the callback URL
{public_base_url}/oauth/login/callback must be registered as an allowed
redirect in that Supabase project.
"""
import base64
import html
import json
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.config import settings

router = APIRouter(prefix="/oauth", tags=["oauth"])

_LOGO_SRC = "data:image/png;base64," + base64.b64encode(
    (Path(__file__).resolve().parent / "assets" / "zynd-logo.png").read_bytes()
).decode("ascii")

# Same faces and tokens as the public card, the editor and the directory on
# cards.zynd.ai (apps/cards-web: components/editions, components/discover), so
# the sign-in a connector opens reads as part of the product.
_FONTS_URL = ("https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600;700;800"
              "&amp;family=Space+Mono:wght@400;700&amp;display=swap")
_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    # Non-blocking: the page is drawn in the fallback faces if Google Fonts is slow or blocked.
    f'<link rel="stylesheet" href="{_FONTS_URL}" media="print" onload="this.media=\'all\'">'
    f'<noscript><link rel="stylesheet" href="{_FONTS_URL}"></noscript>'
)

_CSS = """<style>
  :root{--ink:#1E1B4B;--soft:#5B5B7E;--faint:#8B8AA8;--accent:#6C5CE7;--accent-hi:#5B4BD6;
    --line:#E6E3F6;--tint:#F3F1FF;--edge:#D7D1FF;
    --ui:"Plus Jakarta Sans",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    --mono:"Space Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
  *{box-sizing:border-box}
  [hidden]{display:none!important}
  body{margin:0;min-height:100vh;color:var(--ink);font-family:var(--ui);line-height:1.45;
    -webkit-font-smoothing:antialiased;background-color:#F3F1FB;
    background-image:linear-gradient(180deg,#ECE9FB 0%,#F5F3FE 38%,#F3F1FB 100%)}
  a{color:var(--accent-hi);font-weight:700;text-decoration:none}
  a:hover{text-decoration:underline}
  :focus-visible{outline:3px solid var(--accent);outline-offset:2px}
  .shell{min-height:100vh;display:flex;flex-direction:column}
  .top{display:flex;align-items:center;gap:10px;width:100%;max-width:1240px;margin:0 auto;
    padding:16px clamp(16px,4vw,40px)}
  .brand{display:inline-flex;align-items:center;gap:8px;color:var(--ink);font:800 18px/1 var(--ui);
    letter-spacing:-.02em}
  .brand:hover{text-decoration:none}
  .brand img{display:block;width:26px;height:26px}
  .crumb{font:400 12px/1.2 var(--mono);color:#64748b}
  .crumb strong{color:#1e293b;font-weight:700}
  .stage{flex:1;display:flex;align-items:center;justify-content:center;padding:24px 16px 48px}
  .wrap{width:100%;max-width:460px}
  .eyebrow{display:inline-flex;align-items:center;gap:7px;padding:5px 11px;border-radius:999px;
    border:1px solid var(--edge);background:rgba(255,255,255,.7);color:var(--accent-hi);
    font:700 10.5px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase}
  .eyebrow i{width:6px;height:6px;border-radius:50%;background:var(--accent)}
  h1{margin:14px 0 18px;font:800 clamp(28px,6vw,36px)/1.1 var(--ui);letter-spacing:-.03em;word-spacing:.08em}
  .sub{margin:-8px 0 22px;font:500 14.5px/1.55 var(--ui);color:var(--soft)}
  .card{position:relative;isolation:isolate;overflow:hidden;padding:22px;border-radius:24px;
    background:#fff;border:1px solid var(--line);box-shadow:0 18px 40px -34px rgba(30,27,75,.45)}
  .card::before{content:"";position:absolute;inset:0;z-index:-1;pointer-events:none;
    background:radial-gradient(360px 160px at 96% -22%,rgba(167,139,250,.30),transparent 70%),
      radial-gradient(300px 150px at 100% 112%,rgba(253,186,140,.26),transparent 70%),
      radial-gradient(260px 140px at 52% -24%,rgba(147,197,253,.24),transparent 70%)}
  .card.center{text-align:center}
  .stack,.actions{display:grid;gap:10px}
  .actions{margin-top:16px}
  .btn{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;height:48px;
    padding:0 20px;border-radius:13px;border:1px solid #E2E8F0;background:#fff;color:var(--ink);
    font:700 14px/1 var(--ui);cursor:pointer;
    transition:background .15s,border-color .15s,transform .1s}
  .btn:hover:not(:disabled){border-color:var(--edge);background:var(--tint)}
  .btn:active:not(:disabled){transform:translateY(1px)}
  .btn:disabled{opacity:.55;cursor:wait}
  .btn svg{flex:none}
  .btn.primary{border-color:transparent;background:var(--accent);color:#fff;
    box-shadow:0 12px 24px -14px rgba(108,92,231,.9)}
  .btn.primary:hover:not(:disabled){background:var(--accent-hi)}
  .details{color:var(--soft);font:500 14px/1.6 var(--ui)}
  .details p{margin:0 0 10px}
  .details strong{color:var(--ink);font-weight:700}
  .details .note{margin:-4px 0 14px;font-size:12.5px;line-height:1.5;color:var(--faint)}
  .fields{margin:0 0 14px;border-radius:14px;background:var(--tint);border:1px solid var(--line)}
  .field{display:flex;align-items:baseline;justify-content:space-between;gap:16px;margin:0;padding:11px 14px}
  .field+.field{border-top:1px solid var(--line)}
  .field dt{flex:none;font:700 10.5px/1.4 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--faint)}
  .field dd{margin:0;min-width:0;text-align:right;font:700 14px/1.35 var(--ui);color:var(--ink);overflow-wrap:anywhere}
  .field dd.mono{font:400 12.5px/1.45 var(--mono)}
  .perms{list-style:none;padding:0;margin:0 0 12px;display:grid;gap:6px}
  .perms li{position:relative;padding-left:26px}
  .perms li::before{content:"\\2713";position:absolute;left:0;top:2px;width:17px;height:17px;
    border-radius:50%;background:var(--tint);color:var(--accent-hi);font:700 11px/17px var(--mono);
    text-align:center}
  .err{margin:0 0 14px;padding:12px 14px;border-radius:14px;font:600 13px/1.5 var(--ui);
    background:#FFF1F2;border:1px solid #FECDD3;color:#BE123C;text-align:left}
  .err:last-child{margin-bottom:0}
  .spinner{width:28px;height:28px;border:3px solid var(--line);border-top-color:var(--accent);
    border-radius:50%;animation:spin .7s linear infinite;margin:0 auto 12px}
  @keyframes spin{to{transform:rotate(360deg)}}
  @media (prefers-reduced-motion:reduce){.spinner{animation-duration:2.4s}}
  .foot{margin:18px 0 0;text-align:center;font:400 12px/1.5 var(--mono);letter-spacing:.04em;color:var(--faint)}
  .reviewer{margin-top:18px;padding-top:14px;border-top:1px solid var(--line)}
  .reviewer summary{cursor:pointer;color:var(--faint);font:700 11px/1 var(--mono);
    letter-spacing:.12em;text-transform:uppercase}
  .reviewer input{display:block;width:100%;height:46px;margin-top:10px;padding:0 14px;border-radius:13px;
    border:1px solid var(--edge);background:#fff;color:var(--ink);font:600 14px/1 var(--ui)}
  .reviewer input:focus{outline:0;border-color:var(--accent);box-shadow:0 0 0 4px rgba(108,92,231,.14)}
  .reviewer .btn{margin-top:10px}
  .legal{display:flex;flex-wrap:wrap;justify-content:center;gap:6px 16px;padding:0 16px 28px;
    font:400 12px/1.4 var(--mono);letter-spacing:.04em;color:var(--faint)}
  .legal a{color:var(--faint);font-weight:400}
  .legal a:hover{color:var(--ink)}
  @media (max-width:480px){.card{padding:18px;border-radius:22px}.stage{align-items:flex-start;padding-top:8px}}
</style>"""

# Shown only on a plugin-client request while PLUGIN_REVIEW_EMAILS is set: the
# demo account OpenAI's reviewers use. The server enforces who may use it
# (supabase_identity allow_reviewer); this block is just the entry point.
_REVIEWER_BLOCK = """<details class="reviewer">
      <summary>Reviewer sign-in</summary>
      <form id="reviewer-form" autocomplete="off">
        <input id="reviewer-email" type="email" placeholder="Reviewer email" required autocomplete="username">
        <input id="reviewer-password" type="password" placeholder="Password" required autocomplete="current-password">
        <button type="submit" class="btn primary">Sign in</button>
      </form>
    </details>"""

_GOOGLE_ICON = (
    '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">'
    '<path fill="#4285F4" d="M23.49 12.27c0-.79-.07-1.54-.19-2.27H12v4.51h6.47c-.29 1.48-1.14 2.73-2.4 3.58v3h3.86c2.26-2.09 3.56-5.17 3.56-8.82z"/>'
    '<path fill="#34A853" d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.86-3c-1.08.72-2.45 1.16-4.07 1.16-3.13 0-5.78-2.11-6.73-4.96H1.29v3.09C3.26 21.3 7.31 24 12 24z"/>'
    '<path fill="#FBBC05" d="M5.27 14.29c-.25-.72-.38-1.49-.38-2.29s.14-1.57.38-2.29V6.62H1.29C.47 8.24 0 10.06 0 12s.47 3.76 1.29 5.38l3.98-3.09z"/>'
    '<path fill="#EA4335" d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.31 0 3.26 2.7 1.29 6.62l3.98 3.09C6.22 6.86 8.87 4.75 12 4.75z"/></svg>'
)
_LINKEDIN_ICON = (
    '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">'
    '<rect width="24" height="24" rx="4" fill="#0A66C2"/>'
    '<path fill="#fff" d="M7.1 9.6h2.4V18H7.1V9.6zm1.2-3.9a1.4 1.4 0 110 2.8 1.4 1.4 0 010-2.8zM11.2 9.6h2.3v1.15h.03c.32-.6 1.1-1.25 2.27-1.25 2.43 0 2.88 1.6 2.88 3.68V18h-2.4v-4.3c0-1.03-.02-2.35-1.43-2.35-1.44 0-1.65 1.12-1.65 2.28V18h-2.4V9.6z"/></svg>'
)


def _site_url() -> str:
    return settings.cards_site_base_url.rstrip("/")


def _page(title: str, body: str) -> HTMLResponse:
    site = html.escape(_site_url(), quote=True)
    return HTMLResponse(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        f"<title>{html.escape(title)}</title>" + _FONTS + _CSS + "</head><body>"
        '<div class="shell">'
        f'<header class="top"><a class="brand" href="{site}"><img src="{_LOGO_SRC}" alt="" '
        'width="26" height="26"><span>Zynd</span></a><span class="crumb">/ <strong>Connect</strong></span></header>'
        f'<main class="stage">{body}</main>'
        f'<footer class="legal"><span>&copy; Zynd AI Inc</span><a href="{site}/privacy">Privacy</a>'
        f'<a href="{site}/terms">Terms</a><a href="{site}/support">Support</a></footer>'
        "</div></body></html>",
        headers={"Cache-Control": "no-store"},
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
    return (json.dumps(value, ensure_ascii=True)
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026"))


_LOGIN_BODY = """<div class="wrap">
  <div class="eyebrow" id="kicker"><i></i>Connect your memory</div>
  <h1 id="title">Sign in to Zynd</h1>
  <p class="sub" id="lede">Verify your account so your AI can use Zynd tools. Connector
   connections need an existing Zynd account &mdash; new accounts are created
   on <a href="%%SITE%%">%%SITE_HOST%%</a>.</p>
  <div id="error" class="err" role="alert" aria-live="assertive" %%ERROR_HIDDEN%%>%%ERROR%%</div>
  <div class="card" id="signin">
    <div class="stack">
      <button type="button" class="btn" data-provider="google">%%GOOGLE_ICON%%Continue with Google</button>
      <button type="button" class="btn" data-provider="linkedin_oidc">%%LINKEDIN_ICON%%Continue with LinkedIn</button>
    </div>
    %%REVIEWER%%
  </div>
  <div class="card" id="consent" hidden>
    <div class="details">
      <dl class="fields">
        <div class="field"><dt>Signed in as</dt><dd id="identity"></dd></div>
        <div class="field"><dt>Requesting app</dt><dd id="client"></dd></div>
        <div class="field"><dt>Resource</dt><dd id="resource" class="mono"></dd></div>
      </dl>
      <p class="note">This client name is supplied by the requesting app, not verified by Zynd.</p>
      <p id="permission-summary">Allowing this connection grants full access to your Zynd account. The app can:</p>
      <ul id="permissions" class="perms"><li>Read, search, and add to your memory and conversations.</li>
        <li>Access your profile card and connected account information.</li>
        <li>Use your connected integrations and their available tools on your behalf.</li></ul>
      <p>Only continue if you trust this app. You can disconnect this connection
        individually in your Zynd connection settings later.</p>
    </div>
    <div class="actions">
      <button id="allow" type="button" class="btn primary">Allow full access</button>
      <button id="cancel" type="button" class="btn">Cancel</button>
    </div>
  </div>
  <p class="foot">Sign-in alone does not grant access to your data.</p>
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
  var pending = REQ;
  if (!pending) {
    showError('Missing connection request. Go back to your AI app and start the connection again.');
    return;
  }
  if (window.supabase === undefined) {
    showError('Sign-in library failed to load. Refresh the page to retry.');
    return;
  }
  var sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  function showError(msg){
    var error = document.getElementById('error');
    error.textContent = msg;
    error.hidden = false;
  }
  var token;
  function post(path, data) {
    return fetch(path, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data), cache: 'no-store'
    }).then(function(r){ return r.json().then(function(d){ return {ok:r.ok, data:d}; }); });
  }
  function preview(sessionToken) {
    token = sessionToken;
    post('/oauth/consent', {req: pending, supabase_token: token})
    .then(function(r){
      if (!r.ok) {
        showError(r.data.detail || 'Unable to verify this connection request.');
        return;
      }
      document.getElementById('identity').textContent = r.data.email;
      document.getElementById('client').textContent = r.data.client_name;
      document.getElementById('resource').textContent = r.data.resource;
      if (r.data.scope !== 'user' && r.data.scope.split(' ').includes('cards:approve')) {
        document.getElementById('permission-summary').textContent = 'This connection can read and write private memory and manage your card:';
        var permissions = document.getElementById('permissions');
        permissions.textContent = '';
        ['Read private memory, profile context, and card activity when relevant.',
         'Save, confirm, and forget private facts with your permission.',
         'Review pending facts and publish or dismiss facts after your explicit confirmation.',
         'Read intro requests and update what you are looking for. No Google, social, messaging, or other integration tools.'].forEach(function(text) {
          var item = document.createElement('li'); item.textContent = text; permissions.appendChild(item);
        });
        document.getElementById('allow').textContent = 'Allow memory and card access';
      }
      document.getElementById('title').textContent = 'Approve connection';
      document.getElementById('lede').hidden = true;
      document.getElementById('kicker').hidden = true;
      document.getElementById('signin').hidden = true;
      document.getElementById('consent').hidden = false;
    }).catch(function(){ showError('Unable to verify this connection request.'); });
  }
  function decide(decision) {
    var buttons = document.querySelectorAll('#consent button');
    buttons.forEach(function(btn){ btn.disabled = true; });
    post('/oauth/complete', {req: pending, supabase_token: token, decision: decision})
    .then(function(r){
      if (!r.ok) { showError(r.data.detail || 'Connection failed. Start again in your AI app.'); return; }
      try { sessionStorage.removeItem(key); } catch(e) {}
      window.location.assign(r.data.redirect_url);
    }).catch(function(){ showError('Connection failed. Start again in your AI app.'); })
    .finally(function(){ buttons.forEach(function(btn){ btn.disabled = false; }); });
  }
  document.getElementById('allow').addEventListener('click', function(){ decide('approve'); });
  document.getElementById('cancel').addEventListener('click', function(){ decide('deny'); });
  document.querySelectorAll('button[data-provider]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var provider = btn.getAttribute('data-provider');
      sb.auth.signInWithOAuth({provider: provider, options: {redirectTo: CALLBACK}})
        .then(function(r){ if (r.error) { showError(r.error.message); } });
    });
  });
  var reviewerForm = document.getElementById('reviewer-form');
  if (reviewerForm) {
    reviewerForm.addEventListener('submit', function(ev){
      ev.preventDefault();
      var submit = reviewerForm.querySelector('button');
      submit.disabled = true;
      sb.auth.signInWithPassword({
        email: document.getElementById('reviewer-email').value.trim(),
        password: document.getElementById('reviewer-password').value
      }).then(function(r){
        document.getElementById('reviewer-password').value = '';
        if (r.error || !r.data || !r.data.session) {
          showError('Reviewer sign-in failed. Check the email and password.');
          return;
        }
        preview(r.data.session.access_token);
      }).catch(function(){ showError('Reviewer sign-in failed.'); })
      .finally(function(){ submit.disabled = false; });
    });
  }
  // Existing sessions may skip sign-in, but never skip explicit consent.
  sb.auth.getSession().then(function(r){
    if (r.data && r.data.session && r.data.session.access_token) preview(r.data.session.access_token);
  }).catch(function(){ showError('Unable to check your sign-in session.'); });
})();
</script>"""

_CALLBACK_BODY = """<div class="wrap">
  <div class="card center">
    <div class="spinner"></div>
    <p class="sub" id="msg" style="margin:0">Completing sign-in&hellip;</p>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<script>
(function(){
  var SUPABASE_URL = %%SUPABASE_URL%%;
  var SUPABASE_ANON_KEY = %%SUPABASE_ANON_KEY%%;
  var key = "zynd_oauth_req";
  var req = %%REQ%%;
  if (!req) { try { req = sessionStorage.getItem(key); } catch(e) {} }
  function fail(msg){
    var card = document.querySelector('.card');
    card.textContent = '';
    var error = document.createElement('div'); error.className = 'err';
    error.textContent = msg; card.appendChild(error);
  }
  if (!req) { fail('Missing connection request. Start the connection again in your AI app.'); return; }
  if (window.supabase === undefined) { fail('Sign-in library failed to load. Refresh to retry.'); return; }
  var sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  sb.auth.getSession().then(function(r){
    if (r.error || !r.data || !r.data.session) { fail('Sign-in failed. No session returned.'); return; }
    if (window.location.hash) {
      window.history.replaceState(null, '', window.location.pathname + window.location.search);
    }
    window.location.replace('/oauth/login?zynd_oauth=' + encodeURIComponent(req));
  }).catch(function(){ fail('Sign-in failed. Please try again.'); });
})();
</script>"""


def _reviewer_form_enabled(req: str) -> bool:
    """True only for a signed plugin request (ChatGPT or Claude) while the reviewer account is configured."""
    if not (req and settings.plugin_review_email_set):
        return False
    from app import oauth  # lazy: oauth imports the plugin tools, this module stays config-only
    try:
        payload = oauth._verify_oauth_request(req)
    except HTTPException:
        return False
    return oauth._is_plugin_request(payload)


def _render_login(req: str, error: str = "") -> HTMLResponse:
    project = _supabase_project()
    if not project:
        return _page("Zynd", """<div class="wrap"><div class="card"><div class="err">"""
                     "OAuth sign-in is not configured on this server.</div></div></div>")
    url, key = project
    body = _LOGIN_BODY
    body = body.replace("%%SITE%%", html.escape(_site_url(), quote=True))
    body = body.replace("%%SITE_HOST%%", html.escape(urlsplit(_site_url()).netloc))
    body = body.replace("%%GOOGLE_ICON%%", _GOOGLE_ICON).replace("%%LINKEDIN_ICON%%", _LINKEDIN_ICON)
    body = body.replace("%%REVIEWER%%", _REVIEWER_BLOCK if _reviewer_form_enabled(req) else "")
    body = body.replace("%%ERROR_HIDDEN%%", "" if error else "hidden")
    body = body.replace("%%ERROR%%", html.escape(error))
    body = body.replace("%%REQ%%", _js_string(req))
    body = body.replace("%%SUPABASE_URL%%", _js_string(url))
    body = body.replace("%%SUPABASE_ANON_KEY%%", _js_string(key))
    body = body.replace("%%CALLBACK%%", _js_string(settings.public_base_url.rstrip("/") + "/oauth/login/callback"))
    return _page("Sign in to Zynd", body)


def _render_callback(req_param: str) -> HTMLResponse:
    project = _supabase_project()
    if not project:
        return _page("Zynd", """<div class="wrap"><div class="card"><div class="err">"""
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
    """Post-provider callback. Supabase finishes sign-in, then returns to consent."""
    req = request.query_params.get("zynd_oauth", "")
    return _render_callback(req)
