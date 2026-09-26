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
