# Prisma — canonical schema for Zynd AI

`schema.prisma` is the source-of-truth for every table in the codebase.
Future schema changes go through Prisma migrations rather than hand-written
`.sql` patches.

## What runs on Prisma, what doesn't

| Concern                          | Where it lives                       |
|----------------------------------|--------------------------------------|
| Tables, columns, indexes, enums  | `prisma/schema.prisma` (canonical)   |
| RLS policies                     | `prisma/sql/policies.sql` (sidecar)  |
| Realtime publication             | `prisma/sql/policies.sql` (sidecar)  |
| Partial indexes (`WHERE …`)      | `prisma/sql/policies.sql` (sidecar)  |
| Runtime queries (backend)        | Python `supabase-py` (unchanged)     |
| Runtime queries (frontend)       | `@supabase/supabase-js` (unchanged)  |

Prisma manages the schema; runtime code stays on the Supabase clients.

## Setup (one-time per dev)

```bash
cd webapp
npm install           # picks up prisma as a devDependency
```

Then add the DB URLs to `webapp/.env` (see `prisma/.env.example` for the
format). Both come from Supabase Project Settings → Database.

## Day-to-day flow

### 1. Change the schema
Edit `prisma/schema.prisma`. Add a model, change a column, etc.

### 2. Validate locally
```bash
npm --prefix webapp run prisma:validate
npm --prefix webapp run prisma:format   # auto-format the file
```

### 3. Generate + apply a migration
For dev DBs, this generates a SQL migration AND applies it:

```bash
npm --prefix webapp run prisma:migrate:dev -- --name describe_change
```

For production / staging:

```bash
npm --prefix webapp run prisma:migrate:deploy
```

### 4. Re-apply RLS + realtime
The sidecar file is idempotent — re-run after every migration that
creates new tables:

```bash
npm --prefix webapp run prisma:policies
```

(Or paste `prisma/sql/policies.sql` into the Supabase Studio SQL editor.)

## The baseline migration (`0000_baseline`)

`prisma/migrations/0000_baseline/migration.sql` is the SQL that creates
every table from a fresh empty DB. It's the output of
`prisma migrate diff --from-empty --to-schema-datamodel …`, then
hand-trimmed to remove the `CREATE TABLE auth.users` block (Supabase
owns that table; the FK references still work because the schema
declares `schemas = ["public", "auth"]`).

A `npm run prisma:migrate:deploy` on a fresh Supabase project will:
1. Apply this baseline (all 19 public tables + enums + FKs).
2. Then any subsequent migrations Prisma generates from schema edits.

After deploy, run `npm run prisma:policies` to layer on the RLS + realtime.

## Adopting on an existing database

The Supabase project has historical `.sql` patches in `backend/db/` that
already created every table modeled here. To bring an existing DB under
Prisma's management without re-creating tables:

```bash
# Introspect the existing schema and compare to schema.prisma.
npm --prefix webapp run prisma:db:pull

# If the introspected schema matches what we have committed, mark the
# baseline migration as already applied without running it:
mkdir -p prisma/migrations/0000_baseline
npm --prefix webapp run prisma -- migrate diff \
  --from-empty \
  --to-schema-datamodel prisma/schema.prisma \
  --script > prisma/migrations/0000_baseline/migration.sql

npm --prefix webapp run prisma -- migrate resolve --applied 0000_baseline
```

After this, future `prisma migrate dev` runs generate only the *delta*
from the committed schema.

The legacy patches in `backend/db/*.sql` remain as historical record but
should NOT be applied to a DB that's been adopted under Prisma.

## What about Python / the backend?

The backend runs on `supabase-py` and Postgres directly — it doesn't
load `schema.prisma` at runtime. The schema here is purely a design /
migration artifact for the team. If we ever want runtime type safety in
Python, the path is `prisma-client-py` or `sqlalchemy` — both can be
added later without changing what's here.
