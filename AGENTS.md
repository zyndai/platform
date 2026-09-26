# AGENTS.md — zynd-platform

This file is the source of truth for any AI coding agent (Claude Code, Cursor,
Windsurf, Gemini CLI, opencode, or a human skimming for the house rules)
working in this repository. `CLAUDE.md` at this same path is just
`@AGENTS.md` — edit this file, not that one.

**Read this file first. Then read the `CLAUDE.md`/`AGENTS.md`/`README.md`
inside the specific `apps/*` or `services/*` directory you're about to change**
— those cover stack-specific conventions (Next.js version quirks, the A2A
protocol, MCP tool wiring, …). This file only covers rules that apply across
the whole repo.

---

## 1. What this repo is

`zynd-platform` is Zynd's **consumer product suite**: the AI persona each
user gets, their public profile card, and the shared memory layer both read
from. It is deliberately **not**:

- **`dashboard`** (zynd.ai) — the developer/agent-registry platform. Separate
  repo, separate database, separate team concern. Never edit it from here.
- **`zynd-bridge`** — the local sync CLI users install via npm. Separate repo
  on purpose: it ships to end machines and must stay usable against multiple
  server versions, so it can't move in lockstep with this repo.

If a task mentions either of those by name, it's the wrong repo.

## 2. Layout

| Path | What it is | Stack | Public URL |
|---|---|---|---|
| `apps/persona-web` | Persona's web UI (chat, connections, groups, settings) | Next.js 16 | persona.zynd.ai |
| `apps/cards-web` | Public profile card site (new — replaces the old `dashboard` cards pages) | Next.js | cards.zynd.ai (not live yet) |
| `services/persona-api` | Persona's FastAPI backend: orchestrator, A2A protocol, MCP tools | FastAPI / Python | (behind persona-web) |
| `services/cards-api` | Cards' FastAPI backend: onboarding, publish, search | FastAPI / Python | api.zynd.ai/cards |
| `services/memory` | Shared context/memory layer: ingest, matching, MCP server, OAuth for AI clients | FastAPI / Python | api.zynd.ai |
| `infra/persona-box` | pm2 configs for the box running persona-api + persona-web | — | — |
| `infra/api-box` | Caddy + docker-compose for the box running cards-api + memory | — | — |
| `packages/db` | **The one migration history** for the shared aafo database (persona + cards), Drizzle — read its `README.md` before any schema change | TypeScript / Drizzle | — |
| `packages/contracts` | Shared API contracts. **Planned, not built yet.** | — | — |
| `docs/plans` | Architecture and migration plans behind this repo — start with `docs/plans/README.md` | — | — |

**History is preserved.** Each service was merged in with `git filter-repo`,
so `git log --follow <path>` and `git blame` walk all the way back through
its life as a standalone repo, not just the merge date.

## 3. Branch and push policy — no exceptions

- **`dev`** is the active branch. Persona (`persona-api` + `persona-web`)
  auto-deploys from it to `dev.persona.zynd.ai` via a webhook the moment you
  push. Cards and memory are **not yet** wired to auto-deploy from this
  monorepo — they still run from their old standalone-repo checkouts on the
  server until the cutover documented in the migration plans (ask a
  maintainer if you need those). Don't assume a push here reaches any live
  cards/memory environment yet.
- **`main`** is prod and is protected: PR-only, humans merge it.
- Default behavior after finishing a task: `git add -A && git commit -m
  "<short description>" && git push origin dev`, without asking permission.
  Skip this only if the user explicitly said not to commit/push.
- **Never push directly to `main`.** Never force-push a shared branch.
- Write commit messages that explain *why*, not just *what* — the next
  reader is usually debugging something at 2am, not admiring the diff.

## 4. Shared database — read before touching any schema

- `persona-api`, and `cards-api` (once its migration lands — check with a
  maintainer, it may still be on its old database), share **one** Supabase
  Postgres project. A migration to `persona_agents`, `dm_threads`, or any
  persona table can affect cards; a new cards table can collide with
  persona's naming.
- `services/memory` has its **own, separate** Postgres + pgvector database.
  It is reached **only** over its HTTP API — never open a direct DB
  connection to it from persona-api or cards-api, and never assume its
  tables live in the same database as persona/cards.
- **Every schema change to that database is a migration in `packages/db`**
  (Drizzle). Not the SQL editor, not a `.sql` file inside a service: the old
  SQL folders are frozen. Follow `packages/db/README.md`; `packages/db/OWNERS.md`
  says whose review a table needs.
- **There is no staging database.** dev.persona.zynd.ai uses prod aafo, so a
  migration applied anywhere is live everywhere. Rehearse locally, keep
  migrations expand-only, and apply them only on a human's say-so (§6).
- `services/memory` also *reads* aafo (`persona_agents`,
  `search_personas_fts`) with the service key. Changes to those need
  memory's owner in the loop.

## 5. Testing — before *and* after every change

Run the relevant service's tests before you start and after you're done.
Report only **new** failures against the baselines below — these are known,
pre-existing, and not yours to fix as a side effect of an unrelated change
(if you do fix one, call it out explicitly so it's not confused with scope
creep).

| Service | Command | Known baseline failures |
|---|---|---|
| `services/persona-api` | `cd services/persona-api && pytest -q` | 5 — need env vars (`MEMORY_LAYER_JWT_SECRET`, etc.) not set outside prod |
| `services/cards-api` | `cd services/cards-api && pytest -q` | 2 — `test_x_bot.py`, unrelated env/mock gaps |
| `services/memory` | `cd services/memory && uv run pytest -q -m "not integration"` | 9 — DB-dependent, need a live Postgres+Redis; integration tests (`-m integration`) skip cleanly without them |
| `apps/persona-web`, `apps/cards-web` | `npm run lint && npx tsc --noEmit`; `npm run build` before trusting `next start` locally | — |

If your sandbox lacks Docker or a working repo `.venv`, use
`uv venv --python 3.12 <path> && uv pip install -r requirements.txt` (or the
service's `pyproject.toml` dependencies) rather than fighting a broken
venv or skipping tests.

## 6. Always ask a human first

- Prod deploys, prod SQL, secret or token rotation.
- DNS, Vercel, or GitHub settings changes (branch protection, repo
  visibility, new repos).
- Deleting data, dropping tables, revoking access.
- Anything touching auth, payments, or the shared database schema — even on
  `dev`, call it out explicitly in your summary so a human notices before it
  reaches prod.
- Editing the `dashboard` or `zynd-bridge` repos from a session rooted here.

## 7. Migration status (2026-09-26)

This monorepo was assembled from three previously separate repos
(`agent-persona`, `zynd-cards`, `memory-layer`) with full git history kept.
Current state:

- ✅ All three services imported, tests passing at the baselines above.
- ✅ `apps/cards-web` scaffolded — card reads work; login/claim/create need
  a shared Supabase project and backend trust changes that haven't landed.
- ✅ `infra/` paths fixed for this layout.
- ❌ **Nothing has been deployed from this checkout yet** — prod and dev
  servers for cards and memory still run the old standalone repos. Don't
  trust `infra/` as a description of what's currently live; it's the target.
- 🟡 `packages/db` built (2026-09-26): migrations 0000 (baseline of prod
  aafo, verified), 0001 (persona security fix), 0002–0004 (cards tables) and
  its CI workflow. **Nothing applied to prod yet**: the baseline still has
  to be recorded there, and 0001–0004 applied. See
  `docs/plans/ZYND_DB_UNIFY_PLAN.md` §8.
- ❌ `packages/contracts` is not started. Cards still runs on the dashboard's
  Supabase project (xmfj) until the cutover in that plan.

If a task depends on any of the above being finished, check with a
maintainer rather than assuming the repo layout matches the live servers.

## 8. Tools available in this repo

**code-review-graph MCP** — if it's connected in your session, use it before
Grep/Glob for exploring code, tracing callers/callees, or scoping a review;
it's faster and gives structural context that file scanning can't. Fall back
to Grep/Glob/Read when the graph doesn't cover what you need, or when you're
in a service the graph hasn't indexed yet (it's per-checkout and this repo
is new).

| Tool | Use when |
|---|---|
| `detect_changes` | Reviewing code changes — risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |
