# Local development

Everything runs from the repo root.

## One-time setup

Needs Node 22+, [uv](https://docs.astral.sh/uv/) (Python 3.12 venvs), and
Docker only if you run memory locally.

```bash
npm run setup      # npm ci in apps/persona-web, apps/cards-web, packages/db
                   # + a .venv in each Python service (scripts/setup-python.sh)
```

Then create the env files from their templates (all gitignored, never
committed; no key is hard-coded anywhere in the code):

| Copy | To |
|---|---|
| `apps/persona-web/.env.local.example` | `apps/persona-web/.env.local` |
| `apps/cards-web/.env.local.example` | `apps/cards-web/.env.local` |
| `services/persona-api/.env.example` | `services/persona-api/.env` |
| `services/cards-api/.env.example` | `services/cards-api/.env` |
| `services/memory/.env.example` | `services/memory/.env` |

## Env vars

"Supabase" below means one Supabase project's values (Settings → API):
the project URL, the anon key (public) and the service-role key (secret,
backend only). Today that is aafo (prod); see the warning further down.

### Minimum to boot everything

| Where | Variable | Value locally |
|---|---|---|
| `apps/persona-web/.env.local` | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase URL + anon key |
| | `NEXT_PUBLIC_API_URL` | `http://localhost:8000` |
| | `NEXT_PUBLIC_MEMORY_API_URL` | `http://localhost:8001` |
| `apps/cards-web/.env.local` | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase URL + anon key |
| | `SUPABASE_SERVICE_ROLE_KEY` | service-role key (server-side only) |
| | `NEXT_PUBLIC_API_URL` | `http://localhost:8002` (cards-api) |
| | `NEXT_PUBLIC_ZYND_API_URL` | `http://localhost:8001` (memory: token exchange, findability) |
| | `NEXT_PUBLIC_SITE_URL` | `http://localhost:3002` |
| `services/persona-api/.env` | `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY` | Supabase URL + both keys |
| | `FRONTEND_URL`, `PUBLIC_PAGE_BASE_URL` | `http://localhost:3000` |
| | `MEMORY_LAYER_URL` | `http://localhost:8001` |
| | `MEMORY_LAYER_JWT_SECRET` | **same value as memory's `JWT_SECRET`** |
| | one LLM: `LLM_PROVIDER` + its key (`OPENAI_API_KEY`, or `OPENROUTER_API_KEY` + `OPENROUTER_MODEL`, or `GEMINI_API_KEY`, …) | your key |
| `services/cards-api/.env` | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | Supabase URL + service-role key |
| | `SUPABASE_DB_SCHEMA` | `cards` on aafo (once the cards migrations are applied); `public` on the old xmfj project |
| | `SUPABASE_JWT_SECRET` | the project's legacy JWT secret (only for old HS256 tokens; can stay empty) |
| | `OPENROUTER_API_KEY` (+ optional `OPENROUTER_MODEL`), `OPENAI_API_KEY` (embeddings for search) | your keys |
| | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_AI_KEY` | only for the profile chat widget (Workers AI) |
| | `FRONTEND_URL`, `SITE_BASE_URL`, `API_BASE_URL` | `http://localhost:3002`, `http://localhost:3002`, `http://localhost:8002` |
| | `MEMORY_LAYER_URL`, `MEMORY_SERVICE_TOKEN` | `http://localhost:8001`, **same value as memory's `MEMORY_SERVICE_TOKEN`** |
| `services/memory/.env` | `DATABASE_URL`, `REDIS_URL` | defaults already match `npm run dev:infra` (`localhost:5433`, `localhost:6380`) |
| | `JWT_SECRET`, `MEMORY_SERVICE_TOKEN` | any random strings, shared with persona-api / cards-api as above |
| | `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY` | Supabase values: memory verifies Supabase logins (`/token/exchange`) and reads `persona_agents` |
| | `PERSONA_ENABLED` | `true` to turn on the persona-network features (link, connect, message); off by default |
| | `OPENAI_API_KEY`, `DEEPSEEK_API_KEY` | embeddings + fact extraction (or `MOCK_LLM=true` to skip both) |
| | `PUBLIC_BASE_URL`, `MCP_PUBLIC_BASE_URL` | `http://localhost:8001`, `http://localhost:8090` |
| | `CORS_ORIGINS` | add `http://localhost:3002`: the default only allows `:3000` |
| | `ENABLE_DEV_BEARER=true`, `DEV_BEARER_TOKEN` | optional: call memory's API with a static token while developing |
| `packages/db` | `DATABASE_URL` | only when running migrations; session-pooler URL, port 5432 |
| `infra/local` | none | Postgres/Redis credentials are fixed (`zynd`/`zynd`) |

**Values that must match across services:** persona-api `MEMORY_LAYER_JWT_SECRET` = memory `JWT_SECRET`;
cards-api `MEMORY_SERVICE_TOKEN` = memory `MEMORY_SERVICE_TOKEN`.

### Optional, per feature

Everything else in the `.env.example` files turns on one integration and
can stay empty until you work on it: Google/LinkedIn/Twitter/GitHub/Notion
OAuth apps (persona-api, memory), Telegram (`TELEGRAM_BOT_TOKEN`,
`TELEGRAM_WEBHOOK_SECRET`), enrichment (`QUICKENRICH_*`, `APIFY_*`), web
search (`EXA_API_KEY`, `TAVILY_API_KEY`, `FIRECRAWL_API_KEY`), the X bot
(`X_*`), SEO pings (`INDEXNOW_KEY`, `BING_*`), analytics
(`NEXT_PUBLIC_GA_ID`, `NEXT_PUBLIC_ANALYTICS_ID`) and the Zynd network
(`ZYND_*`, `NGROK_AUTH_TOKEN`). OAuth logins in the browser also need
`http://localhost:3000/**` and `http://localhost:3002/**` in the Supabase
project's Auth redirect URLs.

## Run

```bash
npm run dev          # persona-web, cards-web, persona-api, cards-api together
npm run dev:infra    # memory's Postgres + Redis in Docker (infra/local/docker-compose.yml)
npm run dev:memory   # memory API + MCP server + worker (needs dev:infra)
```

Each piece also runs alone: `npm run dev:persona-web`, `dev:cards-web`,
`dev:persona-api`, `dev:cards-api`.

| Service | Local URL |
|---|---|
| persona-web | http://localhost:3000 |
| cards-web | http://localhost:3002 |
| persona-api | http://localhost:8000 |
| memory API | http://localhost:8001 |
| memory MCP | http://localhost:8090 |
| cards-api | http://localhost:8002 |
| memory Postgres / Redis (Docker) | localhost:5433 / localhost:6380 |

## Test

```bash
npm test                 # all Python suites + lint/typecheck of both web apps
npm run test:persona-api # or test:cards-api, test:memory, check:web
```

Known baseline failures are listed in `AGENTS.md` §5.

## Where the data lives

- **memory** uses plain Postgres + Redis, so it runs fully locally in Docker.
- **persona and cards** use Supabase: Postgres plus Auth (Google/LinkedIn
  OAuth), RLS, Storage and Realtime. Emulating Auth locally is the painful
  part, so local dev points `SUPABASE_URL` and the keys at a **hosted**
  Supabase project instead of a local one.

> **Warning: today that hosted project is prod.** There is no separate dev
> Supabase project yet, and dev.persona.zynd.ai already runs on prod aafo.
> Anything you do locally with aafo's keys reads and writes real user data.

**Recommended next step: a dev Supabase project.** It costs a small
always-on project, and in return local and dev stop touching prod. It can be
built entirely from the migrations:

1. Create a new Supabase project (e.g. `zynd-dev`, Postgres 17).
2. `cd packages/db && DATABASE_URL=<dev project session-pooler URL> npm run db:migrate -- --yes`.
   On an empty project the baseline (0000) runs for real, then every later
   migration. This is also a full rehearsal of every migration.
3. In the dev project's Auth settings, enable LinkedIn (OIDC) and add
   `http://localhost:3000/**` and `http://localhost:3002/**` as redirect URLs.
4. Put the dev project's URL and keys in the env files above, and in
   dev.persona.zynd.ai's env.

If fully-offline development is ever needed, `supabase start` (Supabase CLI)
runs the whole stack in Docker and the same migrations apply to it. It's
heavier, and OAuth redirects need extra setup.

## Why the root isn't an npm workspace

`package.json` at the root only runs scripts. Each app keeps its own lockfile
and installs in its own folder, because that is how they are built in prod:
pm2 on the persona box runs `npm` inside `apps/persona-web`, and Vercel
builds `apps/cards-web` as its root directory. An npm workspace moves every
lockfile to the root, which would change both of those builds. Don't run
`npm install` at the root; `/package-lock.json` is gitignored so a stray one
can't be committed.
