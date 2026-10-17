# ChatGPT plugin

ChatGPT-only surface for Zynd. The general memory MCP does not advertise these tools.

| Path | What |
|---|---|
| `package/` | OpenAI plugin zip source (`plugin.json`, `mcp.json`, skills). `python3 package/build.py` validates it. |
| `plugin_mcp.py` | The six tools, registered by `server.py` on `/chatgpt/mcp`. |
| `plugin_consent.py` | Proposals, web save, and publication. Chat never receives the nonce. |
| `plugin_review.py` | `GET/POST /me/plugin/proposals/...` mounted by the memory API. |
| `adapter/` | Local Node stand-in. Not the production URL. |

OAuth for `zynd-chatgpt-plugin` stays in `services/memory/app/oauth.py`. The token audience is `plugin_resource_url` (`https://api.zynd.ai/chatgpt/mcp` in production), not the general MCP resource. Memory rejects that client on `/mcp`. Set `PLUGIN_MCP_PUBLIC_BASE_URL=https://api.zynd.ai/chatgpt` with the other plugin settings.

The memory Docker image copies this directory to `/chatgpt-plugin` and puts it on `PYTHONPATH`. Tests here run with memory's venv:

```bash
cd services/memory && .venv/bin/python -m pytest ../chatgpt-plugin -q
```
