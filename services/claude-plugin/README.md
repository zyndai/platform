# Claude plugin

Claude-only surface for Zynd: the ChatGPT plugin's six consent-gated tools on
`/claude/mcp`. Plan and Anthropic's requirements: `docs/plans/ZYND_CLAUDE_PLUGIN_PLAN.md`.

| Path | What |
|---|---|
| `claude_server.py` | FastMCP on `/claude/mcp`. Reuses `plugin_mcp.register` and `plugin_auth.ExactIssuerAuth` from `../chatgpt-plugin`, adds tool titles and Claude's instructions. |
| `package/` | The plugin bundle Anthropic's directory reads from GitHub: manifest, `.mcp.json`, three skills, README, LICENSE (MIT). Nothing else may live in it. |
| `bundle.py` | Checks `package/` (least privilege, one endpoint, skills only name real tools) and stages a copy pointed at another environment. |

Claude brings its own OAuth client (a CIMD URL, or a DCR id), so unlike ChatGPT
there is no reserved client id. Memory's `/oauth/authorize` treats a request
for `resource=<CLAUDE_PLUGIN_MCP_PUBLIC_BASE_URL>/mcp` as the plugin: only the
three plugin scopes, the token audience bound to that resource, and the
reviewer account allowed. Only this server accepts that audience; `/mcp`,
`/chatgpt/mcp` and the REST API reject it.

Settings (memory's env, read by both the API and this server):

```
FEATURE_CLAUDE_PLUGIN=true
FEATURE_PLUGIN_CONSENT=true          # shared with ChatGPT; the tools need it
CLAUDE_PLUGIN_MCP_PUBLIC_BASE_URL=https://api.zynd.ai/claude
```

Tests run with memory's venv and pytest config:

```bash
cd services/memory && PYTHONPATH=tests .venv/bin/python -m pytest -c pyproject.toml --rootdir . ../claude-plugin -q
```

## The bundle

```bash
python3 services/claude-plugin/bundle.py                      # our checks
claude plugin validate --profile directory --strict services/claude-plugin/package   # Anthropic's
```

Try it in Claude Code against dev (the copy is written outside the repo; `package/` is never edited):

```bash
python3 services/claude-plugin/bundle.py --stage /tmp/zynd-dev \
  --mcp-url https://dev.api.zynd.ai/claude/mcp --review-origin https://dev.cards.zynd.ai
claude --plugin-dir /tmp/zynd-dev
```

Submission (owner, Pro/Max or a Team/Enterprise Owner with push access to this repo): claude.ai/directory/manage,
Submit new, Plugin bundle, repo `zyndai/platform`, path `services/claude-plugin/package`, branch `main`.
Raise `version` in `package/.claude-plugin/plugin.json` for every release; updates are read from the tracked branch.
