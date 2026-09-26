# zynd-platform

Zynd's consumer product suite: the AI **persona** each user gets, their
public **profile card**, and the shared **memory** layer both read from.

This is **not** the zynd.ai developer/agent-registry platform (that's the
separate `dashboard` repo) and **not** `zynd-bridge` (the local sync CLI,
also a separate repo — it ships to end machines and has to stay usable
against multiple server versions).

> **Working on this repo with an AI coding assistant?** Read
> [`AGENTS.md`](./AGENTS.md) first — it has the branch policy, shared
> database rules, and testing baselines every change needs to respect.

---

## What's in here

| Path | What it is | Stack | Prod URL |
|---|---|---|---|
| `apps/persona-web` | Persona's web UI — chat, connections, groups, settings | Next.js 16 | https://persona.zynd.ai |
| `apps/cards-web` | Public profile card site (new; not live yet) | Next.js | https://cards.zynd.ai (pending) |
| `services/persona-api` | Persona's backend — orchestrator, A2A protocol, MCP tools | FastAPI / Python | behind persona-web |
| `services/cards-api` | Cards' backend — onboarding, publish, search | FastAPI / Python | https://api.zynd.ai/cards |
| `services/memory` | Shared context layer — ingest, matching, MCP server, OAuth for ChatGPT/Claude/Cursor | FastAPI / Python | https://api.zynd.ai |
| `infra/persona-box` | pm2 process configs for the persona server | — | — |
| `infra/api-box` | Caddy + Docker Compose for the cards/memory server | — | — |
| `docs/persona` | Persona's architecture docs (identity, A2A protocol, groups) | — | — |
| `packages/` | Shared DB migrations / API contracts. **Planned, not built yet.** | — | — |

Each service came from its own repo (`agent-persona`, `zynd-cards`,
`memory-layer`) and was merged in with full git history — `git log --follow
<path>` and `git blame` work the same as they always did.

## Status

⚠️ **Mid-migration.** Nothing has been deployed *from this checkout* yet —
the servers still run the old standalone repos. `infra/` describes the
target layout, not necessarily what's live. See `AGENTS.md` §7 for the
current checklist, or ask a maintainer for the migration plan.

---

## Setup

Requirements: **Python 3.12**, **Node 20+**, **[uv](https://docs.astral.sh/uv/)**
(recommended over a bare venv). `services/memory` also wants Docker for its
local Postgres+Redis, or a Postgres 16+ instance with the `pgvector`
extension.

Each app/service is independent — install and run them from their own
directory, not the repo root.

### `services/persona-api` (FastAPI)

```bash
cd services/persona-api
python -m venv .venv && source .venv/bin/activate   # or: uv venv --python 3.12
pip install -r requirements.txt
cp .env.example .env   # no template checked in yet — ask a teammate for one
uvicorn main:app --reload --port 8000
```

```bash
pytest -q          # all tests
pytest tests/test_a2a_ping.py -v   # one file
```

### `apps/persona-web` (Next.js 16 + React 19)

```bash
cd apps/persona-web
npm install
# No .env.local.example is checked in yet — ask a teammate for one, or see
# CLAUDE.md's env var references (NEXT_PUBLIC_API_URL, NEXT_PUBLIC_MEMORY_API_URL, …).
npm run dev        # http://127.0.0.1:3000
npm run build && npm run start   # production mode
npm run lint
```

### `services/cards-api` (FastAPI)

```bash
cd services/cards-api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --port 8000
```

```bash
pytest -q
```

### `apps/cards-web` (Next.js)

```bash
cd apps/cards-web
npm install
cp .env.local.example .env.local
npm run dev        # http://127.0.0.1:3000
```

Card **reads** work today against the existing cards API. Login, claim, and
create do not work yet — they need a shared Supabase project set up first
(see `apps/cards-web/README.md`).

### `services/memory` (FastAPI + Postgres/pgvector + Redis)

```bash
cd services/memory
docker compose up -d              # Postgres (pgvector) on :5433, Redis on :6380
uv sync                           # or: pip install -e ".[dev]"
./scripts/apply_schema.sh         # or: make schema
uv run uvicorn app.main:app --reload --port 8000
```

```bash
uv run pytest -q -m "not integration"   # fast, no DB needed
uv run pytest -q                        # everything, needs the containers above
```

`make up` / `make down` / `make test` / `make test-unit` wrap the same
commands — see `services/memory/Makefile`.

---

## Testing summary

Run the relevant service's tests before and after any change. These
failures are known and pre-existing — don't spend time "fixing" them as a
side effect of an unrelated change:

| Service | Baseline failures | Why |
|---|---|---|
| `services/persona-api` | 5 | Env vars only set in prod (e.g. `MEMORY_LAYER_JWT_SECRET`) |
| `services/cards-api` | 2 | `test_x_bot.py`, unrelated env/mock gaps |
| `services/memory` | 9 | Need a live Postgres + Redis for integration tests |

## Branch policy (short version — full detail in `AGENTS.md`)

- **`dev`** — active branch. Persona auto-deploys from it to
  `dev.persona.zynd.ai`. Cards and memory don't auto-deploy from this repo
  yet.
- **`main`** — prod, protected, PR-only.
- Default: commit and push to `dev`. Never push to `main` directly.

## Further reading

- [`AGENTS.md`](./AGENTS.md) — full rules for any AI agent working here.
- [`docs/persona/architecture.md`](./docs/persona/architecture.md) — persona
  identity model, heartbeat design, security model.
- [`docs/persona/A2A.md`](./docs/persona/A2A.md) — the agent-to-agent
  protocol.
- Per-service `CLAUDE.md`/`AGENTS.md`/`README.md` inside `apps/*` and
  `services/*` — stack-specific conventions.
