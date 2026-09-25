"""Public, shareable install guide served at /install — "how to connect any AI to ZYND".
Minimal black-and-white HTML (no build step), real client logos via icon.horse."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["docs"])

_CONFIG = '''{
  "mcpServers": {
    "zynd": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://api.zynd.ai/mcp",
               "--header", "Authorization: Bearer YOUR_TOKEN"]
    }
  }
}'''

# (display name, install location, icon.horse domain, uses the standard mcpServers block)
_CLIENTS = [
    ("Claude Desktop", "Settings &rarr; Developer &rarr; Edit Config", "claude.ai", True),
    ("Claude Code", "Add to .mcp.json, or run <code>claude mcp add</code>", "claude.ai", True),
    ("Cursor", "Settings &rarr; MCP &rarr; Add new server", "cursor.com", True),
    ("Windsurf", "~/.codeium/windsurf/mcp_config.json", "windsurf.com", True),
    ("Cline", "MCP Servers &rarr; Configure", "cline.bot", True),
    ("Continue", "config.json &rarr; mcpServers", "continue.dev", True),
    ("VS Code", ".vscode/mcp.json &middot; uses a <code>servers</code> key", "code.visualstudio.com", False),
    ("Zed", "settings.json &rarr; context_servers", "zed.dev", False),
    ("ChatGPT", "Use the ZYND GPT (no config needed)", "chatgpt.com", False),
]


def _client_rows() -> str:
    rows = []
    for name, loc, domain, standard in _CLIENTS:
        tag = "" if standard else '<span class="own">own format</span>'
        rows.append(
            f'<div class="client">'
            f'<img src="https://icon.horse/icon/{domain}" alt="" loading="lazy" '
            f'onerror="this.style.visibility=\'hidden\'">'
            f'<div class="cmeta"><div class="cname">{name}{tag}</div>'
            f'<div class="cloc">{loc}</div></div></div>'
        )
    return "\n".join(rows)


_INSTALL_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Install ZYND — connect any AI to your memory</title>
<style>
  :root{--fg:#0a0a0a;--muted:#6b7280;--line:#e7e7e9;--soft:#f6f6f7;--code:#f4f4f5}
  *{box-sizing:border-box}
  html{-webkit-text-size-adjust:100%}
  body{margin:0;background:#fff;color:var(--fg);line-height:1.6;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif;
    font-size:16px;-webkit-font-smoothing:antialiased}
  .wrap{max-width:680px;margin:0 auto;padding:64px 24px 96px}
  .brand{display:flex;align-items:center;gap:9px;font-size:14px;font-weight:600;letter-spacing:.02em}
  .brand .mark{width:22px;height:22px;border-radius:6px;background:#0a0a0a;color:#fff;
    display:inline-flex;align-items:center;justify-content:center;font-size:12px;font-weight:700}
  h1{font-size:34px;line-height:1.12;font-weight:650;letter-spacing:-.02em;margin:30px 0 10px}
  .lede{color:var(--muted);font-size:17px;margin:0 0 18px;max-width:560px}
  .meta{display:inline-flex;align-items:center;gap:8px;font-size:13px;color:var(--muted);
    border:1px solid var(--line);border-radius:8px;padding:6px 11px}
  .meta b{color:var(--fg);font-weight:600}
  section{border-top:1px solid var(--line);padding:30px 0 8px;margin-top:6px}
  .snum{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:999px;
    background:#0a0a0a;color:#fff;font-size:13px;font-weight:600;margin-right:11px;vertical-align:2px}
  h2{font-size:19px;font-weight:600;letter-spacing:-.01em;margin:0 0 6px;display:inline}
  .sub{color:var(--muted);font-size:14.5px;margin:10px 0 14px}
  code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.86em;background:var(--code);
    padding:2px 6px;border-radius:5px;color:#111}
  a{color:#0a0a0a;text-decoration:underline;text-underline-offset:2px;text-decoration-color:#cfcfd4}
  a:hover{text-decoration-color:#0a0a0a}
  .btn{display:inline-block;background:#0a0a0a;color:#fff;text-decoration:none;font-size:14.5px;font-weight:550;
    padding:11px 18px;border-radius:9px;margin:4px 0 6px}
  .btn:hover{background:#222}
  .codewrap{position:relative;margin:14px 0 6px}
  pre{margin:0;background:var(--code);border:1px solid var(--line);border-radius:10px;padding:16px;
    font-size:12.5px;line-height:1.6;color:#18181b;overflow:auto;
    font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;word-break:break-word}
  .copy{position:absolute;top:10px;right:10px;border:1px solid var(--line);background:#fff;border-radius:7px;
    cursor:pointer;font-size:12px;font-weight:600;color:#0a0a0a;padding:5px 11px}
  .copy:hover{background:var(--soft)}
  .clients{margin-top:6px;border:1px solid var(--line);border-radius:12px;overflow:hidden}
  .client{display:flex;align-items:center;gap:13px;padding:13px 16px;border-top:1px solid var(--line)}
  .client:first-child{border-top:0}
  .client img{width:24px;height:24px;border-radius:5px;flex-shrink:0;object-fit:contain}
  .cmeta{min-width:0}
  .cname{font-size:14.5px;font-weight:550;display:flex;align-items:center;gap:8px}
  .cloc{font-size:12.5px;color:var(--muted);margin-top:1px}
  .own{font-size:10.5px;font-weight:600;color:var(--muted);border:1px solid var(--line);
    border-radius:999px;padding:1px 7px}
  details{border-top:1px solid var(--line)}
  details:first-of-type{border-top:0}
  .examples{border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-top:8px}
  summary{list-style:none;cursor:pointer;padding:14px 16px;font-size:14.5px;font-weight:550;
    display:flex;align-items:center;gap:11px}
  summary::-webkit-details-marker{display:none}
  summary::before{content:"+";color:#9ca3af;font-size:17px;line-height:1;width:14px;text-align:center}
  details[open] summary::before{content:"\\2212"}
  .exbody{padding:0 16px 16px 41px}
  .exbody p{font-size:14px;color:var(--muted);margin:0 0 9px}
  .msg{background:var(--soft);border:1px solid var(--line);border-radius:9px;padding:11px 13px;
    font-size:14px;margin:0 0 8px}
  .msg b{color:#0a0a0a;font-weight:650}
  ul.clean{margin:8px 0 0;padding:0;list-style:none}
  ul.clean li{position:relative;padding-left:20px;font-size:14.5px;color:#27272a;margin-bottom:10px;line-height:1.55}
  ul.clean li::before{content:"";position:absolute;left:2px;top:9px;width:6px;height:6px;border-radius:999px;background:#0a0a0a}
  ul.clean b{font-weight:600}
  .foot{margin-top:44px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}
</style></head>
<body><div class="wrap">

  <div class="brand"><span class="mark">Z</span> ZYND</div>
  <h1>Connect any AI to your memory</h1>
  <p class="lede">ZYND turns your conversations into a structured memory you own, and carries it across
   Claude, Cursor, ChatGPT, and any MCP client. Setup takes about two minutes.</p>
  <span class="meta">Prerequisite: <b>Node.js 18+</b> &nbsp;&middot;&nbsp; the config uses <code>npx</code></span>

  <section>
    <h2><span class="snum">1</span>Get your config</h2>
    <p class="sub">Sign in and copy your personal config — your private token is already filled in.</p>
    <a class="btn" href="https://zynd.ai/dashboard/connect">Open zynd.ai &rarr; Connect AI</a>
    <p class="sub">It looks like this (your token replaces <code>YOUR_TOKEN</code>):</p>
    <div class="codewrap"><button class="copy" onclick="cp(this)">Copy</button><pre id="cfg">%%CONFIG%%</pre></div>
    <p class="sub">Treat this token like a password — it unlocks your memory.</p>
  </section>

  <section>
    <h2><span class="snum">2</span>Add it to your AI client</h2>
    <p class="sub">Most clients use the same block — open their MCP config, paste, save. A few use their own format.</p>
    <div class="clients">
%%CLIENTS%%
    </div>
  </section>

  <section>
    <h2><span class="snum">3</span>Restart the app</h2>
    <p class="sub">Fully quit and reopen your client (in Claude Desktop, quit completely — not just close the
     window) so it loads the new server.</p>
  </section>

  <section>
    <h2><span class="snum">4</span>Check it works</h2>
    <p class="sub">Ask your AI: <b>&ldquo;what ZYND tools do you have?&rdquo;</b> &mdash; it should list
     remember, get_my_context, find_similar_users, confirm_fact, forget_fact, and export.</p>
  </section>

  <section>
    <h2><span class="snum">5</span>Use it</h2>
    <p class="sub">Tell it about yourself, then recall and match. Expand an example:</p>
    <div class="examples">
      <details open><summary>Build your memory</summary>
        <div class="exbody">
          <p>Share a durable fact and your AI saves it to ZYND:</p>
          <div class="msg"><b>You:</b> Remember that I&rsquo;m learning Rust and building an AI agent marketplace.</div>
          <p>It calls <code>remember</code>. Facts are extracted in the background within a few seconds.</p>
        </div>
      </details>
      <details><summary>Recall what it knows</summary>
        <div class="exbody">
          <div class="msg"><b>You:</b> What does ZYND know about me?</div>
          <p>Returns your active facts (e.g. <i>learning &rarr; Rust</i>, <i>building &rarr; AI agent marketplace</i>)
           via <code>get_my_context</code>.</p>
        </div>
      </details>
      <details><summary>Find similar people</summary>
        <div class="exbody">
          <div class="msg"><b>You:</b> Who on ZYND is working on similar things?</div>
          <p>Returns people whose context overlaps yours, by similarity, via <code>find_similar_users</code>.</p>
        </div>
      </details>
    </div>
  </section>

  <section>
    <h2>How it works with your team</h2>
    <p class="sub">ZYND gets more useful as more people connect — that&rsquo;s what powers matching.</p>
    <ul class="clean">
      <li><b>One account per person.</b> Each teammate signs in with their own Google login and pastes
       their own config. Never share a token.</li>
      <li><b>Everyone feeds their own memory.</b> As each person talks to their AI, their context graph grows.</li>
      <li><b>Matching needs substance.</b> A profile surfaces to others once it has a handful of facts and a
       genuine overlap — then &ldquo;who&rsquo;s similar to me?&rdquo; returns real teammates.</li>
      <li><b>Private by default.</b> Matches show an opaque handle and a similarity score — never anyone&rsquo;s
       email or raw profile.</li>
      <li><b>One memory across tools.</b> Use the same account in Claude and ChatGPT and both read and write
       the same graph.</li>
    </ul>
  </section>

  <div class="foot">
    Trouble? Confirm Node.js 18+ is installed and that you restarted the app fully.
    &nbsp;&middot;&nbsp; <a href="https://api.zynd.ai/privacy">Privacy</a>
    &nbsp;&middot;&nbsp; <a href="mailto:hello@zynd.ai">hello@zynd.ai</a>
  </div>

</div>
<script>
  function cp(b){navigator.clipboard.writeText(document.getElementById('cfg').innerText)
    .then(function(){b.textContent='Copied';setTimeout(function(){b.textContent='Copy'},1500)})}
</script>
</body></html>"""


@router.get("/install", response_class=HTMLResponse, include_in_schema=False)
async def install_guide() -> HTMLResponse:
    html = _INSTALL_HTML.replace("%%CONFIG%%", _CONFIG).replace("%%CLIENTS%%", _client_rows())
    return HTMLResponse(html)
