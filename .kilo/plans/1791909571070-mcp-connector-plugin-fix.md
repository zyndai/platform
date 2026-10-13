# Fix ZYND MCP Connector/Plugin + Ship Skills (Claude + ChatGPT)

## Why the connector/plugin is failing today

Previous fixes (`.kilo/plans/1791889823378-mcp-oauth-how-to-use.md`) are **in the
`dev` tree but not verified on prod** (memory still runs its old standalone-repo
checkout per AGENTS.md §3/§7). Beyond deploy drift, the OAuth implementation in
`services/memory` still violates hard requirements of the Claude and ChatGPT
connector hosts. Evidence:

| # | Failure | Where | Host impact |
|---|---|---|---|
| R1 | **RFC 8707 `resource` not supported** — `/oauth/authorize` and `/oauth/token` ignore the `resource` param; token response never echoes it | `oauth.py` authorize (~l.448) / token (~l.639) | Claude requires resource indicators; token exchange dies |
| R2 | **Token `iss`/`aud` unbound** — JWTs carry `iss:"zynd"`, `aud:"zynd"` (`config.py` jwt_issuer, `auth.py` `_AUD`), but AS metadata issuer is `https://api.zynd.ai` and the PRM resource is `https://api.zynd.ai/mcp` | `app/auth.py:15,76` | Claude validates iss against AS issuer → 401 → "Connected but no tools" |
| R3 | **Scopes inconsistent** — PRM `scopes_supported: []` (verifier gets `required_scopes=[]`), AS advertises `user/ingest/offline_access`, tokens carry no `scp` claim | `mcp_http.py:296-303`, `oauth.py:388` | ChatGPT connector UI can't request scopes; Claude requests none |
| R4 | **No refresh-token rotation** for public (PKCE/DCR/CIMD) clients | `oauth.py` `/token` | Claude marks the connector unhealthy over time; reconnect loops |
| R5 | **No RFC 9207 `iss` echo**; ChatGPT stable redirect `https://chatgpt.com/connector_platform_oauth_redirect` missing from allowlist | `oauth.py` authorize, `config.py:96-102` | Newer ChatGPT connector platform fails callback validation |
| R6 | **No skills shipped** — the connector/plugin carries zero skills; nothing tells the model when/what to store | repo-wide: no `SKILL.md` anywhere | Plugin loads with no guidance = "empty" experience |
| R7 | **Auth handoff depends on cards** (cross-origin JS POSTing Supabase session to memory `/oauth/complete`) — platform-coupled and fragile | `oauth.py` → `cards_login_url`, `apps/cards-web/src/lib/zynd-oauth.ts` | Any cards-session drift breaks the flow |
| R8 | **Connector auth creates users** — `/oauth/complete` → `resolve_user` upserts a memory user for any verified email | `app/services/users.py` | Violates "no user creation via MCP auth" |

## Locked decisions

1. **Self-hosted auth page on memory** (`https://api.zynd.ai/oauth/login`) —
   memory stays platform-agnostic (no cards/persona dependency for connectors).
   Sign-in via Supabase OAuth providers (Google, LinkedIn OIDC) already trusted
   by `app/supabase_auth.py` (`TRUSTED_PROVIDERS`).
2. **Lookup-only user resolution for connectors**: verified email with no
   existing memory `users` row → error page ("no ZYND account — create your
   card at cards.zynd.ai"), never insert. Legacy confidential clients
   (ChatGPT Action `/aip/`, Hermes deployer) keep the cards front door +
   creation semantics unchanged.
3. **Full-access tokens for v1**: connector OAuth tokens carry `scp:["user"]`
   (all tools visible; matches today's verifier default). Granular
   `memory:write`/`cards:read`/… scopes are out of scope for this pass.
4. **Skills** authored as `SKILL.md` files in `services/memory/skills/`,
   served from the MCP server via FastMCP's `SkillsDirectoryProvider`
   (Claude connector auto-loads), and the same files are importable into
   ChatGPT Skills / Claude Code skill dirs.

## Target flow (after fix)

```
Claude/ChatGPT → POST /mcp (no token) → 401 challenge (PRM /mcp)
  → GET /.well-known/oauth-authorization-server (api app)
  → GET /oauth/authorize?client_id,redirect_uri,code_challenge,resource
      → 302 https://api.zynd.ai/oauth/login?zynd_oauth=<signed jwt>
      → Google/LinkedIn (Supabase PKCE) → /oauth/login/callback (hash → JS)
      → POST /oauth/complete {req, supabase_token}   (same origin)
      → verify identity → find_user (no create) → mint code (bound to resource)
      → 302 client redirect_uri?code&state            (iss echoed for RFC 9207)
  → POST /oauth/token (code + verifier + resource) → {access_token, refresh_token,
      resource echoed, scope, token_type}
  → Bearer token → /mcp tools (verifier accepts iss=AS issuer, aud=resource)
```

## Tasks (ordered)

### Phase 1 — AS fixes in `services/memory` (makes both hosts connect)

1. **`app/auth.py`** — mint connector-bound tokens:
   - Add `issue_connector_access_token(user_id, resource)` → JWT with
     `iss = settings.public_base_url`, `aud = resource`, `typ:"access"`,
     `scp:["user"]`. Keep `issue_access_token` untouched for legacy paths.
   - Add `issue_rotating_refresh_token(user_id)` returning `(token, jti)` and
     `verify_refresh_claims_rotatable(token)`.
2. **`app/oauth.py`**:
   - `authorize`: accept optional `resource` (validate it equals the canonical
     MCP resource `_mcp_origin(MCP_PUBLIC_BASE_URL)+"/mcp"` or its origin);
     seal `resource` + `create_user` flag into `_sign_oauth_request`.
     Connector clients (CIMD `https://` ids and DCR rows) → redirect to
     `{public_base_url}/oauth/login?zynd_oauth=…` with `create_user=false`.
     Known confidential clients (ChatGPT Action, deployer) → unchanged cards
     front door with `create_user=true`.
   - `authorize`: return `iss` (RFC 9207) when the client is ChatGPT; add
     `https://chatgpt.com/connector_platform_oauth_redirect` to the allowlist
     in `config.py`.
   - `complete`: pass `resource` through to `_resolve_user_and_mint_code`
     (stored with the code in Redis); when `create_user=false`, use a new
     lookup-only `find_user` (add to `app/services/users.py`; no INSERT path)
     and return 401 JSON `{"detail": "No ZYND account found for <email> —
     create your card at cards.zynd.ai"}` when absent. Render that error on
     the login page (Phase 2) instead of a silent stop.
   - `token`: accept `resource`; on `authorization_code`, require it to match
     the value stored with the code; echo `resource` in the response; issue
     via `issue_connector_access_token`; return `scope` = requested or
     `"user"`, `token_type:"Bearer"`. On `refresh_token`: single-use
     (Redis `oauth:refresh:{jti}` TTL = refresh TTL, delete on use),
     reissue rotated pair, `invalid_grant` (401) when missing/expired.
   - AS metadata: keep `scopes_supported: ["user", "ingest", "offline_access"]`.
3. **`app/mcp_http.py`**:
   - `RemoteAuthProvider(..., scopes_supported=["user"])` so the PRM advertises
     a non-empty scope list consistent with the AS.
   - `ZyndTokenVerifier` JWT branch: accept `aud` ∈ {`"zynd"`, MCP resource
     URL} and `iss` ∈ {`settings.jwt_issuer`, `settings.public_base_url`}
     (extend `verify_access_meta` in `app/auth.py` with an
     `allowed_audiences`/`allowed_issuers` variant; legacy tokens unchanged).

### Phase 2 — Self-hosted auth page on memory

4. **New `app/oauth_ui.py`** (mount in `main.py`, no auth):
   - `GET /oauth/login` — HTML page (reuse `connect.py` styling) with
     "Continue with Google" / "Continue with LinkedIn" buttons. Embeds the
     **primary** trusted Supabase project's `SUPABASE_URL` + `SUPABASE_ANON_KEY`
     (first entry of `TRUSTED_SUPABASE_PROJECTS`; add a
     `oauth_supabase_project_index` setting if ordering matters) and the
     pending `zynd_oauth` req. Buttons call
     `supabase.auth.signInWithOAuth({provider, options:{redirectTo:
     "{public_base_url}/oauth/login/callback"}})` (supabase-js via CDN, PKCE).
   - `GET /oauth/login/callback` — page extracting the session from the URL
     hash (same pattern as `_CALLBACK_HTML`) and POSTing
     `{req, supabase_token}` to `/oauth/complete` (same origin → no CORS);
     follows `redirect_url`; renders the "no account" error when complete
     returns 401.
5. **`config.py`** — nothing new required; document in `.env.example` that the
   primary trusted Supabase project must have Google + LinkedIn OIDC enabled
   and the redirect URI registered (see Phase 5 deployment).

### Phase 3 — Skills

6. **Author skills** in `services/memory/skills/<name>/SKILL.md` (basic
   store/not-store guidance, per user request):
   - `zynd-memory` — core two-way flow: when to call `remember` /
     `report_user_info` (durable facts: role, skills, projects, goals),
     what NOT to store (secrets, paths, one-off task details, casual chatter),
     milestone batching, "ask before sensitive" rule, `get_my_context` at
     conversation start.
   - `zynd-context` — reading context/card, `export_my_context`, fact
     confirm/forget via `confirm_fact_tool`/`forget_fact_tool`.
   - `zynd-card` — public card, `get_my_card` + owner review tools
     (`get_card_status`, `list_pending_facts`, `approve_fact`).
   Each SKILL.md: YAML frontmatter (name, description) + concise body
   referencing the tool names above.
7. **Serve skills from the MCP server** — in `app/mcp_http.py`:
   `mcp.add_provider(SkillsDirectoryProvider(roots=[Path(__file__).parent.parent / "skills"]))`
   (FastMCP 4.0.10 API, verified in the installed package). Add
   `COPY skills/ /app/skills` to `services/memory/Dockerfile`.
8. (Out of scope) Claude plugin-marketplace submission / ChatGPT Skills
   upload — the SKILL.md files are the artifact; humans install them where
   hosts don't auto-load.

### Phase 4 — Tests (report only NEW failures vs AGENTS.md baseline)

9. `tests/test_oauth.py` / new `tests/test_oauth_connector.py`:
   - authorize with `resource` → sealed; wrong resource → 400.
   - connector client → 302 to `/oauth/login` (not cards); ChatGPT Action
     client → cards (unchanged).
   - `/oauth/complete` with `create_user=false` and unknown email → 401; known
     email → code stored with resource.
   - token response echoes `resource`; JWT `iss`=public_base_url,
     `aud`=resource; refresh rotation: replay of used refresh → 401.
   - RFC 9207: ChatGPT client gets `iss` in the callback redirect; stable
     redirect URI accepted.
10. `tests/test_mcp_http.py` — PRM advertises `scopes_supported:["user"]`;
    verifier accepts connector token (iss/aud) and still accepts legacy
    `aud:"zynd"` tokens; skills provider lists 3 skills.
11. `uv run pytest -q -m "not integration"` in `services/memory`; cards/web
    untouched except nothing (no cards changes in this plan).

### Phase 5 — Deployment & smoke (human steps, AGENTS.md §6)

12. Deploy memory image + env to api-box (memory is not auto-deployed from the
    monorepo). Env sanity: `PUBLIC_BASE_URL=https://api.zynd.ai`,
    `MCP_PUBLIC_BASE_URL=https://api.zynd.ai/mcp`, `JWT_SECRET`,
    `SUPABASE_URL/ANON_KEY` + `TRUSTED_SUPABASE_PROJECTS`.
13. Supabase dashboard (primary project): register
    `https://api.zynd.ai/oauth/login/callback` as an allowed redirect URL;
    enable Google + LinkedIn OIDC providers.
14. Smoke:
    - `GET /.well-known/oauth-protected-resource/mcp` → 200, `resource:
      https://api.zynd.ai/mcp`, non-empty `scopes_supported`,
      `authorization_servers:[https://api.zynd.ai]`.
    - `GET /.well-known/oauth-authorization-server` → 200 (issuer matches).
    - `GET /oauth/login` → 200 HTML with provider buttons.
    - ChatGPT: add custom MCP connector `https://api.zynd.ai/mcp` → OAuth →
      sign in on api.zynd.ai → returns to chatgpt.com/connector/oauth/… →
      tools listed (`get_my_context` etc.).
    - Claude: connect by URL → sign in → new chat → toggle connector → call
      `get_my_context`; skills visible/loaded.
    - Claude Code: `claude mcp add` + loopback redirect still works.
    - Negative: Supabase account with no ZYND user → "no account" error page,
      no user row created.

## Risks / notes

- Legacy 90-day personal tokens keep `iss:"zynd"`, `aud:"zynd"` — verifier
  accepts both, so no existing client breaks.
- `aud = resource` means the connector token is bound to
  `https://api.zynd.ai/mcp`; a future second public base URL needs an
  additional allowed audience (covered by the `allowed_audiences` variant).
- The auth page depends on the primary Supabase project having Google +
  LinkedIn enabled; if the primary is still xmfj during migration, pick the
  project that actually has the providers (config setting).
- Granular scopes, per-tool `securitySchemes` for ChatGPT, Claude directory /
  plugin-marketplace submission, and OIDC domain claiming are out of scope.

## Out of scope

- Moving the AS to cards-api; changing cards-web (no cards changes).
- ChatGPT Action (/aip/) behavior — unchanged.
- User creation via connector auth (explicitly forbidden).