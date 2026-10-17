# Zynd ChatGPT plugin adapter

Local MCP adapter for the packaged plugin in `../package`. It exposes the same six tools and forwards each call to the memory MCP with the caller's bearer token. The tool implementations live in `../plugin_mcp.py` and run in `../server.py` at `/chatgpt/mcp`. They share memory's database and OAuth, but not its `/mcp` tool list.

This process is not the OAuth server and it is not the production plugin URL. ChatGPT should connect to `https://api.zynd.ai/chatgpt/mcp` with public client `zynd-chatgpt-plugin`. Use this adapter only to exercise that contract locally.

## Contract

- Tools: `recall_memories`, `propose_memory`, `get_proposal_status`, `list_pending_facts`, `propose_card_fact`, `get_public_card`.
- Scopes must be exactly `memory:recall memory:propose cards:review`.
- The bearer must be a plugin JWT with `cid=zynd-chatgpt-plugin`, `iss=ZYND_AUTH_ISSUER`, and `aud` equal to `ZYND_MCP_URL`.
- `propose_memory` takes `text`. `propose_card_fact` takes an existing `fact_id` and `version`.
- There is no save or publish tool. A proposal returns `review_url`; the signed-in owner saves or publishes on that page. Do not pass a nonce or receipt.

The adapter does not verify the JWT signature. The memory service does, and it also enforces `feature_plugin_consent`, PKCE, and the reserved client. An unconfigured memory server rejects the plugin client.

## Run

```bash
cp .env.example .env
npm install
npm run typecheck
npm test
npm run dev
```

`GET /healthz` is public. `POST /mcp` without a valid plugin bearer returns 401 and a protected-resource challenge for the upstream issuer. Missing `ZYND_MCP_URL` defaults to `https://api.zynd.ai/mcp`; the process does not exit on import.
