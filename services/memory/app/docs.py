"""Public, shareable install guide served at /install — "how to connect any AI to ZYND".
Plain self-contained HTML (no build step), styled to match the ZYND dashboard."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["docs"])

_CONFIG = '''{
  "mcpServers": {
    "zynd": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://api.zynd.ai/mcp",
               "--header", "Authorization: Bearer YOUR_TOKEN_HERE"]
    }
  }
}'''

_INSTALL_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Install ZYND — connect any AI to your memory</title>
<style>
  :root{--bg:#000;--fg:#f6f6f6;--muted:#9094a8;--accent:#8B5CF6;--accent2:#3B82F6;--line:rgba(255,255,255,.09)}
  *{box-sizing:border-box}
  body{margin:0;background:#000;color:var(--fg);font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;
    letter-spacing:-.02em;line-height:1.6;
    background-image:radial-gradient(900px 520px at 50% -10%,rgba(139,92,246,.16),transparent 60%)}
  .wrap{max-width:760px;margin:0 auto;padding:56px 22px 90px}
  .kicker{display:inline-flex;align-items:center;gap:9px;font-size:12.5px;color:var(--muted);
    border:1px solid var(--line);padding:6px 13px 6px 7px;border-radius:999px}
  .kicker .z{width:21px;height:21px;border-radius:6px;background:linear-gradient(135deg,#8B5CF6,#3B82F6);
    display:inline-flex;align-items:center;justify-content:center;font-weight:700;font-size:12px;color:#fff}
  h1{font-size:42px;line-height:1.05;font-weight:500;letter-spacing:-.04em;margin:22px 0 12px}
  .lede{color:var(--muted);font-size:16px;max-width:620px;margin:0 0 14px}
  .pill{font-size:12.5px;color:#bdb4f0;background:rgba(139,92,246,.12);border:1px solid rgba(139,92,246,.28);
    padding:5px 11px;border-radius:999px;display:inline-block}
  .step{display:flex;gap:18px;padding:26px 0;border-top:1px solid var(--line)}
  .step:first-of-type{border-top:0}
  .num{flex-shrink:0;width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#8B5CF6,#3B82F6);
    display:flex;align-items:center;justify-content:center;font-weight:700;font-size:15px;color:#fff}
  .step h2{font-size:19px;font-weight:600;margin:3px 0 8px;letter-spacing:-.02em}
  .step p{color:#c7cad8;font-size:14.5px;margin:0 0 10px}
  .step .body{flex:1;min-width:0}
  a{color:#a78bfa;text-decoration:none;border-bottom:1px solid rgba(167,139,250,.35)}
  a:hover{border-bottom-color:#a78bfa}
  code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;color:#d8d0ff;
    background:rgba(139,92,246,.12);padding:2px 7px;border-radius:6px}
  .codewrap{position:relative;margin:10px 0 4px}
  pre{margin:0;background:#07070d;border:1px solid rgba(139,92,246,.26);border-radius:12px;
    padding:16px 16px;font-size:12.5px;line-height:1.65;color:#e9e6ff;overflow:auto;
    font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;word-break:break-word}
  .copy{position:absolute;top:10px;right:10px;border:0;border-radius:8px;cursor:pointer;
    font-size:12px;font-weight:600;color:#fff;padding:6px 12px;background:linear-gradient(135deg,#8B5CF6,#3B82F6)}
  .clients{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;margin-top:6px}
  .client{border:1px solid var(--line);border-radius:11px;padding:12px 14px;background:rgba(255,255,255,.03)}
  .client b{font-size:13.5px} .client span{display:block;color:var(--muted);font-size:11.5px;margin-top:4px;line-height:1.45}
  .try{display:grid;gap:8px;margin-top:8px}
  .try div{background:rgba(255,255,255,.03);border:1px solid var(--line);border-radius:9px;padding:10px 13px;
    font-size:13.5px;color:#d3d6e4}
  .try b{color:#a78bfa}
  .note{margin-top:8px;font-size:13px;color:var(--muted)}
  .foot{margin-top:42px;padding-top:18px;border-top:1px solid var(--line);color:#6b7088;font-size:12.5px}
  .cta{display:inline-block;margin-top:6px;background:linear-gradient(135deg,#8B5CF6,#3B82F6);color:#fff;
    padding:11px 18px;border-radius:11px;font-size:14.5px;font-weight:600;border-bottom:0}
  .cta:hover{filter:brightness(1.08);border-bottom:0}
</style></head>
<body><div class="wrap">
  <div class="kicker"><span class="z">Z</span> ZYND &middot; one memory, every AI</div>
  <h1>Connect any AI to your memory</h1>
  <p class="lede">ZYND turns your conversations into a structured memory you own, and carries it across
   Claude, Cursor, ChatGPT, and any MCP client. Setup takes about two minutes.</p>
  <p class="pill">Prerequisite: Node.js 18+ installed (the config uses <code>npx</code>)</p>

  <div style="margin-top:30px">

    <div class="step"><div class="num">1</div><div class="body">
      <h2>Get your connection config</h2>
      <p>Sign in and copy your personal config — your private token is already filled in.</p>
      <a class="cta" href="https://zynd.ai/dashboard/connect">Open zynd.ai → Connect AI</a>
      <p class="note">Sign in with Google → click <b>Connect AI</b> in the sidebar → <b>Copy config</b>.
       It looks like this (your token replaces <code>YOUR_TOKEN_HERE</code>):</p>
      <div class="codewrap">
        <button class="copy" onclick="cp(this)">Copy</button>
        <pre id="cfg">%%CONFIG%%</pre>
      </div>
      <p class="note">Treat this token like a password — it unlocks your memory.</p>
    </div></div>

    <div class="step"><div class="num">2</div><div class="body">
      <h2>Paste it into your AI client</h2>
      <p>Most clients use the same <code>mcpServers</code> block. Open your client's MCP config, paste it in, save.</p>
      <div class="clients">
        <div class="client"><b>Claude Desktop</b><span>Settings → Developer → Edit Config (claude_desktop_config.json)</span></div>
        <div class="client"><b>Claude Code</b><span>Add to .mcp.json, or run <code>claude mcp add</code></span></div>
        <div class="client"><b>Cursor</b><span>Settings → MCP → Add new server</span></div>
        <div class="client"><b>Windsurf</b><span>~/.codeium/windsurf/mcp_config.json</span></div>
        <div class="client"><b>Cline</b><span>MCP Servers → Configure</span></div>
        <div class="client"><b>Continue</b><span>config.json → mcpServers</span></div>
      </div>
    </div></div>

    <div class="step"><div class="num">3</div><div class="body">
      <h2>Restart the app</h2>
      <p>Fully quit and reopen your AI client (in Claude Desktop, quit completely — not just close the window)
       so it loads the new server.</p>
    </div></div>

    <div class="step"><div class="num">4</div><div class="body">
      <h2>Check it works</h2>
      <p>Ask your AI:</p>
      <div class="try"><div><b>You:</b> what ZYND tools do you have?</div></div>
      <p class="note">It should list: remember, get_my_context, find_similar_users, confirm_fact, forget_fact, export.</p>
    </div></div>

    <div class="step"><div class="num">5</div><div class="body">
      <h2>Use it</h2>
      <p>Tell it about yourself, then recall and match:</p>
      <div class="try">
        <div><b>You:</b> Remember that I'm learning Rust and building an AI agent marketplace.</div>
        <div><b>You:</b> What does ZYND know about me?</div>
        <div><b>You:</b> Who on ZYND is working on similar things?</div>
      </div>
      <p class="note">Your memory grows as you share. Recall and matching get better the more you feed it.</p>
    </div></div>

  </div>

  <div class="foot">
    Trouble? Make sure Node.js 18+ is installed and you restarted the app fully.
    Questions: <a href="mailto:hello@zynd.ai">hello@zynd.ai</a> &middot;
    <a href="https://api.zynd.ai/privacy">Privacy</a>
  </div>
</div>
<script>
  function cp(btn){
    var t=document.getElementById('cfg').innerText;
    navigator.clipboard.writeText(t).then(function(){btn.textContent='Copied';setTimeout(function(){btn.textContent='Copy'},1500)});
  }
</script>
</body></html>"""


@router.get("/install", response_class=HTMLResponse, include_in_schema=False)
async def install_guide() -> HTMLResponse:
    return HTMLResponse(_INSTALL_HTML.replace("%%CONFIG%%", _CONFIG))
