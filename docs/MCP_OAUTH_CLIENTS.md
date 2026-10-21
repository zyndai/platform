# Zynd MCP OAuth client contracts

Research snapshot: 2026-10-15. This is a **contract and validation matrix**, not
proof that Zynd OAuth onboarding works in these products. The currently deployed
Zynd setup surfaces may still offer manual bearer credentials. Do not advertise
the candidate URL-only instructions as working until the corresponding client
has completed the real-client checks below against the updated server in an
approved isolated environment. Do not use a production account for this check.

Use the environment-specific Zynd memory MCP URL (`<Zynd MCP URL>`, ending in
`/mcp`), not the separate public Cards MCP. The ChatGPT plugin uses
`<origin>/chatgpt/mcp`, served by `services/chatgpt-plugin`, not this URL. No config below needs an access
token, `Authorization` header, client secret, or token-exchange call. An
existing Zynd account is required; general clients use the legacy `user` scope, which
now exposes the 17 registered Cards, memory, discovery and hosted-page tools
(not Persona or external integrations). Existing clients may need to refresh
their cached tool list after this catalog change. Consent, connection inventory,
and individual disconnect are implemented server-side with isolated tests, not a
verified property of these clients. Locally installed CLI versions below were
checked with **version/help only**; no account, config, callback, token storage,
refresh, or disconnect was exercised.

### Zynd Plugin Consent Draft (2026-10-16)

`services/chatgpt-plugin/package` version `0.2.0`, display name **Zynd**, targets a separate
reserved public OAuth client, `zynd-chatgpt-plugin`, with
`memory:recall memory:propose cards:review`. These are anticipated server
contracts, not evidence of deployed availability. None authorizes direct save
or publication. Existing broad ChatGPT grants must reconnect to the reduced
grant once the server policy is ready; never substitute `user` or legacy
direct-write scopes when a tool is unavailable.

The packaged allowlist is `recall_memories`, `propose_memory`,
`get_proposal_status`, `list_pending_facts`, `propose_card_fact`, and
`get_public_card`. Recall needs an explicit request and returns relevant
private facts only. Creating a temporary exact proposal also needs an explicit
request/agreement. A proposal is not durable memory or public content. Its
returned review link carries only an opaque ID and requires signed-in owner
web review. **Save privately** saves one exact private fact. Queueing private
card review does not publish. A separate web confirmation publishes one final
public fact; editing requires fresh confirmation. Chat yes, model booleans and
tokens do not perform either web decision. Status must distinguish pending,
rejected, expired, saved privately, publication committed, sync pending and
verified card visibility. Never claim card visibility from proposal success.

Local package checks and draft packaging (from the repository root):

```bash
python3 -m unittest discover -s services/chatgpt-plugin/package -p 'test_*.py'
python3 services/chatgpt-plugin/package/build.py
python3 services/chatgpt-plugin/package/build.py --output /tmp/zynd-draft.zip
python3 services/chatgpt-plugin/package/build.py --output /tmp/zynd-isolated.zip \
  --mcp-url https://memory.test.example/mcp \
  --review-origin https://cards.test.example
```

Replace both example targets with approved isolated HTTPS origins. The builder
rewrites only the generated ZIP, including OAuth resource, skill dependency
URLs and trusted review origins; it does not modify source manifests or deploy
anything. The source defaults are production URLs and are not permission to
connect or test production. No credentials or review-account secrets belong in
the package. The MCP URL must use `/mcp`; the review origin has no path.

For independent current-schema checks, install `jsonschema` in a disposable
environment and run `python3 services/chatgpt-plugin/package/build.py --official-schemas`. This
fetches the official Agent Plugins 1.0.0 schemas and validates `plugin.json`
and the portable MCP projection. As checked on 2026-10-16, the official MCP
schema rejects server `extensions` (`additionalProperties: false`), while
[OpenAI's packaging documentation](https://developers.openai.com/plugins/build/plugins.md#configure-mcp-authentication)
requires `extensions.com.openai.auth`. The builder validates that OAuth
extension separately, using a provided public client, no secret, resource
binding and the exact reduced scopes. **The full MCP document is not claimed
to pass the portable schema.** Resolve this vendor mismatch and validate the
installed host before submission. The schema check needs network access;
ordinary package tests and builds do not.

For isolated client validation, configure the actual callback displayed by
ChatGPT's MCP management UI on the isolated server, with PKCE S256 and the
reserved client. In ChatGPT Plugins, add the isolated HTTPS MCP URL, configure
the provided public OAuth client, create the plugin and authorize a test
account. Install the three packaged skills using the host's supported
local/workspace distribution, refresh metadata and start a new chat. Do not
invent a registered OpenAI mapping ID. Use two isolated test accounts; record
actual tool discovery, scope disclosures, recall/no-auto-recall, injection
handling, proposal then web save, separate exact-wording publication, expiry,
cross-account denial, reconnect/revocation and card sync visibility. This is
still **not tested in a real client**; package tests do not establish server
consent enforcement or transaction atomicity. The manifest's review prompts
are planned cases, not executed client evidence.

Local evidence on 2026-10-16: package tests passed (14, including the schema
validator test in a disposable Python 3.12 environment with `jsonschema`);
default and isolated draft ZIP builds succeeded; the live official plugin
schema and portable MCP projection checks passed. No real-client OAuth,
web confirmation or production behavior was exercised by these checks.

`--submission` remains fail-closed: verified support/privacy/terms URLs,
walkthrough, country availability, private reviewer-account details, domain
verification and actual OAuth/tool evidence are outstanding. Test-target ZIPs
cannot be submitted. Production deployment, provider configuration changes
and public submission require human approval.

## Client matrix

`Unknown` means the cited vendor documentation did not establish the precise
Zynd-specific behavior, not that the behavior is unsupported. The registration
column describes vendor-supported choices, **not** a successful registration
with Zynd. Unless explicitly stated, callback paths, local token persistence,
restart reuse, and refresh are **unverified for Zynd**.

| Client and local check | URL-only candidate and authentication | Callback / registration (vendor docs) | Persistence / refresh evidence | Choice and Zynd result |
| --- | --- | --- | --- | --- |
| Claude Code **2.1.288**, `claude --version`, `claude mcp --help`, `claude mcp add --help` | `claude mcp add --transport http zynd <Zynd MCP URL>`; in Claude `/mcp`, or installed `claude mcp login zynd`. HTTP `type` must be present in JSON config. | CIMD or DCR; Claude Code CIMD advertises `http://localhost/callback` and `http://127.0.0.1/callback`, with variable loopback port, exact host/path. | Vendor documents stored OAuth credentials and refresh before expiry/on 401; removing server deletes credentials. Exact local storage is not established here. | Native candidate. CLI syntax locally confirmed; Zynd login/restart/refresh **not tested**. [Claude Code](https://code.claude.com/docs/en/mcp), [Anthropic auth](https://claude.com/docs/connectors/building/authentication) |
| Claude Desktop / hosted Claude, **not installed/tested** | Settings (or Admin settings) > Connectors > Add custom connector > enter server URL; connect and authenticate. Do not confuse this hosted connector with Claude Desktop's local stdio config or Codex/ChatGPT desktop. | Hosted redirect `https://claude.ai/api/mcp/auth_callback`; CIMD or DCR, or explicitly provisioned OAuth client. | Vendor says hosted Claude refreshes reactively to 401 and proactively before expiry; precise hosted token store unknown. | Native hosted candidate; Zynd flow **not tested**. [Anthropic auth](https://claude.com/docs/connectors/building/authentication), [custom connectors](https://claude.com/docs/connectors/custom/add-unlisted) |
| ChatGPT **web** plugin/custom MCP connector, **not tested** | ChatGPT Plugins > Add custom MCP server > enter HTTPS `/mcp` URL, configure authentication; not the local Codex config. | CIMD preferred when enabled, DCR optional. Callback is **the exact URI shown on the MCP management page**: issuer-bound responses use `https://chatgpt.com/connector_platform_oauth_redirect`; otherwise `https://chatgpt.com/connector/oauth/{callback_id}`. Older published plugins may retain the stable URI. | Vendor describes attaching access tokens and reauthorization, but does not specify local storage or automatic refresh details in these sources; unknown here. | Native hosted candidate; workspace policy and Zynd flow **not tested**. [ChatGPT connection](https://developers.openai.com/plugins/deploy/connect-chatgpt.md), [auth](https://developers.openai.com/plugins/build/auth.md) |
| Codex CLI / IDE / **ChatGPT desktop app as Codex host**, `codex` **not installed** | `codex mcp add zynd --url <Zynd MCP URL>` then `codex mcp login zynd`; alternatively `[mcp_servers.zynd]` and `url = "<Zynd MCP URL>"` in `config.toml`. ChatGPT desktop app and Codex IDE share this config. | Auto CIMD when advertised with public `none` and supported loopback, otherwise DCR; default callback `http://127.0.0.1/callback` on varying port. With issuer-bound response, stable CIMD `/callback`; without, server-specific `/callback/{callback_id}` and matching CIMD. Pre-registered callback must match CLI-displayed URI exactly. | Vendor documents shared `config.toml` for client config and stored MCP OAuth credentials; credential file location / refresh after restart not established here. | Native candidate; command from docs only; Zynd flow **not tested**. [Codex MCP](https://developers.openai.com/codex/mcp.md) |
| Kilo CLI **7.8.8**, `kilo --version`, `kilo mcp --help`, `kilo mcp auth --help` | `{"mcp":{"zynd":{"type":"remote","url":"<Zynd MCP URL>"}}}` in Kilo config; `kilo mcp auth zynd` (installed help confirms positional `[name]`). | OAuth-capable remote servers documented; registration method and callback host/path for this installed version **unknown**. | `kilo mcp logout zynd` and auth status commands appear in installed help, but token location, restart and refresh **unknown**. | Native candidate; only CLI syntax locally confirmed; Zynd flow **not tested**. [Kilo CLI MCP](https://kilo.ai/docs/automate/mcp/using-in-cli) |
| OpenCode **v1** CLI/editor, `opencode` **not installed** | `{"mcp":{"zynd":{"type":"remote","url":"<Zynd MCP URL>"}}}` in v1 config; `opencode mcp auth zynd`. Do not use this v1 config shape for v2. | Vendor says DCR if supported; callback host/path unspecified in cited page. | V1 vendor says tokens stored at `~/.local/share/opencode/mcp-auth.json` and reused for future requests; refresh under Zynd rotation **not tested**. | Native candidate for **v1 only**; Zynd flow **not tested**. [OpenCode v1 MCP](https://opencode.ai/docs/mcp-servers/) |
| OpenCode **v2** CLI/editor, `opencode` **not installed** | `opencode mcp add zynd --url <Zynd MCP URL>` then `opencode mcp auth zynd`, or `{"mcp":{"servers":{"zynd":{"type":"remote","url":"<Zynd MCP URL>"}}}}`. V2 uses `mcp.servers`, unlike v1. | Vendor says PKCE and DCR where supported; optional configured loopback port/redirect for pre-registration. Default exact host/path unspecified here. | V2 vendor says it refreshes tokens and keeps credentials outside project config; exact storage path not given in cited v2 page. Zynd refresh/restart **not tested**. | Native candidate for **v2 only**; Zynd flow **not tested**. [OpenCode v2 MCP](https://opencode.ai/v2/docs/mcp-servers/) |
| Cursor editor / CLI `agent`, `agent` **not installed** | `{"mcpServers":{"zynd":{"url":"<Zynd MCP URL>"}}}` in global `~/.cursor/mcp.json` or project `.cursor/mcp.json`; CLI `agent mcp login zynd` where installed. Editor uses the same MCP config. | Vendor lists desktop `http://localhost:8787/callback` and web/Agents `https://www.cursor.com/agents/mcp/oauth/callback` for static OAuth; whether DCR uses exactly those on a given version needs confirmation. | Vendor docs confirm OAuth support for HTTP but do not establish Zynd token store, restart or rotating refresh. | Native candidate; Zynd flow **not tested**. [Cursor MCP](https://cursor.com/docs/mcp), [Cursor CLI](https://cursor.com/docs/cli/mcp) |
| Windsurf **legacy Cascade** (not Devin Local), **not installed/tested** | `{"mcpServers":{"zynd":{"serverUrl":"<Zynd MCP URL>"}}}` in `~/.config/devin/mcp_config.json` per current vendor docs; `url` also accepted. Open MCP config from Cascade actions; save, refresh, authenticate in UI. | Vendor says HTTP OAuth supported but callback host/path and registration mechanism unspecified in this guide. | Vendor does not establish Zynd credential store, restart or rotating refresh. | Native candidate **only for legacy Cascade**; not a Devin Local config; Zynd flow **not tested**. [Windsurf/Cascade MCP](https://docs.windsurf.com/windsurf/cascade/mcp) |
| Cline IDE / CLI, `cline` **not installed** | `{"mcpServers":{"zynd":{"type":"streamableHttp","url":"<Zynd MCP URL>"}}}`; IDE Remote Servers > Streamable HTTP > Add, or CLI `cline mcp` wizard > Authorize OAuth. Omitted `type` selects legacy SSE. | Vendor documents OAuth UI/CLI wizard but not callback host/path or registration method in this guide. | Vendor does not establish Zynd credential storage, restart or rotating refresh. | Native candidate; Zynd flow **not tested**. [Cline MCP](https://docs.cline.bot/mcp/configuring-mcp-servers) |
| Google Antigravity 2.0 IDE / CLI `agy`, **not installed/tested** | Google's official example uses `~/.gemini/config/mcp_config.json`, `mcpServers.<name>.serverUrl`, **plus pre-registered `oauth.clientId` and `oauth.clientSecret`** for Google Workspace; GUI Authenticate or CLI `/mcp` Authenticate. | That Google-specific example registers `https://antigravity.google/oauth-callback` and requires copying an authorization code back into GUI/CLI. No evidence a generic Zynd URL-only public DCR/CIMD connection follows that contract. | Storage, rotation and restart unknown. | Offered in the cards-web "Connect an assistant" panel (2026-10-21) as a bare `serverUrl` entry with **no** `oauth` block, so the Google-specific client ID/secret is never used; config path differs by version (`~/.gemini/config/mcp_config.json` on 2.0, `~/.gemini/antigravity/mcp_config.json` before), and the panel names both. Zynd login, callback, restart and refresh **not tested**; the panel says so. A third-party guide ([Eulerian](https://doc.eulerian.com/p/z2FiSpcXN5x-U2/Eulerian-MCP-Integration-Guide-for-Antigravity)) shows the same bare-`serverUrl` shape working against a non-Google OAuth server. [Google Antigravity client example](https://developers.google.com/workspace/guides/configure-mcp-servers), [Workspace codelab](https://codelabs.developers.google.cn/google-workspace-mcp-antigravity?hl=en) |
| OpenClaw, `openclaw` **not installed** | `{"mcp":{"servers":{"zynd":{"url":"<Zynd MCP URL>","transport":"streamable-http","auth":"oauth"}}}}`; `openclaw mcp login zynd`. Omitted transport defaults to legacy SSE. | Vendor documents dynamic registration and loopback callback, exact host/path selected at login not specified; `openclaw mcp login zynd --code <code>` supports an SSH/remote-browser handoff. Per-requester OAuth uses separate public gateway callback and is not this operator setup. | Vendor says owner-only `<state-dir>/state/openclaw.sqlite` stores access/refresh tokens and registration; refresh/login/logout serialized by SQLite lease. Zynd compatibility not verified. Shared operator credentials are not per-user chat identity. | Native **operator-shared** candidate only; Zynd flow **not tested**. [OpenClaw transports](https://docs.openclaw.ai/cli/mcp/transports) |

## Bridge decision

The maintained [`mcp-remote` project](https://github.com/geelen/mcp-remote)
documents a Node 18+ stdio-to-HTTP OAuth bridge, DCR/CIMD, default
`localhost:<port>/oauth/callback`, credentials under `~/.mcp-auth` (or
`MCP_REMOTE_CONFIG_DIR`), and token refresh. Its GitHub URL currently redirects
to the project's `punkpeye/mcp-remote` repository. **No pinned version was
installed or tested against Zynd**, including restart, refresh, and callback;
therefore **do not recommend or ship a bridge config** for any client. If native
OAuth fails in a particular version, test a pinned bridge with the MCP URL
alone (no `--header`, secret or pasted token), a protected local credential
directory, a supported Node runtime, and the full callback/refresh/restart
cycle before selecting it. If neither works, mark that version unsupported.
Do not substitute a longer-lived manual bearer token or claim that a device
grant exists. Headless/SSH login needs a client-supported browser handoff or
callback forwarding; OpenClaw's documented `--code` is client-specific.

## Verification still required

Older unbound rotating MCP refresh tokens require browser authorization once;
their existing access tokens and pasted bearer credentials are not revoked by
this change. Historical resource-bound confidential refresh grants used the same
unbound record format and also require that one-time reauthorization. New
confidential resource grants rotate with a separate client-bound record;
legacy non-rotating confidential refresh behavior is preserved. No production
records are deleted as part of this change.

For **each exact client and version**, record: config accepted; unauthenticated
HTTP challenge and discovery; actual DCR or CIMD client identity; exact
authorize and token-request callback (host, path, variable port); browser
sign-in and explicit full-access consent; one successful authenticated tool
call; token location/permissions where inspectable; reuse after restart;
refresh after forced expiry without browser; and failure of both access and
refresh after disconnect while another connection remains valid. Test issuer
validation (especially ChatGPT/Codex conditional callbacks), cancellation,
unavailable loopback and headless behavior. Only then change a row from
"not tested" to a dated result. Production account tests, shared production
DB/Redis state, deploys and provider configuration changes require separate
approval; help output and vendor docs are **not** end-to-end verification.
