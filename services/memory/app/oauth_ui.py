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
import html
import json

from fastapi import APIRouter, HTTPException, Request
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
  button:disabled{opacity:.5;cursor:wait}
  button.secondary{background:transparent;border:1px solid var(--line)}
  .details{text-align:left;color:var(--muted);font-size:14px;line-height:1.5}
  .details strong{color:var(--fg);font-weight:500}
  .details p{margin:0 0 12px}
  .details ul{padding-left:20px;margin:0 0 12px}
  .err{margin-bottom:10px;padding:12px 14px;border-radius:9px;font-size:13px;line-height:1.5;
    background:rgba(255,80,80,.12);border:1px solid rgba(255,80,80,.3);color:#ffb4b4;text-align:left}
  .spinner{width:28px;height:28px;border:3px solid #333;border-top-color:var(--accent);border-radius:50%;
    animation:spin .7s linear infinite;margin:0 auto 12px}
  @keyframes spin{to{transform:rotate(360deg)}}
  .foot{margin-top:16px;font-size:12px;color:#6b7088;line-height:1.5}
  a{color:#8B5CF6}
  .reviewer{margin-top:18px;text-align:left;border-top:1px solid var(--line);padding-top:14px}
  .reviewer summary{cursor:pointer;color:var(--muted);font-size:13px}
  .reviewer input{display:block;width:100%;margin-top:10px;padding:11px 12px;border-radius:9px;
    border:1px solid var(--line);background:rgba(255,255,255,.04);color:var(--fg);font:inherit;font-size:14px}
</style>"""

# Shown only on a plugin-client request while PLUGIN_REVIEW_EMAILS is set: the
# demo account OpenAI's reviewers use. The server enforces who may use it
# (supabase_identity allow_reviewer); this block is just the entry point.
_REVIEWER_BLOCK = """<details class="reviewer">
      <summary>Reviewer sign-in</summary>
      <form id="reviewer-form" autocomplete="off">
        <input id="reviewer-email" type="email" placeholder="Reviewer email" required autocomplete="username">
        <input id="reviewer-password" type="password" placeholder="Password" required autocomplete="current-password">
        <button type="submit">Sign in</button>
      </form>
    </details>"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title>" + _CSS + "</head><body>" + body + "</body></html>",
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
  <div class="kicker"><span class="z">Z</span> ZYND &middot; connect your memory</div>
  <h1>Sign in to ZYND</h1>
  <p class="sub">Verify your account so your AI can use ZYND tools. Connector
   connections need an existing ZYND account &mdash; new accounts are created
   on cards.zynd.ai.</p>
  <div id="error" class="err" role="alert" aria-live="assertive" %%ERROR_HIDDEN%%>%%ERROR%%</div>
  <div class="card" id="signin">
    <button data-provider="google">Continue with Google</button>
    <button data-provider="linkedin_oidc">Continue with LinkedIn</button>
    %%REVIEWER%%
  </div>
  <div class="card" id="consent" hidden>
    <div class="details">
      <p>Signed in as <strong id="identity"></strong></p>
      <p><strong id="client"></strong> is requesting access to the ZYND MCP resource
        <strong id="resource"></strong>. This client name is supplied by the requesting app,
        not verified by ZYND.</p>
      <p id="permission-summary">Allowing this connection grants full access to your ZYND account. The app can:</p>
      <ul id="permissions"><li>Read, search, and add to your memory and conversations.</li>
        <li>Access your profile card and connected account information.</li>
        <li>Use your connected integrations and their available tools on your behalf.</li></ul>
      <p>Only continue if you trust this app. You can disconnect this connection
        individually in your ZYND connection settings later.</p>
    </div>
    <button id="allow" type="button">Allow full access</button>
    <button id="cancel" type="button" class="secondary">Cancel</button>
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
      } else if (r.data.scope !== 'user') {
        var granted = r.data.scope.split(' ');
        var plugin = {
          'memory:recall': 'Recall private facts from your memory when you ask about them.',
          'memory:propose': 'Draft new private facts for you to review on ZYND. Nothing is saved until you approve it.',
          'cards:review': 'Read your public card and pending facts, and queue facts for your review. It cannot publish anything.'
        };
        var lines = granted.filter(function(s){ return plugin[s]; }).map(function(s){ return plugin[s]; });
        if (lines.length && lines.length === granted.length) {
          document.getElementById('permission-summary').textContent = 'This connection has limited access to your ZYND account. The app can:';
          var list = document.getElementById('permissions');
          list.textContent = '';
          lines.concat(['No access to your integrations, messages, or other ZYND tools.']).forEach(function(text) {
            var item = document.createElement('li'); item.textContent = text; list.appendChild(item);
          });
          document.getElementById('allow').textContent = 'Allow limited access';
        }
      }
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
    """True only for a signed plugin-client request while the reviewer account is configured."""
    if not (req and settings.plugin_review_email_set):
        return False
    from app import oauth  # lazy: oauth imports the plugin tools, this module stays config-only
    try:
        payload = oauth._verify_oauth_request(req)
    except HTTPException:
        return False
    return oauth._is_plugin_client(payload.get("client_id", ""))


def _render_login(req: str, error: str = "") -> HTMLResponse:
    project = _supabase_project()
    if not project:
        return _page("ZYND", """<div class="wrap"><div class="card"><div class="err">"""
                     "OAuth sign-in is not configured on this server.</div></div></div>")
    url, key = project
    body = _LOGIN_BODY
    body = body.replace("%%REVIEWER%%", _REVIEWER_BLOCK if _reviewer_form_enabled(req) else "")
    body = body.replace("%%ERROR_HIDDEN%%", "" if error else "hidden")
    body = body.replace("%%ERROR%%", html.escape(error))
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
    """Post-provider callback. Supabase finishes sign-in, then returns to consent."""
    req = request.query_params.get("zynd_oauth", "")
    return _render_callback(req)
