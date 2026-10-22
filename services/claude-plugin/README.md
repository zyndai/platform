# Claude plugin

Claude-only surface for Zynd: the ChatGPT plugin's six consent-gated tools on
`/claude/mcp`. Plan and Anthropic's requirements: `docs/plans/ZYND_CLAUDE_PLUGIN_PLAN.md`.

| Path | What |
|---|---|
| `claude_server.py` | FastMCP on `/claude/mcp`. Reuses `plugin_mcp.register` and `plugin_auth.ExactIssuerAuth` from `../chatgpt-plugin`, adds tool titles and Claude's instructions. |
| `package/` | Plugin bundle for Anthropic's directory. Phase 2, not built yet. |

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
