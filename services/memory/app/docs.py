"""Public, credential-free MCP OAuth setup guide at /install and /connect."""

import html

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.config import settings

router = APIRouter(tags=["docs"])

_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect Zynd to your AI</title>
<style>
  :root{color-scheme:light;--ink:#15151c;--muted:#62647a;--line:#dedee6;--accent:#7046d1}
  *{box-sizing:border-box}body{margin:0;background:#f8f7fb;color:var(--ink);
    font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
  main{max-width:760px;margin:auto;padding:56px 22px 90px}
  .mark{font-weight:750;letter-spacing:.12em;color:var(--accent)}
  h1{font-size:32px;line-height:1.12;margin:24px 0 12px}
  h2{font-size:1.3rem;margin:0 0 8px}p{margin:8px 0 15px}
  .lead{font-size:1.1rem;color:var(--muted);max-width:640px}
  section{border-top:1px solid var(--line);margin:20px 0;padding:22px 0 8px;overflow:hidden}
  code,pre{font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}
  code{background:#f3f1f9;padding:2px 4px;border-radius:4px}
  pre{background:#f3f1f9;border-radius:9px;padding:14px;overflow-x:auto;white-space:pre-wrap;
    overflow-wrap:anywhere;margin:12px 0}
  .url{font-size:1rem}a{color:#6237c2}small,.note{color:var(--muted)}
  @media(max-width:520px){main{padding:32px 16px 60px}section{padding:18px}}
</style></head><body><main>
<div class="mark">ZYND / MCP</div><h1>Connect your AI to Zynd</h1>
<p class="lead">Add the MCP server URL to a supported client. Your client opens Zynd sign-in
and asks you to approve access; no token or password goes in your configuration.</p>
<section><h2>Your server URL</h2><pre class="url">%%URL%%</pre>
<p>Use this URL for this environment, not a URL copied from another deployment.
You must already have a Zynd account. If you do not, <a href="%%ACCOUNT_URL%%">create one
through Zynd onboarding</a>, then retry client authorization. This setup page does not sign
you up or issue a credential.</p></section>
<section><h2>Claude Code</h2>
<pre>claude mcp add --transport http zynd %%URL%%</pre>
<p>Open Claude Code and use <code>/mcp</code> to authenticate the Zynd server.</p>
<small><a href="https://code.claude.com/docs/en/mcp">Claude Code MCP docs</a></small></section>
<section><h2>Codex CLI</h2><pre>codex mcp add zynd --url %%URL%%
codex mcp login zynd</pre>
<small><a href="https://developers.openai.com/codex/mcp">Codex MCP docs</a></small></section>
<section><h2>Kilo CLI</h2><p>Add to your <code>kilo.json</code>, then run
<code>kilo mcp auth zynd</code>:</p>
<pre>{"mcp":{"zynd":{"type":"remote","url":"%%URL%%"}}}</pre>
<small><a href="https://kilo.ai/docs/automate/mcp/using-in-cli">Kilo MCP docs</a></small></section>
<section><h2>OpenCode v2</h2>
<pre>opencode mcp add zynd --url %%URL%%
opencode mcp auth zynd</pre>
<p>OpenCode v1 uses a different configuration format; consult its version-specific docs.</p>
<small><a href="https://opencode.ai/v2/docs/mcp-servers/">OpenCode v2 MCP docs</a></small></section>
<section><h2>Authorization and access</h2>
<p>Sign in with your existing Zynd account in the browser and explicitly approve the
requesting client. Consent grants full <code>user</code> access to your Zynd memory, card,
and available integrations, including reading and changing data. Only approve clients you trust.</p>
<p>Access tokens last one hour. The client handles rotating refresh tokens, each valid for
30 days from issuance, while the connection stays active. Disconnect individual clients in
your Zynd connection settings. If a refresh session expires or cannot be used, sign in again.</p>
<p class="note">These are client configuration examples from vendor documentation, not
end-to-end verification for your installed version. Other clients (including Claude Desktop,
ChatGPT, Cursor, Windsurf, Cline, Antigravity, and OpenClaw) need version-specific OAuth
verification before setup can be recommended. No untested bridge or manual bearer fallback
is provided here.</p></section>
</main></body></html>"""


@router.get("/install", response_class=HTMLResponse, include_in_schema=False)
async def install_guide() -> HTMLResponse:
    url = settings.mcp_resource_url
    body = _HTML.replace("%%URL%%", html.escape(url, quote=True)).replace(
        "%%ACCOUNT_URL%%", html.escape(settings.cards_site_base_url.rstrip("/"), quote=True)
    )
    return HTMLResponse(body, headers={"Cache-Control": "no-store"})
