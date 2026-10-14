# Fix connector OAuth bounce + Claude “Connected but no tools”

## Symptoms (confirmed)

| Client | What happened |
|---|---|
| **ChatGPT CIMD** | Sign-in on cards succeeds; browser **stays on cards** — never returns to ChatGPT |
| **Claude** | Lands on `cards.zynd.ai/auth` → **bounces back** → shows **Connected** but **exposes no tools** |
| **Prod probes** | `GET /mcp` → 405 (alive); `GET /mcp/mcp` → 404; `/.well-known/oauth-protected-resource/mcp` → **404**; AS metadata → 200 |
| **ChatGPT UI** | Resource field = `https://api.zynd.ai/mcp/mcp` (double `/mcp`) |

## Root causes

### A. ChatGPT bounce-back

Callback from CIMD: `https://chatgpt.com/connector/oauth/<id>`.

Allowlist only has `https://chatgpt.com/aip/` (+ chat.openai.com/aip/). Authorize accepts the URI via CIMD; **`POST /oauth/complete` re-runs `_check_redirect_uri` → 400**. Cards clears the pending handoff silently → stuck on cards.

### B. Claude connected, no tools

OAuth handoff works. Tools fail because discovery/audience is wrong:

- FastMCP `RemoteAuthProvider(base_url=MCP_PUBLIC_BASE_URL)` with prod `MCP_PUBLIC_BASE_URL=https://api.zynd.ai/mcp` plus default transport mount at `/mcp` advertises resource **`https://api.zynd.ai/mcp/mcp`**.
- That path **404s**. Protected Resource Metadata at `/.well-known/oauth-protected-resource/mcp` also **404s** on prod.
- Claude can finish OAuth and mark Connected while `list_tools` / resource binding fails → empty tool set.

### C. Not Google-only (already decided)

Cards front door; `/oauth/complete` accepts any trusted Supabase session (`linkedin_oidc`, etc.).

## Decisions (locked)

| Decision | Choice |
|---|---|
| ChatGPT redirect | Add `https://chatgpt.com/connector/` and `https://chat.openai.com/connector/` to allowlist |
| `/oauth/complete` signed-req | Trust `redirect_uri` sealed in `zynd_oauth` JWT (no second allowlist). Keep allowlist at authorize / DCR. Legacy `state_id` path can keep allowlist |
| MCP resource URL | **base_url = origin** (`https://api.zynd.ai`) + FastMCP **path `/mcp`** so advertised resource = `https://api.zynd.ai/mcp`. Do **not** leave public URL as `/mcp/mcp` |
| PRM | Must return **200** at `/.well-known/oauth-protected-resource/mcp` with `"resource": "https://api.zynd.ai/mcp"` |
| Cards UX | Show `/oauth/complete` errors; LinkedIn `next=/auth` when handoff pending |
| Deploy | **memory (api.zynd.ai) + cards-web** — memory may need human docker deploy (AGENTS.md) |

## Implementation tasks

### 1. ChatGPT allowlist — `services/memory/app/config.py`

Extend `oauth_allowed_redirect_prefixes`:

- `https://chatgpt.com/connector/`
- `https://chat.openai.com/connector/`

Keep existing `aip/`, `claude.ai/api/mcp/`, localhost.

### 2. Trust sealed redirect on complete — `services/memory/app/oauth.py`

In `POST /oauth/complete` **signed-req** branch: after `_verify_oauth_request`, use sealed `redirect_uri` **without** `_check_redirect_uri`. Authorize already validated via CIMD/DCR/known client.

### 3. Fix double `/mcp` resource — `services/memory/app/mcp_http.py` (+ config if needed)

- Derive ASGI/public mount so **resource == `https://api.zynd.ai/mcp`**.
- Recommended approach: pass FastMCP `base_url` as **origin only** (`urlsplit(mcp_public_base_url).scheme://netloc` or dedicated setting) and `http_app(..., path="/mcp")` (or equivalent FastMCP API) so Caddy `/mcp*` + app `/mcp` align and PRM path is `/mcp`.
- If `MCP_PUBLIC_BASE_URL` stays `https://api.zynd.ai/mcp` for docs/clients, **do not** append another `/mcp` when building `RemoteAuthProvider.base_url`.
- Add/adjust unit test: PRM JSON `resource` equals canonical MCP URL (no `/mcp/mcp`); `GET /.well-known/oauth-protected-resource/mcp` → 200.

Inspect FastMCP version’s `http_app` / `RemoteAuthProvider` signatures in the installed package before coding — match existing call sites.

### 4. Cards handoff reliability — `apps/cards-web`

- `zynd-oauth.ts`: return/show error detail on non-OK complete (do not silent-clear only).
- Auth page: display that error; when starting LinkedIn during handoff, `next=/auth`.
- `ZyndOAuthHandoff`: after return with session + pending KEY, call complete (no second LinkedIn loop).

### 5. Tests

- Allowlist accepts ChatGPT `connector/` URI; evil host still rejected at **authorize**.
- Complete with sealed ChatGPT connector redirect succeeds without second allowlist fail.
- PRM resource !== `…/mcp/mcp`; === `…/mcp`.
- Existing Claude allowlist / oauth tests still pass (report only **new** failures vs AGENTS.md baseline).

### 6. Ship

1. Commit on current branch; merge/push to `dev` as appropriate.
2. Deploy **memory** image + env to api-box (confirm `CORS_ORIGINS` includes `https://cards.zynd.ai`; `MCP_PUBLIC_BASE_URL` / code change consistent).
3. Deploy **cards-web** (pm2 rebuild/restart on single-box if that is how cards ships).
4. Smoke:

| Check | Expect |
|---|---|
| `/.well-known/oauth-protected-resource/mcp` | 200, `resource` = `https://api.zynd.ai/mcp` |
| `GET /mcp` | 405 (not 404) |
| `GET /mcp/mcp` | 404 (unused) |
| ChatGPT Connect → sign in | Leaves cards → `chatgpt.com/connector/oauth/…?code=` |
| Claude reconnect → new chat | Tools visible / callable (`get_my_context`, etc.) |
| Claude Code | Loopback still works |

## Out of scope

- OIDC for ChatGPT domain claiming  
- Anthropic-held client secrets / EMA  
- Stage 2 persona SSO  
- Changing Claude connector UI toggles (already OAuth + Claude CIMD)

## Key files

| Path | Change |
|---|---|
| `services/memory/app/config.py` | `connector/` allowlist |
| `services/memory/app/oauth.py` | Trust sealed redirect_uri on complete |
| `services/memory/app/mcp_http.py` | Fix base_url / path so resource is `/mcp` not `/mcp/mcp`; PRM 200 |
| `services/memory/tests/test_mcp_http.py` (+ oauth tests) | Resource + allowlist coverage |
| `apps/cards-web/src/lib/zynd-oauth.ts` | Error surfacing |
| `apps/cards-web/src/app/(site)/auth/page.tsx` | Show errors; LinkedIn `next=/auth` |
| `apps/cards-web/src/components/ZyndOAuthHandoff.tsx` | Post-login complete |
| `infra/api-box` / prod `.env` | Human deploy; CORS if overridden |

## User retest after deploy

1. ChatGPT: disconnect connector → reconnect → confirm bounce off cards.  
2. Claude: disconnect Zynd → reconnect → **new chat** → toggle connector on → ask for `get_my_context`.  
3. If still no tools: check Network for `list_tools` / MCP calls against `https://api.zynd.ai/mcp` (not `/mcp/mcp`).
