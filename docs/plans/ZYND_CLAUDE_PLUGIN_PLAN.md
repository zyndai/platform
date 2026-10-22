# ZYND Claude Plugin — Plan

> **Status (2026-10-22):** phases 1-3 are on `dev`: the `/claude/mcp` server and
> audience-bound plugin OAuth, the bundle in `services/claude-plugin/package/`, and
> the `cards.zynd.ai/claude` page. Phase 4 (live test on dev, PR to `main`, prod env
> vars and deploy, submission) is open. Phase 1 changes memory's OAuth, so it needs a
> human sign-off before it reaches prod (AGENTS.md §6: auth). No schema change.
>
> **Scope:** new `services/claude-plugin/` (server + plugin bundle), small
> changes in `services/memory/app/oauth.py` and the token verifier, `infra/`
> routing, and a docs page in `apps/cards-web`. `services/chatgpt-plugin` is
> reused, not changed.

The ChatGPT plugin (`services/chatgpt-plugin`) gives ChatGPT a narrow,
consent-gated Zynd surface: six tools on `/chatgpt/mcp`, where the model can
recall on request and *propose* facts, and the owner saves or publishes them on
signed-in cards.zynd.ai. This plan builds the same thing for Claude and ships it
as a plugin in Anthropic's directory.

---

## 1. What Anthropic calls a plugin

Anthropic has two directory listing types, both submitted from
`claude.ai/directory/manage`:

| Type | What it is | Shows up in |
|---|---|---|
| MCP connector | A remote MCP server, reviewed on its own | claude.ai, Desktop, mobile, Cowork |
| Plugin bundle | A GitHub folder: `.claude-plugin/plugin.json`, `skills/*/SKILL.md`, `.mcp.json` | claude.ai directory, Cowork, Claude Code |

The plugin bundle is the counterpart of our OpenAI ZIP (`plugin.json`,
`mcp.json`, skills). A plugin may point at an MCP server we own; it does not
need a separate connector listing. (Policy 3.F additionally lets a plugin use
someone else's *approved* connector — not relevant here.)

**Decision:** submit a plugin bundle only. Its `.mcp.json` points at a new
`https://api.zynd.ai/claude/mcp` that serves the same six tools as ChatGPT.
The existing memory `/mcp` (35 tools, already usable as a Claude custom
connector) stays exactly as it is.

### Why a new `/claude/mcp` instead of pointing the bundle at `/mcp`

Both are allowed (we own `api.zynd.ai`), but `/mcp` would struggle in review:

- It messages other people (DMs, group invites) and `find_people` falls back to
  LinkedIn. Policy 3.F requires owning every endpoint the software connects to,
  and the plugin security scan flags data sent to undisclosed destinations.
- No tool has a `title`; direct writes (`send_card_dm`, `publish_page`,
  `approve_fact`) carry `destructiveHint: false`. Both are review findings.
- The six-tool consent design already went through OpenAI review, so its test
  cases and reviewer account carry over.

## 2. Anthropic's requirements (researched 2026-10-22)

Sources: [connector submission](https://claude.com/docs/connectors/building/submission),
[connector auth](https://claude.com/docs/connectors/building/authentication),
[review criteria](https://claude.com/docs/connectors/building/review-criteria),
[Software Directory Policy](https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy),
[plugin submission](https://claude.com/docs/plugins/submit),
[plugin checklist](https://claude.com/docs/plugins/pre-submission-checklist),
[plugin manifest](https://code.claude.com/docs/en/plugins/manifest-reference).

**Server and OAuth**

- Remote, HTTPS, Streamable HTTP.
- Every tool needs a `title` and the right `readOnlyHint` / `destructiveHint`.
  Tool names ≤ 64 chars. Errors must be specific (no bare "Bad Request").
- OAuth 2.0 with PKCE S256. Claude uses CIMD when the AS metadata advertises
  `client_id_metadata_document_supported: true` and `none` in
  `token_endpoint_auth_methods_supported` (memory already does), else DCR.
  **There is no field to give Claude a fixed client ID** — that only exists
  via mcp-review@anthropic.com. So, unlike ChatGPT, we can't identify the
  plugin by client ID.
- Redirects: hosted apps use `https://claude.ai/api/mcp/auth_callback`;
  Claude Code uses its CIMD at `https://claude.ai/oauth/claude-code-client-metadata`
  with loopback `http://localhost/callback` / `http://127.0.0.1/callback` on
  any port (memory's `_check_dcr_redirect_uri` already ignores loopback ports).
- An unauthenticated request must get a 401 with
  `WWW-Authenticate: Bearer resource_metadata="…"`. The protected-resource
  `resource` must equal the MCP URL exactly; Claude uses only the first
  `authorization_servers` entry.
- Public clients need rotated refresh tokens and `invalid_grant` on a bad one
  (memory already rotates). Discovery/register/token must answer within 10 s,
  refresh within 30 s.
- Anthropic's traffic comes from `160.79.104.0/21`; allowlist it if anything
  filters in front of `api.zynd.ai`.

**Policy items that matter for a memory product**

- 1.D / 1.F: collect only what the function needs; never read Claude's own
  memory, chat history or uploaded files.
- 2.D / 2.F / 2.G: instructions (server `instructions`, tool descriptions,
  skills) must be human-readable, must not tell Claude to call tools the user
  didn't ask for, and must not pull instructions from external sources.
- 3.A–3.E: privacy policy (missing one is an immediate rejection), verified
  support contact, public documentation, test account with sample data, at
  least three working example prompts.

**Plugin bundle**

- `.claude-plugin/plugin.json`; only `name` is required, but the directory
  reads `icon`, `documentationUrl`, `supportUrl`, `privacyPolicyUrl`,
  `termsOfServiceUrl`. Names must not start with `claude-` / `anthropic-` or
  equal reserved words (`claude`, `plugin`, `mcp`, …). `zynd` is fine.
- README of at least 40 words and a LICENSE (or `license` field) — both block
  if missing. No symlinks, submodules, LFS, `.DS_Store`; non-image files under
  256 KiB; no credentials anywhere.
- Skills need valid YAML front matter with a text `description`.
- `claude plugin validate --strict` must pass.
- Submitted from a public github.com repo + folder (`zyndai/platform` is
  public), by a Pro/Max account (or Team/Enterprise Owner) with push access.
  A security scan runs; a failing first submission is rejected. New versions
  are picked up from the tracked branch; bump `version` each release.

## 3. Design

### 3.1 Identify the plugin by token audience, not client ID

Today `plugin_mcp.is_plugin()` checks
`claims.oauth_client_id == settings.plugin_oauth_client_id`, and `/authorize`
picks the ChatGPT resource from the client ID. Claude's client ID is a CIMD URL
or a random DCR ID, so the Claude surface is keyed on the RFC 8707 `resource`:

- `/authorize` with `resource=https://api.zynd.ai/claude/mcp` (or its origin
  form) → allowed scopes are exactly `memory:recall memory:propose
  cards:review`, and the request is sealed with that resource.
- `/token` binds the token's audience to that resource (it already echoes and
  binds `resource`).
- The token verifier accepts the Claude audience; the Claude server's
  `PluginOnly` middleware accepts a token only if its audience is the Claude
  resource; memory's `/mcp` rejects plugin-audience tokens, and
  `/chatgpt/mcp` keeps rejecting anything that isn't the ChatGPT client.
- The review account (`PLUGIN_REVIEW_EMAILS`) is accepted on this flow, the
  same way it is for ChatGPT.
- The consent screen names the client "Claude" (from the CIMD `client_name`)
  and lists the three plugin scopes.

### 3.2 Reuse the ChatGPT tool code

`plugin_mcp.register` and `plugin_consent` are host-agnostic. The Claude server
imports them (the memory image already puts `/chatgpt-plugin` on
`PYTHONPATH`) and does not modify them. Proposals record `source_client_id`, so
reviews show which host created them. If the two servers drift, extract a
shared core later — not in this plan, to keep the live ChatGPT plugin
untouched.

## 4. Phases

### Phase 1 — Server: `services/claude-plugin/`

- `server.py`: FastMCP on `/claude/mcp`, `ExactIssuerAuth` (same issuer
  fix as ChatGPT), Claude-specific `instructions` text, audience-gated
  `PluginOnly` middleware, `title` on all six tools.
- `services/memory/app/config.py`: `claude_plugin_mcp_public_base_url` →
  `claude_plugin_mcp_origin` / `claude_plugin_resource_url`.
- `services/memory/app/oauth.py`: resource-based plugin detection (§3.1).
- Token verifier (`app/mcp_http.py`): add the Claude audience; `/mcp`
  rejects it.
- `/.well-known/oauth-protected-resource/claude/mcp`, served by the new
  container.
- Infra: Caddy routes for `/claude/mcp*` and its well-known path in
  `infra/api-box/Caddyfile` and `infra/single-box/Caddyfile`;
  `claude-plugin` service (port 8092) in compose; `deploy.sh` builds
  `claude-plugin` / `claude-plugin-dev`; memory Dockerfile copies the new dir
  and adds it to `PYTHONPATH`.
- Tests (mirroring `test_plugin_oauth`, `test_plugin_metadata`,
  `test_plugin_consent`): audience isolation in all directions, claude.ai
  callback, Claude Code CIMD loopback on a random port, scope restriction,
  reviewer login, tool list/visibility, 401 metadata.
- Run memory's baseline before and after
  (`cd services/memory && uv run pytest -q -m "not integration"`, 9 known
  failures) plus `pytest ../chatgpt-plugin ../claude-plugin -q`.

### Phase 2 — Bundle: `services/claude-plugin/package/`

```
package/
  .claude-plugin/plugin.json   name "zynd", version, description, author,
                               homepage, license, icon, documentationUrl,
                               supportUrl, privacyPolicyUrl, termsOfServiceUrl
  .mcp.json                    {"mcpServers":{"zynd":{"type":"http",
                                "url":"https://api.zynd.ai/claude/mcp"}}}
  skills/zynd-context/SKILL.md
  skills/zynd-memory/SKILL.md
  skills/zynd-card/SKILL.md
  assets/zynd-logo.png
  README.md                    ≥ 40 words: what it does, consent flow, links
  LICENSE
```

- Skills ported from the ChatGPT package without `agents/openai.yaml`, with
  wording reviewed against policy 2.D–2.G.
- A `build.py`-style test pins the file list, URLs, scopes and skill → tool
  mapping, like `chatgpt-plugin/package/test_build.py`.
- `claude plugin validate --strict services/claude-plugin/package` passes.

### Phase 3 — Docs page: `cards.zynd.ai/claude`

New page in `apps/cards-web`: install, the six tools, the propose → web-review
flow, what stays private, troubleshooting (sign-in, scopes, disconnect),
privacy/support links. Becomes `documentationUrl`. `npm run lint && npx tsc
--noEmit && npm run build` must pass.

### Phase 4 — Test, ship, submit

1. Push to `dev`; check `dev` deploy of the new container (cards/memory are
   not auto-deployed from this repo — see AGENTS.md §3).
2. Add `/claude/mcp` as a custom connector in claude.ai and connect; install
   the bundle in Claude Code via a local marketplace; run every tool and the
   web review end to end.
3. PR to `main` — a human reviews (auth change) and merges.
4. Prod deploy and Caddy update — only on the owner's go-ahead.
5. Verification script (like `verify_review_flow.py`) against prod.
6. Owner submits: `claude.ai/directory/manage` → Submit new → Plugin bundle,
   repo `zyndai/platform`, path `services/claude-plugin/package`, branch
   `main`. Data-handling answers: reads and stores personal data, sends data
   only to `api.zynd.ai`, retention per the privacy policy, not for under-18s.
   Test account `review@zynd.ai`, example prompts from the ChatGPT test cases.

## 5. Open items

- Is the existing memory `/mcp` listed in Anthropic's connector directory, or
  only used as a custom connector? Doesn't change this plan; worth knowing
  before anyone submits it separately.
- Who submits (needs a Pro/Max account with push access to `zyndai/platform`
  and the Claude GitHub App).
- `cards.zynd.ai/privacy` must cover data sent from Claude; check the wording
  before submission.
