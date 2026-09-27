# @zynd/db — migrations for the shared database

Persona and cards share one Supabase Postgres project, **aafo**
(`aafoguuvmaxymrtnfafn`). Postgres schemas are the boundary between them,
and each schema has its **own, independent migration history**:

| History | Owns schema | Folder | Tracking table | Owner / reviews |
|---|---|---|---|---|
| `identity` | `identity` | `identity/` | `drizzle.__identity_migrations` | shared: both products review |
| `persona` | `public` | `persona/` | `drizzle.__persona_migrations` | persona |
| `cards` | `cards` | `cards/` | `drizzle.__cards_migrations` | cards |

- **Independent.** persona's history never sees the `cards` schema, and
  cards' never sees `public`. Adding a column to a cards table is a cards-only
  PR. Each history applies in its own transaction.
- **No name clashes.** `cards.x` and `public.x` can both exist.
- **Cross-schema references still work** within the one database:
  `cards.agent_profile_cards.owner_user_id → auth.users(id)` is a normal FK.
- **`identity` is the only shared part.** It is what both products point at.
  Today that is Supabase's own `auth.users`, so the schema starts empty; the
  Zynd Account tables (Stage 2) go there. Keep it small and slow-moving.
- **persona stays in `public`** because its 28 tables have always lived
  there. Moving them into a `persona` schema would touch every query,
  realtime subscription and policy in persona-api, persona-web and memory,
  on a database with no staging copy. It can be a separate project later.
- **Drizzle is only used for schema and migrations.** persona-api, cards-api
  and memory keep using supabase-py; the web apps use supabase-js.
- **There is no staging database.** dev.persona.zynd.ai runs on prod aafo,
  so any migration you apply is live for dev *and* prod. Rehearse locally,
  keep migrations expand-only, and write the rollback SQL before applying.

The plan and its reasoning: [`docs/plans/ZYND_DB_UNIFY_PLAN.md`](../../docs/plans/ZYND_DB_UNIFY_PLAN.md).

## Layout

| Path | What |
|---|---|
| `<history>/schema/*.ts` | Tables, columns, constraints, indexes, RLS policies: everything Drizzle can express |
| `<history>/migrations/` | That history's ordered migrations + Drizzle's `meta/` |
| `<history>/drizzle.config.ts` | Which schema it owns and where it records progress (`lib/config.ts`) |
| `lib/shared.ts` | Helpers used by the schema files (FK naming, policy builders, `tsvector`) |
| `scripts/migrate.ts` | `npm run db:migrate`: dry run by default, `-- --yes` applies, `-- --project cards` for one history |
| `scripts/check-drift.ts` | `npm run db:drift`: does a real database equal what the migrations build? |
| `scripts/catalog.sql` | The read-only catalog query `db:drift` compares (also runs in the SQL editor) |
| `scripts/baseline-sql.ts` | `npm run db:baseline-sql`: records persona's 0000 on a database that already has it |
| `scripts/preflight-cards.sql` | Read-only checks before the cards history first reaches aafo |
| `scripts/lint-migrations.sh` | `npm run db:lint`: naming, owner header, journals, no edits to merged files |
| `test/supabase-stubs.sql` | Enough of Supabase (roles, `auth.*`, publication, default grants) to run migrations on plain Postgres |
| `introspection/` | Dated catalog exports of prod, kept as evidence |
| `OWNERS.md` | Who owns and who reads each table and function |

## Making a schema change

| Kind of change | Command (from `packages/db`) |
|---|---|
| Table, column, default, PK/FK/unique/check, index, RLS policy, generated column | Edit `<history>/schema/**`, then `npm run <history>:generate -- --name <change>` |
| Extension, function, trigger, GRANT/REVOKE, publication, data backfill | `npm run <history>:generate:custom -- --name <change>`, then write the SQL in the new empty file |
| Changing a function or trigger | A **new** custom migration with `CREATE OR REPLACE`; never edit an old file |

1. `git switch dev && git pull`, then create a branch.
2. Make the change as above. Read the generated SQL. When Drizzle asks
   whether a column was renamed, answer carefully, or you get drop + add
   (data loss).
3. First line of every migration: `-- owner: persona|cards|shared`. Explain
   *why*, and include the rollback SQL in the comment.
4. Keep it **expand-only**. Drops and renames happen in a later migration,
   once no deployed code uses the old thing.
5. Rehearse locally (below), run `npm run db:lint`, and open a PR to `dev`
   that says "schema change" (AGENTS.md §6). CI builds every history from an
   empty database and fails if schema files and migrations disagree.
6. **Apply to prod** (any team member, after review):
   ```bash
   cd packages/db
   export DATABASE_URL='postgresql://postgres.aafoguuvmaxymrtnfafn:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres'
   npm run db:drift -- --expected "$DATABASE_URL" --scratch <local-scratch-url> --upto <what prod has>   # must say "No drift"
   npm run db:migrate -- --project <history>          # dry run: check Target and pending
   npm run db:migrate -- --project <history> --yes    # apply
   unset DATABASE_URL
   ```
   Use the **session pooler or direct** connection (port 5432), not the
   transaction pooler (6543). `--upto` names, per history, the last migration
   prod already has, e.g. `--upto persona:0001_persona_drop_public_read,cards:none`.
7. Deploy code that needs the change only **after** step 6.

## Rules

- **No schema changes in the Supabase SQL editor.** An emergency hotfix done
  there becomes a migration the same day.
- **Never `drizzle-kit push`** against aafo. There is no push script on purpose.
- **Never edit a merged migration.** Add a new one; CI enforces it.
- **A history's pending migrations run in one transaction.** One failure rolls
  all of them back. So `CREATE INDEX CONCURRENTLY` can't be used: for a big
  table, build the index by hand in a quiet window and record it in a
  migration with `CREATE INDEX IF NOT EXISTS`.
- A new Postgres schema is not exposed by default. The cards schema only
  grants the service role, and it must be listed in the project's API
  **Exposed schemas** setting before cards-api can query it.
- Changes to `persona_agents` or `search_personas_fts` also need memory's
  owner: memory reads them (`OWNERS.md`).
- The old SQL folders (`services/persona-api/db`,
  `services/persona-api/supabase/migrations`, `apps/persona-web/db`,
  `services/cards-api/db`) are frozen history. Don't add to them.

## Local rehearsal

Needs a throwaway Postgres (Homebrew is fine; the cards history also needs
`brew install pgvector`). Never point this at Supabase.

```bash
initdb -D /tmp/zdb -U postgres --auth=trust && pg_ctl -D /tmp/zdb -o "-p 5544" -l /tmp/zdb.log start
psql -h 127.0.0.1 -p 5544 -U postgres -c 'create database rehearsal'
psql -h 127.0.0.1 -p 5544 -U postgres -d rehearsal -f test/supabase-stubs.sql
DATABASE_URL=postgresql://postgres@127.0.0.1:5544/rehearsal npm run db:migrate -- --yes
```

A brand-new Supabase project (e.g. a future dev project) is built the same
way: `db:migrate -- --yes` on an empty project runs every history, including
persona's baseline.

## persona's baseline (0000)

`persona/migrations/0000_baseline_persona.sql` is aafo's `public` schema
exactly as it was on 2026-09-26: 28 tables, 43 indexes, 72 policies,
4 functions, 1 trigger and the realtime publication. Prod already has all of
it, so on prod it is **recorded, never run**:

```bash
npm run db:baseline-sql   # prints SQL; run it once in the aafo SQL editor
```

`db:migrate` refuses to run persona's 0000 on a database that already has the
persona tables. To prove the baseline equals prod, export
`scripts/catalog.sql` from the aafo SQL editor into
`introspection/aafo-<date>.txt` (or pass the prod URL), then:

```bash
npm run db:drift -- --expected introspection/aafo-<date>.txt --scratch <local-scratch-url> \
  --upto identity:none,persona:0000_baseline_persona,cards:none
```
