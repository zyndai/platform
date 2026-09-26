# @zynd/db — the one migration history for the shared database

Persona and cards share one Supabase Postgres project, **aafo**
(`aafoguuvmaxymrtnfafn`). Every schema change to it, from either product,
is a migration in this folder. Nothing else creates tables, columns,
indexes, policies or functions there.

- **Drizzle is only used for the schema and migrations.** persona-api,
  cards-api and memory keep talking to the database through supabase-py;
  the web apps use supabase-js. No runtime code imports this package.
- **There is no staging database.** dev.persona.zynd.ai runs against prod
  aafo, so every migration you apply is live for dev *and* prod at once.
  Rehearse locally (below), keep migrations expand-only, and have the
  rollback SQL written before you apply.
- The full plan and its reasoning: [`docs/plans/ZYND_DB_UNIFY_PLAN.md`](../../docs/plans/ZYND_DB_UNIFY_PLAN.md).

## Layout

| Path | What |
|---|---|
| `src/schema/persona/*.ts`, `src/schema/cards/*.ts` | Tables, columns, constraints, indexes, RLS policies. Source of truth for everything Drizzle can express |
| `migrations/NNNN_*.sql` + `migrations/meta/` | The ordered history. Generated from the schema, or hand-written ("custom") for what Drizzle can't express |
| `scripts/migrate.ts` | `npm run db:migrate` — dry run by default; `-- --yes` applies |
| `scripts/check-drift.ts` | `npm run db:drift` — does a real database equal what the migrations build? |
| `scripts/catalog.sql` | The read-only catalog query `db:drift` compares (also runnable in the SQL editor) |
| `scripts/baseline-sql.ts` | `npm run db:baseline-sql` — marks 0000 as applied on a database that already has it |
| `scripts/preflight-cards.sql` | Read-only checks before the cards migrations |
| `scripts/lint-migrations.sh` | `npm run db:lint` — naming, owner header, journal consistency, no edits to merged files |
| `test/supabase-stubs.sql` | Enough of Supabase (roles, `auth.*`, publication, default grants) to apply migrations to plain Postgres |
| `introspection/` | Dated catalog exports of prod, kept as evidence |
| `OWNERS.md` | Which product owns which table, and who else reads it |

## What goes where

| Kind of change | How |
|---|---|
| Table, column, default, PK/FK/unique/check, index, RLS policy, generated column | Edit `src/schema/**`, then `npm run db:generate -- --name <owner>_<change>` |
| Extension, function, trigger, GRANT/REVOKE, realtime publication, data backfill | `npm run db:generate:custom -- --name <owner>_<change>`, then write the SQL in the new empty file |
| Changing a function or trigger | A **new** custom migration with `CREATE OR REPLACE` — never edit an old file |

## Workflow for a schema change

1. `git switch dev && git pull`, then create a branch.
2. Make the change as above. Read the generated SQL: when Drizzle asks
   whether a column was renamed, answer carefully, or you get drop + add
   (data loss).
3. First line of every new migration: `-- owner: persona|cards|shared`.
   Add a comment explaining *why*, and the rollback SQL.
4. Keep it **expand-only**: add columns/tables/indexes; don't drop or
   rename in the same release as the code change. Destructive changes are
   a second migration after every deploy has stopped using the old thing.
5. Rehearse locally (next section), then `npm run db:lint`, then open a PR
   to `dev`. Say "schema change" in the PR description (AGENTS.md §6). CI
   applies everything from an empty database and checks that the schema
   and migrations are in sync.
6. **Applying to prod** (any team member, after review):
   ```bash
   cd packages/db
   export DATABASE_URL='postgresql://postgres.aafoguuvmaxymrtnfafn:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres'
   npm run db:drift -- --expected "$DATABASE_URL" --scratch <local-scratch-url> --upto <last-applied-tag>  # must say "No drift"
   npm run db:migrate            # dry run: check Target and Pending
   npm run db:migrate -- --yes   # apply
   unset DATABASE_URL
   ```
   Use the **session pooler / direct** connection (port 5432), not the
   transaction pooler (6543).
7. Deploy code that needs the new schema only **after** step 6.

## Rules

- **No schema changes in the Supabase SQL editor.** An emergency hotfix
  made there gets committed as a migration the same day.
- **Never run `drizzle-kit push`** against aafo. There is no `db:push` script on purpose.
- **Never edit a migration that has been merged.** Add a new one. CI enforces this.
- **All pending migrations run in one transaction.** If one fails, none
  apply. That also means `CREATE INDEX CONCURRENTLY` can't be used; for a
  big table, apply that index by hand in a quiet window and record it in a
  migration that uses `CREATE INDEX IF NOT EXISTS`.
- Anything touching `persona_agents` or `search_personas_fts` needs the
  memory owner's review too (memory reads them — see `OWNERS.md`).
- The old SQL folders (`services/persona-api/db`,
  `services/persona-api/supabase/migrations`, `apps/persona-web/db`,
  `services/cards-api/db`) are frozen history. Don't add to them.

## Local rehearsal

Needs a throwaway Postgres (Homebrew is fine; the cards migrations also
need `brew install pgvector`). Never point this at Supabase.

```bash
initdb -D /tmp/zdb -U postgres --auth=trust && pg_ctl -D /tmp/zdb -o "-p 5544" -l /tmp/zdb.log start
psql -h 127.0.0.1 -p 5544 -U postgres -c 'create database rehearsal'
psql -h 127.0.0.1 -p 5544 -U postgres -d rehearsal -f test/supabase-stubs.sql
DATABASE_URL=postgresql://postgres@127.0.0.1:5544/rehearsal npm run db:migrate -- --yes
```

## The baseline (0000)

`0000_baseline_persona.sql` is aafo's public schema exactly as it was on
2026-09-26: 28 tables, 43 indexes, 72 policies, 4 functions, 1 trigger,
the realtime publication. Prod already has all of it, so on prod it is
**recorded, never run**:

```bash
npm run db:baseline-sql   # prints SQL; run it once in the aafo SQL editor
```

`db:migrate` refuses to run 0000 on a database that already has the persona
tables, so it can't be applied there by accident.

Proving the baseline equals prod: export `scripts/catalog.sql` from the
aafo SQL editor into `introspection/aafo-<date>.txt` (or pass the prod URL
directly), then:

```bash
npm run db:drift -- --expected introspection/aafo-<date>.txt --scratch <local-scratch-url> --upto 0000_baseline_persona
```
