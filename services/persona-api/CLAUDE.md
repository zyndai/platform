# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.

## Git workflow (always follow, no exceptions)

This repo is checked out on `dev`, which auto-deploys to dev.persona.zynd.ai via webhook the moment you push. `main` is prod and is manual-merge-only by humans.

Whenever you finish ANY task that changes files in this repo, your LAST action before reporting done must be:

1. `git add -A`
2. `git commit -m "<short description>"`
3. `git push origin dev`

Do this automatically. Do NOT ask the user "want me to commit it?" or "should I push?" — just do it, then report what you shipped. Only skip this if the user explicitly said not to commit/push in their request. Never push to `main` (blocked by the pre-push hook anyway).

## Fast path for trivial changes (speed matters)

For small, low-risk changes (copy/text edits, styling tweaks, adding a static banner/line, config value changes) — do NOT spin up a local dev server, run a full npm install, run a full build, or curl/browser-check localhost to verify. That verification loop is the slowest part of a simple task and is unnecessary for content-only edits.

Instead, for trivial changes: make the edit, do a quick sanity check by re-reading the changed lines (or a fast lint/typecheck if one is already configured and fast, e.g. under ~10s), then commit and push per the git workflow above. Skip `npm install` / `npm run build` / `npm run dev` / spinning up servers entirely unless the change touches logic, dependencies, imports, API routes, env vars, or you were explicitly asked to verify the build.

Reserve the full install+build+serve+verify loop for changes where correctness genuinely depends on it (logic changes, new dependencies, config that affects the build, anything you're not confident will just work).

---

## Project overview

Zynd is a multi-tenant AI agent platform: users create autonomous "personas"
(FastAPI backend + Next.js frontend) that live on the Zynd AI Network, get
discovered by other agents, receive messages, and take actions on behalf of
their owner (posting tweets, scheduling calendar events, querying Notion,
etc). The design docs that used to live at the repo root —
`architecture.md` (identity/HD key derivation, DB schema, heartbeat manager,
request flows, registry integration, security model), `A2A.md` (the
agent-to-agent protocol: JSON-RPC 2.0 task FSM, connection FSM, permission
enforcement, replay protection), `GROUPS.md` (Persona Groups rollout), and
`theme.md` (frontend visual design system) — are **not in this repo**. Find
them in the old standalone `agent-persona` repo's history, or
`git log --all --oneline -- '**/architecture.md'` from this repo if they
were ever imported. The summaries below cover the same ground at a glance.

## Commands

### Backend (`services/persona-api/`, Python/FastAPI)

```bash
cd services/persona-api
pip install -r requirements.txt
uvicorn main:app --reload --port 8000     # run dev server
pytest                                     # run all tests
pytest tests/test_a2a_ping.py              # run a single test file
pytest tests/test_a2a_ping.py::test_name -v  # run a single test
```

`tests/conftest.py` adds this directory to `sys.path` so tests import
`api.*` / `agent.*` / `mcp.*` the same way the running app does. There's no
separate lint config in `backend/`.

### Webapp (`apps/persona-web/`, Next.js 16 + React 19 + Tailwind 4)

```bash
cd apps/persona-web
npm run dev      # dev server on 127.0.0.1 (see package.json)
npm run build    # required before `next start` picks up any change
npm run start
npm run lint
```

### Production deployment (PM2 + Caddy)

This is now part of the `zynd` monorepo. Two checkouts run on the box:

| Channel | Branch | Code dir | pm2 apps | Backend | Web | URL |
|---|---|---|---|---|---|---|
| Prod | `main` | `/home/ubuntu/zynd-platform` | `api`, `web` | 127.0.0.1:8000 | 127.0.0.1:3001 | https://persona.zynd.ai |
| Dev | `dev` | `/home/ubuntu/zynd-platform-dev` | `api-dev`, `web-dev` | 127.0.0.1:8001 | 127.0.0.1:3002 | https://dev.persona.zynd.ai |

pm2 configs live at `infra/persona-box/ecosystem.config.js` (prod) and `infra/persona-box/ecosystem.dev.config.js` (dev).

- Caddy (`/etc/caddy/Caddyfile`) fronts both: `/api/*` → backend port,
  everything else → web port. PM2 apps: prod from `ecosystem.config.js`, dev
  from `ecosystem.dev.config.js`. After adding/removing apps: `pm2 save`.
- Env files are gitignored; each copy has its own `.env` / `.env.local` (dev
  differs only in `FRONTEND_URL`, `PUBLIC_PAGE_BASE_URL`,
  `NEXT_PUBLIC_API_URL`; `ZYND_WEBHOOK_BASE_URL` and OAuth redirect URIs stay
  on prod).
- Both copies share: Supabase project, LLM/API keys, memory layer, and the
  Zynd identity keypair (`~/.zynd/developer.json`).
- **Telegram**: only prod may register the webhook (one URL per bot). Never
  run `services/persona-api/scripts/register_telegram_webhook.py` on the dev box. The webhook
  rejects updates without `TELEGRAM_WEBHOOK_SECRET` once that env var is set.

**Deploy flow (dev first, then prod):** commit + push to `main` → on each
copy: `git pull`, `pip install -r requirements.txt` only if it changed,
`npm run build` in `apps/persona-web/` (required — `next start` serves stale
artifacts otherwise), then `pm2 restart api-dev web-dev` (dev) or
`pm2 restart api web` (prod). Prefer per-app `pm2 restart` names over
`pm2 restart all`, which also bounces the deployer.

## Architecture

### Identity: HD-derived Ed25519 keypairs

Every persona's cryptographic identity is derived from a single admin
developer keypair (`~/.zynd/developer.json`) via HD derivation — no private
keys are ever stored in the database, only a `derivation_index` per user in
`persona_agents`. On every server startup, `agent/persona_manager.py`
rehydrates all active personas by re-deriving their keypairs from the
developer key + stored index. See `architecture.md` for the exact
derivation algorithm and `agdns:` agent ID format.

### Heartbeats are batched, not per-agent

`agent/heartbeat_manager.py` runs a single asyncio task that heartbeats all
personas to the Zynd registry (`zns01.zynd.ai`) in batches over one shared
WebSocket per batch, instead of one persistent connection per persona. This
is the key scalability decision in the codebase — see "Heartbeat
Architecture" in `architecture.md` before changing anything here.

### Request flow: everything funnels through the orchestrator

`agent/orchestrator.py` is the single LLM orchestration loop used for both:
- **Internal chat** (`api/chat.py`) — the user talking to their own persona,
  full tool access.
- **External A2A traffic** (webhooks in `agent/a2a_router.py`, plus group
  mentions via `agent/group_dispatch.py`) — another agent or a group
  `@mention` talking to the persona, restricted to only the capabilities the
  owning user explicitly granted (`external_permissions`), no destructive
  actions, brief responses. This internal/external split is the core
  security boundary in the system — read "Security Model" in
  `architecture.md` before adding new tool-calling entry points.

Tools available to the orchestrator's LLM are registered in
`backend/mcp/server.py` (wraps the local `contextaware/` framework) with
implementations under `backend/mcp/tools/` — social (Twitter, LinkedIn),
Google Workspace (Calendar, Docs, Gmail, Sheets, Drive), Notion, and Zynd
Network tools (search, connect, message/call other agents, services).

### Agent-to-agent protocol (A2A)

`agent/a2a_router.py` implements the receiving side of the A2A v3 protocol
described in `A2A.md`: JSON-RPC 2.0 over `POST /a2a/v1`, per-message Ed25519
`x-zynd-auth` envelopes, a task FSM (`submitted → working →
input-required/auth-required → completed/canceled/failed/rejected`), and a
connection FSM stored on `dm_threads` (`none → requested → accepted |
declined | blocked → revoked`). Permissions are enforced at three layers:
the advertised agent card, the connection's `dm_threads.permissions`, and
the orchestrator's tool allowlist — a foreign agent (or a hallucinating LLM)
cannot exceed what the connection explicitly grants. `services/callbacks.py`
wires up outbound push-notification delivery for async task replies; it's
imported for its side effect in `main.py`'s lifespan startup, not called
directly.

### Persona Groups

Multi-user chat rooms where personas can be `@mentioned` to act on behalf of
a specific member. `agent/group_dispatch.py` parses `@DisplayName` mentions
in `api/groups.py` messages and routes each to `orchestrator` via
`handle_user_message(is_external=True, ...)`, translating group-level
permissions into the same `external_permissions` shape used for A2A. See
`GROUPS.md` for the phased rollout and what's shipped vs. planned.

### Persistence

Supabase/Postgres (project aafo, shared with cards). **All schema changes go
through `packages/db`** (Drizzle migrations; see its README). The old SQL in
`services/persona-api/db/`, `services/persona-api/supabase/migrations/` and
`apps/persona-web/db/` is frozen history: never re-run it. The verified
current schema is `packages/db/migrations/0000_baseline_persona.sql` plus
the migrations after it. RLS policies on `dm_threads`/`dm_messages` accept both
Supabase user UUIDs and `agdns:` agent IDs in the same TEXT columns since a
thread can be between two humans, a human and an agent, or two agents.

### Frontend structure

Next.js App Router under `webapp/src/app/`. Key surfaces: `dashboard/`
(authenticated persona management — chat, identity, connections, groups),
`p/` and `g/` (public persona pages / group invite links), `pages/`
(published persona pages). Shared state lives in `webapp/src/contexts/`
(`DashboardContext` for auth), reusable UI in `webapp/src/components/`.
