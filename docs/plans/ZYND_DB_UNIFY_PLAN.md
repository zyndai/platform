# Shared DB plan: cards data + login → persona DB (aafo), one Drizzle migration history

| | |
|---|---|
| **Status** | Plan · 2026-09-26 · nothing executed |
| **Goal** | Cards stops using the dashboard Supabase project (**xmfj**). Its tables, avatars and login move into the persona project (**aafo**), so cards and persona share one database and one set of users. Every schema change for that DB, from either product, is a migration in **`packages/db`**, managed by **Drizzle**. |
| **Replaces** | `ZYND_CARDS_MOVE_PLAN.md` §3 (Supabase-CLI layout for `packages/db`), P1, P3 and P4. Its P0, P2 (done) and P5 still apply and are referenced below |
| **Out of scope** | memory-layer keeps its own Postgres (decided). The zynd.ai dashboard keeps xmfj and its own Prisma schema; it only loses the cards tables at the end |

---

## 1. Where things stand (checked 2026-09-26)

**Monorepo `zynd/`:** on `dev`, clean, **no git remote yet** (M3 not done), **no `packages/` and no `.github/`** (M2.7–M2.9 not done). `apps/cards-web` is built (`5cd915b`) but not live. P0 from the cards-move plan (`TRUSTED_SUPABASE_URLS`, `MAINTENANCE_READONLY`) isn't in the code yet.

**aafo (persona, Postgres 17.6):** no migration tracking. Schema history is spread over three folders, all used recently, and nothing records which files ran on prod:
- `services/persona-api/db/` has 30 `patch_*.sql` files plus `schema.sql` and `migrate_v2.sql`
- `services/persona-api/supabase/migrations/` has 3 Supabase CLI files
- `apps/persona-web/db/migrations/0000–0004`, which is Prisma's folder format left over after Prisma was removed, plus `db/sql/policies.sql`

**Prisma was tried here and removed.** `a9b0c0e` (May 13) made Prisma the canonical schema, used only for migrations while the runtime stayed on supabase-py and supabase-js. `71fcd1a` (Jun 3) removed it. RLS policies, the realtime publication, partial indexes, and the FTS trigger/RPC all had to live in a side-car `policies.sql` that Prisma couldn't express.

**xmfj (cards part):** `agent_profile_cards`, `x_accounts`, `x_mentions`, `x_conversations`, and the functions `skill_names`, `match_cards` and `search_cards_fts`. It also has a `vector(1536)` column with an HNSW index, a generated `search_tsv` column with a GIN index, RLS policies and the `avatars` bucket. The prod schema has columns that no repo SQL creates (`owner_email`), so the prod dump is the source of truth. **The dashboard's `prisma/schema.prisma` doesn't model any cards table** (only `developer_keys`, `subscribers`, `blog_posts`, `entities`, …), so removing them from xmfj later doesn't touch the dashboard's Prisma history.

**xmfj schema export (user, 2026-09-26):** besides the dashboard tables and the 4 cards tables, xmfj also holds **copies of every persona table** (`persona_agents`, `dm_threads`, `api_tokens`, …), with the same columns as aafo, plus a `keyword_posts` table that no local repo references. **Scope confirmed by the user: only the 4 cards tables move. Login moves to aafo, and no xmfj users are copied.** The `agent_profile_cards` columns in prod are `id, status, handle_github, handle_x, card, search_tsv, created_at, updated_at, published_at, handle (unique), embedding, scrape_raw, user_intent, owner_email, suggested_posts, claim_token_hash`. None of the 4 cards table names exist in aafo, so there's no clash. The visualizer export leaves out indexes, policies, functions, triggers, the vector dimension, and whether `search_tsv` is generated or a plain default. The catalog query in the chat (2026-09-26) fills those gaps.

**aafo catalog (user, 2026-09-26):**
- **Extensions:** `pg_stat_statements`, `pgcrypto`, `plpgsql`, `supabase_vault`, `uuid-ossp`. **`vector` is not enabled**, so D3 has to enable it first.
- **Public functions:** `is_persona_group_member`, `is_persona_group_manager` (both SECURITY DEFINER), `persona_agents_search_vector_update` (a trigger function), `search_personas_fts`. There are no enums; bounded columns are `text` + CHECK.
- **Policies:** 70 in total. Every table has a `to public using (auth.role() = 'service_role')` policy. These are redundant, because service_role bypasses RLS, but the baseline reproduces them verbatim.
- **Still missing:** public indexes, the actual `CREATE TRIGGER`s, views, the realtime publication and grants.
- **Security:** policy `"Public read persona agents"` on `persona_agents` is `using (true)` for role `public`. Anyone with the anon key (it ships in every frontend) can read every persona's `brief_content`, `profile` and `webhook_url` through PostgREST. No app code reads `persona_agents` or `agent_profile_cards` from the browser; every read goes through the backends. xmfj's `"public read published cards"` has the same problem: it exposes `owner_email`, `claim_token_hash` and `scrape_raw` of published cards. agent-persona is a public repo, so keep this out of commit messages until it's fixed in prod.

**Ownership is by email, not by user id.** cards-api's `verify_supabase_jwt` returns the token's `email`, and cards store `owner_email`. No cards table stores an xmfj `auth.users` UUID. **So xmfj auth users don't need to be copied** (§4).

**Runtime access:** persona-api and cards-api use `supabase-py` with the service key. persona-web and cards-web use `@supabase/ssr` for login. cards-web writes directly only to Storage (`avatars`); everything else goes through cards-api.

**Local tooling:** Homebrew Postgres 18 **without pgvector**, and no Docker. Applying the cards migrations locally needs `brew install pgvector` (ask first) or a staging Supabase project/branch.

## 2. Decision: Drizzle, not Prisma (recommended)

In both cases the tool only manages the schema and migrations. The Python services keep using supabase-py, and nothing about the runtime changes.

| Need in this DB | Drizzle (`drizzle-kit`) | Prisma |
|---|---|---|
| RLS policies, Supabase roles | Native: `pgPolicy`, `.enableRLS()`, `authenticatedRole`/`anonRole`/`serviceRole` from `drizzle-orm/supabase` | Not supported, so they end up in a side-car file again |
| `vector(1536)` + HNSW `vector_cosine_ops` | Native `vector({dimensions})`, `index().using('hnsw', col.op('vector_cosine_ops'))` | `Unsupported("vector")`, and the index is hand-edited SQL |
| Generated `tsvector` column + GIN | `customType` + `generatedAlwaysAs(sql…)`, GIN index native | Unsupported |
| Functions, triggers, realtime publication | `drizzle-kit generate --custom`: hand-written SQL **in the same ordered journal** | Hand-edited migrations; `migrate dev` then reports drift |
| FK to Supabase-owned `auth.users` | `authUsers` from `drizzle-orm/supabase`; `schemaFilter: ['public']` leaves `auth`/`storage` alone | multiSchema, plus manually stripping `auth.users` from the baseline (done last time) |
| Adopt a live DB | `drizzle-kit pull` → schema.ts + snapshot | `db pull` + `migrate resolve` |
| Shadow DB | Not needed (diffs against the committed snapshot) | `migrate dev` needs one, and it fights Supabase-managed schemas |

The one thing Prisma has going for it is that the dashboard team knows it. That doesn't outweigh having to rebuild the side-car the team already abandoned once, now with vectors and RPCs on top.

## 3. `packages/db` layout and rules

```
packages/db/
├── package.json            # "@zynd/db", private; drizzle-kit, drizzle-orm, pg, tsx — EXACT versions pinned
├── drizzle.config.ts
├── src/schema/
│   ├── _supabase.ts         # re-exports authUsers + roles from drizzle-orm/supabase; tsvector customType
│   ├── persona/*.ts         # from `drizzle-kit pull`, split by domain (agents, dm, groups, callbacks, …)
│   ├── cards/cards.ts       # agent_profile_cards
│   ├── cards/x_bot.ts       # x_accounts, x_mentions, x_conversations
│   └── index.ts
├── migrations/             # drizzle-kit `out`: NNNN_name.sql + meta/_journal.json + snapshots
├── scripts/
│   ├── mark-baseline-applied.ts   # inserts 0000's hash into drizzle.__drizzle_migrations (never runs its SQL)
│   ├── preflight.sql              # read-only: name clashes, extensions, row counts
│   └── check-drift.sh             # prod schema dump vs. scratch DB built from migrations, normalized diff
├── test/supabase-stubs.sql # auth schema, auth.users, auth.uid(), roles anon/authenticated/service_role — for CI only
├── OWNERS.md               # table → persona | cards | shared
└── README.md
```

`drizzle.config.ts`: `dialect: 'postgresql'`, `schema: './src/schema/index.ts'`, `out: './migrations'`, `schemaFilter: ['public']`, `entities: { roles: { provider: 'supabase' } }`, `migrations: { schema: 'drizzle', table: '__drizzle_migrations' }`, `strict: true`, `dbCredentials.url = DATABASE_URL`. `DATABASE_URL` must be the **direct or session-pooler (5432)** connection, not the transaction pooler (6543).

**First migrations**

| # | Kind | Contents |
|---|---|---|
| `0000_baseline_persona` | custom | `pg_dump --schema-only --schema=public --no-owner --no-privileges` of aafo as it is today: tables, enums, functions, triggers, policies, and grants the app needs. **Marked applied on prod, never run there.** A fresh DB (CI, staging, local) gets the full persona schema from it |
| `0001_cards_prereqs` | custom | `create extension if not exists vector with schema extensions;` plus `skill_names(jsonb)`. It has to come before the table, because the generated `search_tsv` column calls it |
| `0002_cards_tables` | generated | The 4 tables exactly as in the xmfj prod dump (including `owner_email`, `claim_token_hash`, `handle unique`, `embedding vector(1536)`), HNSW + GIN + status/handle indexes, RLS + the existing policies. **New:** `owner_user_id uuid null references auth.users(id) on delete set null` + index (§4) |
| `0003_cards_functions` | custom | `match_cards`, `search_cards_fts`, and their grants |

**Rules** (these go in the README)
1. Every schema change to aafo is a migration here, whichever product needs it. Tables and columns: edit `src/schema/**`, then run `npm run db:generate -- --name <owner>_<change>`. Functions, triggers and publications: use `--custom`. Every file starts with `-- owner: persona|cards|shared`.
2. Read the generated SQL before committing. Drizzle turns a rename into drop + add unless you answer its prompt, so check for that.
3. **Never run `drizzle-kit push` against staging or prod.** Only `db:migrate`, run by a person: staging first, `check-drift.sh` clean, then prod.
4. Each migration runs in a transaction, so `CREATE INDEX CONCURRENTLY` on a big table goes in its own custom migration with a note.
5. The old SQL folders (`services/persona-api/db`, `services/persona-api/supabase/migrations`, `apps/persona-web/db`, `services/cards-api/db`) get a "Frozen — see packages/db" README. `apps/persona-web`'s `db:policies` script is removed.
6. Standalone package with its own lockfile and **no root workspace** for now, so the Vercel builds of the two apps don't change. Shared TS types for the apps can come later.

**CI (`.github/workflows/db.yml`, `paths: packages/db/**`):** `drizzle-kit check`, then apply every migration to a `pgvector/pgvector:pg17` service container after `supabase-stubs.sql`. Next, run `drizzle-kit generate` and require empty output (schema.ts and migrations in sync). Last, lint the `-- owner:` headers.

## 4. Auth: how the logins move

**Recommendation: don't copy xmfj users into aafo.** Card owners sign in to cards.zynd.ai with Google, LinkedIn or a magic link, which creates or reuses their **aafo** user. Ownership is still checked against `owner_email`, so a card stays theirs as long as the email is the same, the same rule as today.

Why not copy `auth.users`/`auth.identities`:
- Nothing in cards references xmfj UUIDs, so there's nothing to preserve.
- xmfj also holds every dashboard developer account. Copying would put non-cards people into the persona user base.
- Card owners who already use persona have an aafo user under a **different UUID**. A copy would mean merging two users per person, which is exactly the "4 identities per person" problem the platform work is removing.

**Linking the two products.** This is the step that actually connects them.
- `agent_profile_cards.owner_user_id` → `auth.users(id)` in aafo, the same id persona uses. A card and a persona then join on one user id, which is the `zynd_uid` Stage 2 builds on.
- **Backfill at cutover:** `update agent_profile_cards c set owner_user_id = u.id from auth.users u where lower(u.email) = lower(c.owner_email) and c.owner_user_id is null;`
- **Going forward:** `verify_supabase_jwt` returns `(email, sub)`. Each authenticated publish/claim/edit sets `owner_user_id = sub` when the token's issuer is aafo.
- `owner_email` stays the authority for ownership until Stage 2. `owner_user_id` is additive.

**Token trust during the switch (cards-move P0, unchanged):** cards-api `TRUSTED_SUPABASE_URLS` and memory `TRUSTED_SUPABASE_PROJECTS` accept xmfj **and** aafo, with one JWKS client per issuer and `iss` pinned. Drop xmfj 14 days after cutover.

**Pre-checks (read-only, the user runs them):** on xmfj, the number of distinct `owner_email` among non-archived cards, and any emails that differ only by case. On aafo, how many of those emails already exist in `auth.users`. That shows how many owners land on an existing persona user and how many create a new one.

## 5. Data move

Scripts live in `services/cards-api/scripts/migrate_to_persona/`, dry-run by default. **The agent writes them and the user runs them.**
- **`copy_tables.sh`:** `pg_dump --data-only` of the 4 tables from xmfj, then `psql --single-transaction` into aafo in FK order: `agent_profile_cards` first, then `x_accounts`, `x_conversations`, `x_mentions`. It truncates the target first so it can be re-run for the rehearsal and the final copy. `search_tsv` is generated, so pg_dump skips it and aafo recomputes it. Embeddings copy as-is, with no re-embedding.
- **`copy_avatars.py`:** list xmfj `avatars` → download → upload to aafo `avatars` at the same path. Then rewrite `…xmfj….supabase.co/storage/v1/object/public/avatars/` to the aafo host inside `card` JSON (text replace on `card::text`, cast back to jsonb, only rows that contain the old host). It reports missing objects and leaves external URLs (GitHub/LinkedIn avatars) alone.
- **`verify.sql`:** row counts per table and per status; `md5(string_agg(id || md5(card::text), ',' order by id))` on both sides; unique handles; embeddings present; one `match_cards` and one `search_cards_fts` call with the same input on both sides, which should return the same top 10.

## 6. Phases

Stop after each phase and report. Nothing below touches prod unless the user runs it.

**D0: Monorepo prerequisites (agent + user).** `git pull` doesn't apply yet because there's no remote. Creating `zyndai/zynd` (M3) is needed before CI and Vercel, but not for D1–D3.

**D1: Scaffold `packages/db` (agent, branch off `dev`).**
- Package, config, stubs, README, OWNERS, `db:generate`/`db:migrate`/`db:check` scripts, CI workflow, frozen READMEs.
- Remove `db:policies` from persona-web.
- Nothing runs against any database in this phase.

**D2: Baseline aafo (user runs read-only commands, agent builds).**
- **User:**
  1. `npx drizzle-kit pull` with `DATABASE_URL` = aafo (read-only role, if you have one).
  2. `pg_dump --schema-only --schema=public --no-owner --no-privileges` of aafo, using a pg_dump 17 client.
  3. `select * from pg_publication_tables where pubname = 'supabase_realtime'`
- **Agent:** turns the pulled schema into `src/schema/persona/*`, makes `0000_baseline_persona.sql` from the dump (adding publication lines if the dump left them out), and applies the full chain to a scratch Postgres. It then diffs a dump of that scratch DB against the prod dump; the diff must be empty apart from ordering.
- **User:** `npm run db:mark-baseline` on aafo. That's a single insert into `drizzle.__drizzle_migrations`. *Rollback:* `drop schema drizzle cascade` (it holds only the tracking table).

**D3: Cards schema in aafo (agent writes, user applies).**
- **User:** runs the read-only schema dump of the 4 tables, 3 functions and policies on **xmfj**.
- **Agent:** writes 0001–0003 to match that dump, plus `owner_user_id`.
- **User:** runs `preflight.sql` on aafo (no name clashes, `vector` available), enables `vector` in the dashboard if needed, then runs `npm run db:migrate` on aafo. This creates empty tables and functions, so it's additive.
- *Rollback:* a down script that drops the 4 tables and 3 functions. They're empty at this point.

**D4: Code, deployed with both issuers trusted (agent, then user deploys).**
- Cards-move P0: multi-issuer auth in cards-api and memory, `MAINTENANCE_READONLY`, publish de-dup.
- Also: `(email, sub)` from `verify_supabase_jwt`, and `owner_user_id` set on aafo-authenticated writes.
- Tests are compared against the A4 baselines (cards 2 failed / 89 passed, memory 9 failed / 203 passed).
- cards-api still points at xmfj.
- *Rollback:* redeploy the previous image.

**D5: aafo auth setup (user, dashboard clicks).**
- **Google OAuth client and LinkedIn app** (the ones xmfj uses today, or new ones): add aafo's callback `https://aafoguuvmaxymrtnfafn.supabase.co/auth/v1/callback`.
- **aafo → Auth:** enable Google, LinkedIn (OIDC) and email. Add `https://cards.zynd.ai/**` plus the Vercel preview and localhost URLs to the redirect list. Set up **custom SMTP** before relying on magic links, because Supabase's built-in mailer is heavily rate-limited.
- **aafo → Storage:** a public `avatars` bucket with an upload policy for `authenticated` only.
- **Then:** smoke-test cards-web on a Vercel preview. Login works against aafo, and data still comes from xmfj through the API.

**D6: Rehearsal (user runs, while live).** Run `copy_tables.sh`, `copy_avatars.py` and `verify.sql` from xmfj to aafo. Nothing reads the aafo copy yet. Fix anything the verify step flags. The final copy re-truncates, so the rehearsal leaves nothing behind.

**D7: Cutover (quiet hour; a `docs/cards/CUTOVER.md` runbook with a rollback line per step).**
1. `MAINTENANCE_READONLY=true` on cards-api, which also pauses the X poller.
2. Final `copy_tables.sh`, then `copy_avatars.py`, then `verify.sql`, which must match.
3. Run the `owner_user_id` backfill (§4).
4. Switch cards-api `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` to aafo in `infra/api-box`, restart, and check reads, search, chat and the X bot.
5. Point cards.zynd.ai DNS at the Vercel project, then smoke-test login, claim, create, edit and avatar upload.
6. `MAINTENANCE_READONLY=false`.

*Rollback before step 6:* point the env back at xmfj and restart. xmfj was read-only, so nothing is lost. *After step 6:* writes made on aafo would need copying back, so decide within the first hour.

**D8: Cleanup (day +14).**
- Remove xmfj from the trusted issuers.
- Cards-move P5: dashboard feature branch that removes the cards UI and adds the 301s.
- Rename the xmfj cards tables to `*_retired`, then drop them after another 14 days. This is plain SQL, because they aren't in the dashboard's Prisma schema.
- Remove the xmfj `avatars` bucket.

## 7. Choices I've made (say so if you want them changed)

1. **Drizzle** over Prisma (§2).
2. **Cards tables stay in the `public` schema.** cards-api's supabase-py queries and RPC calls then don't change at all; only the URL and key do. A separate `cards` Postgres schema is cleaner for ownership, but it has to be exposed in PostgREST and every `.table()`/`.rpc()` call changed. Ownership is tracked with `src/schema/cards/` and `OWNERS.md` instead.
3. **No copy of xmfj auth users** (§4).
4. `packages/db` is a **standalone** npm package, with no root workspace yet.
5. **The cards tables in aafo drop the anon `"public read published cards"` policy.** Only service_role gets access, because cards-api does every read. Nothing in cards-web, the dashboard or memory queries the table directly (checked 2026-09-26).
6. **A migration right after the baseline, `persona_lock_public_reads`,** replaces `persona_agents`' `using (true)` read policy. Owner-only reads stay; the backend keeps using service_role. It's a separate migration so it can be rolled back on its own if something external turns out to depend on it.

## 8. Questions only you can answer

- **Staging.** Is there a staging Supabase project or branch for aafo? Rehearsing D3/D6 there is safer. The alternative is a local rehearsal, which needs `brew install pgvector` (a scratch cluster on port 5544, as in `local-dev-tooling`).
- **OAuth apps.** Reuse xmfj's Google/LinkedIn OAuth apps (just add the aafo callback), or create new ones for Zynd Account?
- **Open duplicates.** `0xsy3`/`0xsy3-pobf` and `chandan-kumar`/`chandan867` (cards-move §2). Settle them before D6 so they don't get carried over.

## 9. Risks

| Risk | Mitigation |
|---|---|
| The baseline doesn't match prod exactly, and the next generated migration fights the real schema | D2 scratch-apply + dump diff must be empty. `check-drift.sh` before every prod migrate |
| Someone keeps changing aafo in the SQL editor | README rule, `check-drift.sh` in the release checklist, frozen READMEs in the old folders |
| `drizzle-kit` upgrades change the migrations-table format | Exact version pin. `mark-baseline-applied.ts` is tied to that version |
| An owner signs in with a provider whose email differs from `owner_email` | Same as today. Claim tokens and support can reassign the card; `owner_user_id` makes that easier later |
| A name clash between cards and persona tables in `public` | `preflight.sql` in D3 before any migrate |
| The magic link hits the email rate limit on launch day | Custom SMTP in D5 |
