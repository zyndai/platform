# URL-Only MCP OAuth For Coding Agents

## Goal And Confirmed Decisions

Replace new manual-bearer MCP onboarding with a credential-free server URL/config:
agent starts authorization -> Zynd website sign-in and explicit consent -> agent
callback -> agent stores tokens and refreshes automatically.

- Cover Claude Desktop/Code, ChatGPT connectors, Codex, Kilo, OpenCode, Cursor,
  Windsurf, Cline, Antigravity, and OpenClaw. Distinguish editor and CLI versions.
- Prefer native OAuth; use a tested `mcp-remote` OAuth bridge only when necessary.
  No new manual-token setup in onboarding. Do not claim unsupported clients work.
- Preserve existing OAuth full `user` access, clearly disclosed on consent.
  Granular OAuth permissions are a separate task.
- Keep access TTL 3,600 seconds and rotating refresh TTL 30 days from issuance of
  each replacement. No global lifetime increase or non-expiring credentials.
- Require an existing Zynd account. Unknown users go to onboarding then retry;
  MCP sign-in does not create accounts.
- List and individually disconnect OAuth connections, without signing out other
  clients. Existing pasted bearer tokens remain valid and revocable.
- Older unbound MCP OAuth refresh sessions may require one browser reauthorization
  on their next refresh. Existing access tokens expire normally. Preserve separate
  confidential ChatGPT Action/Hermes behavior unless an explicit regression needs fixing.
- Planning only. Implementation touches auth and requires human approval. No
  production operations, secret rotation, schema application, or deploy authorized
  by this plan. Prior task's dev deployment approval does not carry forward.

## Current State

`services/memory/app/oauth.py` already supports discovery, DCR, client metadata
documents (CIMD), hosted sign-in, code exchange, and rotating refresh. MCP accepts
resource-bound JWTs. Claude Code already has URL-only primary instructions.

However, Persona connect unconditionally calls `/token/exchange`; most snippets
and Cards setup still embed bearer headers. OAuth consent currently auto-completes
an existing browser login. Public grants lack complete client/redirect binding,
and Redis GET then DELETE is not atomic single-use redemption.

## Ordered Implementation

### 1. Verify Client Contracts Before Advertising Them

Record tested client/version, config shape, auth command, callback host/path,
registration method, token persistence, refresh behavior, and native/bridge choice
in maintained setup docs. Use current official docs/source, then real-client tests.

- Claude Code: HTTP URL, `claude mcp add --transport http zynd <url>`, then `/mcp`.
- Codex: `codex mcp add zynd --url <url>`, then `codex mcp login zynd`.
- Kilo: native remote entry and `kilo mcp auth zynd` (verify installed syntax).
- OpenCode: native remote entry and version-appropriate MCP auth command.
- Cursor: URL remote entry; CLI `agent mcp login zynd` where supported.
- Windsurf/Cline: verify native remote OAuth including refresh, not just transport.
- Antigravity/OpenClaw: validate actual native config and callback behavior rather
  than treating their current generic `mcpServers` snippets as authoritative.
- Claude Desktop/ChatGPT: retain hosted callback support and issuer validation.
- For a native gap, test a maintained pinned `mcp-remote` version using only the
  MCP URL, no `--header` secret. Bridge manages OAuth credentials, refresh, and
  callback. Explain Node/runtime requirement and protected local credential store.
- If neither route works, mark that version unsupported; do not silently issue a
  longer token. Headless/SSH machines need client-supported callback forwarding
  or documented browser URL handling; do not invent a device grant in this change.

Starting evidence (2026-10-15; verify installed versions during execution):
`https://code.claude.com/docs/en/mcp`,
`https://developers.openai.com/codex/mcp`,
`https://kilo.ai/docs/automate/mcp/using-in-cli`,
`https://opencode.ai/docs/mcp-servers/`,
`https://cursor.com/docs/cli/mcp`,
`https://docs.windsurf.com/windsurf/cascade/mcp`,
`https://docs.cline.bot/mcp/configuring-mcp-servers`,
`https://docs.openclaw.ai/cli/mcp/transports`,
`https://github.com/geelen/mcp-remote`.

### 2. Harden Public MCP OAuth Grants

Files: memory `app/oauth.py`, `app/oauth_ui.py`, `app/auth.py`,
`app/services/users.py`, relevant configuration and OAuth tests.

1. Classify public MCP vs existing confidential grants explicitly. Do not choose
   legacy token behavior merely because a public client omitted `resource`.
   Default an omitted public MCP resource to this environment's canonical `/mcp`;
   reject foreign resources and preserve resource binding across refresh.
2. Require valid S256 PKCE for public clients at authorize and exchange. Seal and
   persist client ID/type, exact callback, scope, resource, PKCE, and request nonce.
   Bind code redemption to the same client and exact original redirect, including
   its selected port. Validate verifier format and hash; no public client secret.
3. Registered callbacks match exactly, except the registered loopback host/path
   may use an ephemeral port. Host/path/query must remain registered; reject
   fragments/userinfo, sibling/subpaths, and fallback to a global allowlist after
   a DCR/CIMD mismatch. Do not equate distinct loopback hosts unless registered.
   Keep known confidential client rules isolated; reject rather than redirect
   errors to an unvalidated callback.
4. Keep DCR/CIMD compatible with vendor clients. Harden metadata fetching against
   DNS-resolved private destinations/rebinding, redirects, oversized streamed
   responses, and timeouts. Use a vetted address-pinned fetch/transport approach;
   a preflight DNS check followed by an independent resolution is insufficient.
   Enforce HTTPS, document self-consistency, bounded cache, and safe client labels.
5. Replace auto-approval with explicit Allow/Cancel, showing signed-in identity,
   requesting client (escaped, not a verified-brand claim), Zynd MCP resource, full
   memory/card/integration capabilities, and disconnect guidance. The sign-in
   page remains the existing hosted Zynd `/oauth/login`; no new auth host/provider.
   Existing browser sessions skip sign-in, never consent. Only explicit approval
   creates a code; denial returns `access_denied` with original state to a validated
   callback. Preserve state through Google/Supabase sign-in without leaking tokens.
6. Make authorization request completion, code redemption, and refresh redemption
   atomic single-use (Redis GETDEL or tested Lua compatible with deployed Redis).
   Store all code/PKCE bindings together; validate before atomic compare/consume
   when necessary. Denial/approval nonce replay cannot mint multiple codes.
7. Fix lookup-only identity conflicts: matching email must not select a memory
   account already linked to a different Supabase subject. Never overwrite links
   or auto-create an account here. Missing/conflicting account gives safe onboarding
   guidance, not an authorization code.

### 3. Track Revocable OAuth Connections Without A Schema Change

Reuse existing memory `mcp_clients` rows: UUID `jti` is already the stable revoke
handle and `scopes` accepts `user`. Avoid new schema/migrations for this task.

- At successful new public-MCP code exchange create one connection record with
  sanitized client label and `user` scope. Persist client ID/resource/subject/scope/
  connection handle in the Redis refresh grant; do not store raw tokens in DB.
- Access JWT gets this UUID connection handle in `jti`; refresh JWT gets its own
  unique rotation nonce. Every replacement access/refresh retains the connection
  handle in its grant. Do not mint a 90-day assistant token by reusing the current
  `issue_client_token` unchanged. Use 1-hour resource-bound OAuth issuance, without
  bumping user token_version or invalidating other connections.
- Refresh requires matching OAuth client ID, active owned connection, correct
  resource and original scopes. `scope` cannot expand; omitted resource is restored
  from the grant. Return both replacement tokens, `expires_in`, and actual scope.
  Concurrent redemption yields exactly one success, losers `invalid_grant`.
  Bind refresh nonce to its connection; reject replay without revoking unrelated
  connections. Expired, revoked, or missing grants require reauthorization.
- Existing `ZyndTokenVerifier` already checks jti revocation. Verify subject/owner
  binding and consistently enforce connection revocation on all HTTP endpoints
  that accept these new tokens, not only `/mcp`. Fix management `_user_from_bearer`
  validation so an expired/revoked credential cannot manage connections via the
  decode-only path. Preserve valid Supabase-session management.
- Reuse client list/disconnect routes and extend response only additively if
  needed. OAuth connections carry `user`; legacy manual clients retain their
  recorded granular scopes. UI must render full access meaningfully. Individual
  disconnect blocks both access and refresh; global disconnect retains existing
  watermark/version behavior. No pre-existing token table rows are deleted.
- New refresh storage uses a versioned grant payload/key prefix. Old public MCP
  refresh records without binding return `invalid_grant` and require one-time
  sign-in; never silently adopt them into another client. Do not revoke old access
  or bearer tokens. Leave unrelated confidential grant compatibility explicit.

### 4. Replace Every Active Manual Setup Surface

- `apps/persona-web/src/app/dashboard/connect/page.tsx`: remove mint-on-load,
  manual-token alternatives and headers from all configs/prompts. Add missing
  Kilo/ChatGPT entries where appropriate. Render environment-correct URL and
  tested native/bridge setup independently of any token exchange.
- `apps/cards-web/src/components/mcp/McpConnectPanel.tsx`,
  `src/lib/mcp-connector.ts`, and owner `edit-client.tsx`: replace mint-and-copy
  with client-specific URL/OAuth setup; remove misleading limited-scope selection
  for new full-access OAuth. Keep connection inventory/disconnect, including legacy
  clients. No credentials in clipboard configs/deeplinks or local setup state.
- `services/memory/app/connect.py` and `app/docs.py`: replace public Get-token/
  signup config presentation with URL/OAuth instructions; old browser form must
  no longer mint new setup tokens. Preserve legacy token verification, not the
  obsolete UI. Update corresponding route tests deliberately.
- Do not remove or break `/token/exchange`: Cards claim/import/memory flows still
  consume it internally (`cards-web/src/lib/memory.ts` and create page). Keep its
  compatibility behavior out of onboarding; avoid expanding into a separate
  internal-auth redesign. Legacy `connect_links` must not feed new OAuth setup.
- Update maintained install/connect guidance, `.env` TTL comments if needed, and
  any active generated examples; preserve historical plans and independent public
  Cards MCP/`zynd-cards` connector. No edits in separate dashboard/bridge repos.
- Read both Next.js app guides before edits; use existing visual patterns. Avoid
  new shared packages solely for a small client setup matrix.

## Validation And Acceptance

Capture actual pre/post memory, Persona API, Cards API (if touched), and both web
lint/typecheck baselines. Build both changed web apps; exercise browser UI desktop
and mobile. Test fixtures use local isolated Postgres/Redis, never shared prod data.

- End-to-end protocol: unauthenticated real HTTP `/mcp` -> 401 with usable resource
  metadata -> AS discovery -> DCR/CIMD -> sign-in -> explicit consent -> loopback/
  registered callback -> PKCE exchange -> full-scope tools call -> forced expiry
  -> refresh -> successful call without a new browser window. Client restart must
  reuse securely stored credentials. Use shortened TTL only in isolated tests.
- OAuth regressions: wrong client/redirect/resource/verifier, absent PKCE, callback
  subpath/query substitution, CSRF/nonce replay, SSRF/DNS and streaming-size limits,
  expired/replayed/concurrent codes and refresh, denied consent, unknown account,
  subject/email conflicts, returned scopes, single-use rotation, local callback
  unavailable, user cancels browser, and authorization/token response no-store.
- Connection isolation: authorize two agents; disconnect one; its access and
  refresh fail everywhere while the other keeps working. Old bearer credentials
  remain valid; old unbound public MCP refresh prompts exactly the documented
  reauthorization. Existing ChatGPT/Claude hosted callbacks and confidential
  ChatGPT Action/Hermes paths remain covered separately.
- UI tests: opening setup performs no `/token/exchange`; configs contain no
  Authorization/token/env-secret fields; copying/installing config is secret-free;
  connection list/disconnect still works; full-access consent is accurate. Test
  card claim/import unaffected by retaining internal exchange.
- Primary regression files: memory `tests/test_oauth_connector.py`, CIMD/PKCE/OAuth
  UI tests discovered in checkout, `test_connect.py`, `test_s09.py`, MCP HTTP tests,
  session/client tests; new focused tests only where needed. Add frontend tests
  using existing test setup rather than introducing a new framework unnecessarily.
- Record real-client native/bridge login, restart, refresh and disconnect results
  for every named client. If a GUI/client is unavailable, report that specific
  validation gap and do not label it verified based on a mock or unrelated docs.

## Rollout And Boundaries

1. Complete auth/security review before deployment. No schema change expected;
   if reuse proves impossible, stop and revise migration design rather than
   silently adding production SQL.
2. Deploy auth backend before OAuth-only UI on dev, only after fresh approval.
   Dev shares production DB/Redis: namespace any new Redis records by grant
   version and issuer/resource, never consume another environment's grants.
   Production and development issuers/resources must not be interchangeable.
3. Shared DB/Redis means even dev consent creates connection records and existing
   consent code may seed persona memory. Real-user end-to-end tests require
   separate human approval; use isolated test accounts/data where authorized.
4. Verify public HTTPS metadata/routing without broad Caddy changes. Any required
   DNS, provider callback allowlist, or GitHub settings changes need separate
   approval. Do not copy secrets into logs, PRs, config snippets, or plans.
5. Human-approved production rollout after dev verification. Explain one-time
   OAuth reauthorization, unchanged old bearer validity, and removal of manual
   setup. Rollback code/UI together without deleting connection records; retain
   newly revoked rows and do not resurrect revoked credentials.

Out of scope: lifetime increases, device-code grant, custom CLI distribution,
granular OAuth permissions, third-party integration reauthorization, public Cards
MCP changes, production deployment, secret rotation, and removal of internal
token exchange or existing bearer verification.
