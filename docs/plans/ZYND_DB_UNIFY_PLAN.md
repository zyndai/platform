# Shared DB plan: cards data + login → persona DB (aafo), schema-separated Drizzle migrations

| | |
|---|---|
| **Status** | 2026-09-27 · `packages/db` built with three independent histories (D14); nothing applied to prod yet. Progress: §8 |
| **Goal** | Cards moves off the dashboard Supabase project (**xmfj**, `xmfjvixclgqcmjmtecwv`) and into the persona project (**aafo**, `aafoguuvmaxymrtnfafn`). That covers its 4 tables, its avatars and its login. Cards and persona then share one database and one set of users (`auth.users`), separated by Postgres schema: persona in `public`, cards in `cards`, the shared identity layer in `identity`. Each schema has its own independent Drizzle migration history in **`packages/db`** (D14) |
| **Replaces** | `ZYND_CARDS_MOVE_PLAN.md` §3, P1, P3 and P4. Its P0 is folded in here (§7). Its P2 (`apps/cards-web`) is done. Its P5 (dashboard cleanup) still applies, at the end (§8 phase I) |
| **Out of scope** | `services/memory` keeps its own Postgres. The zynd.ai dashboard keeps xmfj and its own Prisma schema. `zynd-bridge` is not touched |
| **Evidence** | Full catalog dumps of both projects, from the query in Appendix A, run by the user in the Supabase SQL editor on 2026-09-26, plus a code read of this repo on the same day |

---

## 0. Summary

1. **Tool:** Drizzle (`drizzle-kit` 0.31.x + `drizzle-orm` 0.45.x, exact pins) in `packages/db`. It manages schema and migrations only. The runtime stays on supabase-py / supabase-js.
2. **Three histories, one per Postgres schema (D14):** `identity` (shared, empty for now), `persona` (owns `public`), `cards` (owns a new `cards` schema). Each migrates independently.
3. **persona baseline:** persona's `0000` recreates aafo's `public` schema exactly as it is today: 28 tables, 43 extra indexes, 4 functions, 1 trigger and 72 policies. It is recorded as already applied on prod and never runs there.
4. **Persona security fix:** persona's `0001` drops the `using (true)` read policy on `persona_agents`.
5. **Cards:** cards' `0000`–`0002` create the `cards` schema in aafo: `vector` extension, 4 tables, 3 functions, service-role-only access, plus one new column, `cards.agent_profile_cards.owner_user_id → auth.users`.
6. **Logins:** no users are copied. Card owners sign in to aafo, and ownership still matches on `owner_email`. `owner_user_id` is filled at cutover by email match, then set on every signed-in write. That shared user id is what links a card to a persona.
7. **Data move:** `pg_dump --data-only` of the 4 tables (from xmfj's `public` into aafo's `cards`) plus a copy of the `avatars` bucket, rehearsed first, then a final copy during a short read-only window.
8. **After cutover:** 14 days of rollback safety, then xmfj trust is removed and the xmfj cards tables and bucket are dropped.

---

## 1. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **Drizzle**, not Prisma. Pin `drizzle-kit@0.31.11` and `drizzle-orm@0.45.3`, the current `latest` tags (not the 1.0 betas) | Drizzle expresses RLS policies, Supabase roles, `vector(n)`, HNSW/GIN indexes and generated columns natively. Functions, triggers and publications go in hand-written migrations **inside the same ordered history**. Persona already tried Prisma (`a9b0c0e`) and removed it three weeks later (`71fcd1a`), because RLS, the realtime publication, partial indexes and the FTS trigger/RPC had to live in a side-car SQL file |
| D2 | `packages/db` is the **only** place schema changes to aafo come from, organised as independent histories per schema (D14) | Tracked, reviewable in PRs, reproducible on a fresh database |
| D3 | **Only the 4 cards tables and the `avatars` bucket move**: `agent_profile_cards`, `x_accounts`, `x_mentions`, `x_conversations` | User decision. xmfj's copies of the persona tables, `keyword_posts` and the dashboard tables stay where they are (§2.3) |
| D4 | **Login moves to aafo, and no users are copied** | Nothing in cards stores an xmfj user id, because ownership is `owner_email` (§5) |
| D5 | ~~Cards tables go in the `public` schema~~ **Superseded by D14 (2026-09-27): cards goes in its own `cards` schema.** cards-api switches schema with one env var (`SUPABASE_DB_SCHEMA`, used as the client's default schema), so no query code changes | — |
| D6 | `vector` goes in the **`extensions`** schema on aafo (xmfj has it in `public`) | Supabase default and lint-clean. Cards functions get `set search_path = cards, extensions` |
| D7 | **Cards tables are service-role only**: drop the anon `"public read published cards"` policy, revoke table grants and RPC execute from `anon`/`authenticated` | No code reads cards tables from a browser. cards-web goes through cards-api. On aafo, Supabase's default grants would give `anon` full table privileges, so the old policy would expose `owner_email`, `claim_token_hash` and `scrape_raw`. On xmfj it can't be used today, because xmfj revoked `anon`/`authenticated` grants on every table. This keeps that effective access |
| D8 | Drop the `persona_agents` `"Public read persona agents"` policy (`using (true)`) in its own migration, `0001` | It exposes every persona's `brief_content`, `profile` and `webhook_url` to the anon key. Checked: no code reads `persona_agents` with anon, and every RLS subquery on `persona_agents` filters `user_id = auth.uid()`, which `"Users can read own persona"` still allows (§2.4) |
| D9 | `packages/db` is a **standalone npm package** (own lockfile, no root workspace) | Vercel builds of `apps/*` stay unchanged. Shared TS types can come later |
| D10 | Prod migrations are applied **by a person**. Anyone on the team may run them, after a clean drift check and a local rehearsal | AGENTS.md §6: prod SQL needs a human |
| D11 | **There is no staging database.** `dev.persona.zynd.ai` runs against **prod aafo** (user, 2026-09-26). The rehearsal is a local scratch Postgres (stubs + pgvector), and every migration must be **expand-only**, so that the code on `dev` and on `main` both keep working against the same database. Destructive changes need two steps: expand, deploy, then contract | Any migration applied is live for dev and prod at once |
| D12 | **Cards uses persona's login: LinkedIn (OIDC) only.** Google, GitHub and the email magic link are removed from cards-web. Magic links come back once an email provider (SMTP) is chosen, which is `null` for now | User decision. aafo already has LinkedIn configured, so no new OAuth app is needed |
| D14 | **Postgres schemas are the boundary; one migration history per schema** (user, 2026-09-27). `identity` = the one shared layer (reviewed by both products; empty until Stage 2, since today the shared id is `auth.users`). `persona` owns `public`. `cards` owns `cards`. Each has its own folder, its own tracking table (`drizzle.__<name>_migrations`) and its own transaction; one tool (Drizzle) and one set of scripts serve all three | Independent ownership without two tools fighting over one database: no name clashes, no shared PR queue for product-only changes, and cross-schema FKs/joins still work. persona is **not** moved into a `persona` schema now: that would touch every persona query, realtime subscription and policy on a database with no staging copy |
| D15 | **The monorepo root is a script runner, not an npm workspace**, and local dev points persona/cards at hosted Supabase while memory's Postgres + Redis run in Docker (`docs/LOCAL_DEV.md`) | pm2 and Vercel install inside each app folder; a workspace would move lockfiles to the root. Supabase Auth is the hard part to emulate locally |
| D13 | **Remove xmfj's copies of the persona tables** once the activity check (Appendix F) proves nothing uses them. Leave `keyword_posts` alone | User decision. The dashboard code and this repo don't reference either (checked 2026-09-26) |

---

## 2. Current state (verified 2026-09-26)

### 2.1 Repo

- **Repo:** `zynd-platform` (remote `zyndai/platform`), with `dev` active and `main` protected. `packages/` and `.github/` don't exist yet.
- **cards-web:** `apps/cards-web` is built but not live, and already configured for aafo auth.
- **P0 code:** none of it exists yet (`TRUSTED_SUPABASE_URLS`, `MAINTENANCE_READONLY`).
- **Old SQL folders, none of them tracked** (nothing records what ran on prod):

  | Folder | Contents |
  |---|---|
  | `services/persona-api/db/` | 30 `patch_*.sql`, plus `schema.sql` and `migrate_v2.sql` |
  | `services/persona-api/supabase/migrations/` | 3 files |
  | `apps/persona-web/db/migrations/0000–0004` | Prisma-format leftovers, plus `db/sql/policies.sql`. `apps/persona-web/package.json` had a `db:policies` script (removed in phase A) |
  | `services/cards-api/db/` | 6 files; they miss prod columns such as `owner_email` |

### 2.2 aafo (persona), the target

| Item | Value |
|---|---|
| Postgres | 17.6 (Supabase) |
| Extensions | `pg_stat_statements`, `pgcrypto`, `uuid-ossp` (schema `extensions`), `plpgsql`, `supabase_vault`. **No `vector`** |
| Tables (28, all in `public`, RLS enabled on all) | `a2a_tasks`, `agent_tasks`, `api_tokens`, `brief_todos`, `callback_results`, `chat_messages`, `dm_messages`, `dm_threads`, `enriched_companies`, `enriched_contacts`, `github_profiles`, `linkedin_profiles`, `oauth_pending_state`, `outbound_callbacks`, `pending_approvals`, `persona_agents`, `persona_group_audit_events`, `persona_group_constraints`, `persona_group_invitations`, `persona_group_members`, `persona_group_messages`, `persona_groups`, `published_pages`, `suggested_contact_runs`, `suggested_contacts`, `telegram_chat_history`, `telegram_links`, `twitter_profiles` |
| Tables with RLS on and **no** policies (service role only) | `oauth_pending_state`, `persona_group_invitations` |
| Constraints | PKs, uniques, CHECKs (limited-value columns are `text` + CHECK, **no enums**), FKs to `auth.users(id)` with `ON DELETE CASCADE` / `SET NULL` |
| Indexes | 43 besides the constraint-backed ones. They include partial indexes (`agent_tasks_one_open_proposal`, `brief_todos_user_title_uniq`, `persona_group_invitations_open_uniq`, …), a GIN index (`persona_agents_search_vector_idx`) and `NULLS FIRST` / `DESC` orderings. Two are duplicates of unique constraints: `published_pages_slug_idx`, `telegram_links_chat_idx` |
| Functions (4) | `is_persona_group_member(uuid)`, `is_persona_group_manager(uuid)` (both `SECURITY DEFINER`, `search_path=public`, **EXECUTE revoked from PUBLIC**, granted to anon/authenticated/service_role), `persona_agents_search_vector_update()` (trigger), `search_personas_fts(text,int)` |
| Trigger (1) | `persona_agents_search_vector_trigger` BEFORE INSERT OR UPDATE on `persona_agents` |
| Policies | **72**. Every table has a redundant `"Service role full access on …"` (`to public using (auth.role()='service_role')`). The baseline copies them verbatim |
| Realtime publication `supabase_realtime` | `a2a_tasks`, `agent_tasks`, `callback_results`, `dm_messages`, `dm_threads`, `outbound_callbacks`, `pending_approvals`, `persona_group_invitations`, `persona_group_messages` |
| Table grants | Supabase defaults (ALL to `anon`, `authenticated`, `postgres`, `service_role`) on every table. These come from default privileges, so the baseline doesn't create them |

### 2.3 xmfj (dashboard), the source

**Cards objects, the only ones that move:**

| Object | Prod definition |
|---|---|
| `agent_profile_cards` | `id text PK`, `status text NOT NULL DEFAULT 'draft'`, `handle_github text`, `handle_x text`, `card jsonb NOT NULL`, `search_tsv tsvector GENERATED ALWAYS AS (…skill_names(card)) STORED`, `created_at`/`updated_at timestamptz NOT NULL DEFAULT now()`, `published_at timestamptz`, `handle text UNIQUE`, `embedding vector(1536)`, `scrape_raw jsonb`, `user_intent jsonb`, `owner_email text`, `suggested_posts jsonb`, `claim_token_hash text` |
| its indexes | `agent_profile_cards_embedding_hnsw_idx` (hnsw, `vector_cosine_ops`), `agent_profile_cards_tsv_idx` (gin), `agent_profile_cards_status_idx`, `idx_cards_owner_email`, `agent_profile_cards_handle_idx` (duplicates the unique constraint, so it's not recreated) |
| `x_accounts` | `x_user_id text PK`, `username text NOT NULL`, `card_id text → agent_profile_cards(id)` (NO ACTION), `created_at`/`updated_at` NOT NULL DEFAULT now() |
| `x_conversations` | `id uuid PK DEFAULT gen_random_uuid()`, `x_user_id text NOT NULL`, `card_id text → agent_profile_cards(id)`, `status text NOT NULL DEFAULT 'initial'`, `current_question text`, `answered jsonb NOT NULL DEFAULT '{}'`, timestamps; index `x_conversations_user_idx(x_user_id)` |
| `x_mentions` | `tweet_id text PK`, `x_user_id text NOT NULL`, `text text`, `status text NOT NULL DEFAULT 'processed'`, `created_at` NOT NULL DEFAULT now(); index `x_mentions_user_idx(x_user_id)` |
| functions | `skill_names(jsonb)` IMMUTABLE; `match_cards(vector, int=200)` STABLE; `search_cards_fts(text, int=200)` STABLE. No `search_path` set; exact bodies are in Appendix C |
| policies | `"public read published cards"` (to public, `status='published'`), `"service role full access on cards"` and the 3 `x_*` equivalents (`to service_role using (true) with check (true)`) |
| grants | only `postgres` and `service_role`: xmfj revoked `anon`/`authenticated` on all tables |
| extension | `vector` 0.8.0 **in schema `public`** |
| storage | bucket `avatars`; card JSON stores public URLs on the xmfj storage host |

**Staying in xmfj, not migrated:**
- **Dashboard tables:** `developer_keys`, `entities`, `subscribers`, `blog_posts`, `topups`, `_prisma_migrations`. The dashboard's `prisma/schema.prisma` doesn't model the cards tables, so dropping them later doesn't affect its Prisma history.
- **`keyword_posts`:** service-role policy only. **No code in this repo or the dashboard references it.** Owner unknown (§12).
- **Stale copies of all 28 persona tables.** They don't match aafo: RLS is **disabled** on 12 of them, the `persona_group_*` service-role policies are missing, and the realtime publication covers only 5 tables. They must never be used as a source. Row counts tell us whether anything still writes to them (§12).

### 2.4 Who touches the aafo schema from code

| Consumer | How | Depends on |
|---|---|---|
| `services/persona-api` | supabase-py with the **service key** (`config.get_supabase()`). The anon client (`get_supabase_anon()`) is used **only** for realtime broadcasts on `system_pings` (`mcp/tools/zynd_network.py`, `services/meetings.py`) | all persona tables; RPC `search_personas_fts` |
| `services/memory` | supabase-py with the **service key** against **aafo** (`app/tools/zynd_network.py`) | `persona_agents` (`agent_id, name, description, active, updated_at`), RPC `search_personas_fts`. **So memory is a schema consumer too:** changes to these need memory's owner in the loop |
| `apps/persona-web` | supabase-js as the **signed-in user**: reads `dm_threads` and `agent_tasks`, realtime `postgres_changes` on dm/tasks/callbacks/group tables | RLS policies + realtime publication |
| `services/cards-api` | supabase-py with the **service key**: `sb.table("agent_profile_cards"…)`, RPC `match_cards`, `search_cards_fts` (`services/search.py`) | cards tables + functions |
| `apps/cards-web` | supabase-js for **login and Storage (`avatars`) only**. Card data goes through cards-api | Auth config, `avatars` bucket |

Check for D8: no code reads `persona_agents` or `agent_profile_cards` with the anon key. The RLS subqueries that read `persona_agents` (in the `dm_threads`, `dm_messages` and `a2a_tasks` policies) all filter `p.user_id = auth.uid()`, which `"Users can read own persona"` keeps allowing.

---

## 3. Target picture

```
                 ┌──────────────── aafo (Supabase, Postgres 17) ────────────────┐
cards-web ──auth─┤ auth.users  ◄── the one user id for persona AND cards         │
persona-web ─────┤ public   (persona history): 28 persona tables                 │
cards-api  ─svc──┤ cards    (cards history):   4 cards tables, owner_user_id ──► auth.users
                 │ identity (identity history): shared layer, empty until Stage 2 │
persona-api ─svc─┤ extensions.vector · storage bucket `avatars`                  │
                 │ drizzle.__{identity,persona,cards}_migrations                  │
memory ─────svc──┤ (reads persona_agents + search_personas_fts)                  │
                 └───────────────────────────────▲───────────────────────────────┘
                                                 │ npm run db:migrate (a person; rehearsed locally)
                         zynd-platform/packages/db  (Drizzle schema + migrations)

xmfj: dashboard only (developer_keys, entities, …). Cards tables are dropped 28 days after cutover.
```

---

## 4. `packages/db`: design

The package README ([`packages/db/README.md`](../../packages/db/README.md)) is the source of truth for the layout, commands, workflow and rules. This section keeps the reasoning.

### 4.1 Layout (as built)

```
packages/db/
├── lib/config.ts        # historyConfig(name, ownedSchemas): one drizzle-kit config per history
├── lib/shared.ts        # FK naming, policy builders, tsvector
├── identity/            # schema/ + migrations/ + drizzle.config.ts   → owns `identity`
├── persona/             # schema/*.ts (28 tables) + migrations/        → owns `public`
├── cards/               # schema/*.ts (4 tables) + migrations/         → owns `cards`
├── scripts/             # migrate.ts, check-drift.ts, catalog.sql, baseline-sql.ts,
│                        # lint-migrations.sh, preflight-cards.sql, projects.ts (the history registry)
├── test/supabase-stubs.sql
├── introspection/       # dated prod catalog exports
├── OWNERS.md
└── README.md
```

Scripts: `npm run <history>:generate` / `<history>:generate:custom`, `db:check`, `db:lint`, `db:migrate` (dry run unless `--yes`; `--project <history>`), `db:drift`, `db:baseline-sql`. There is no push script.

### 4.2 Why one tool with three histories

- Each history's config has `schemaFilter` = the schema it owns, so drizzle-kit never diffs, creates or drops anything in another product's schema.
- Each records progress in its own table, so persona can apply `0005` while cards is at `0002`, without either knowing.
- All three share the migrate/drift/lint scripts and one CI job, so there is still one way to change the database, and one place to look.
- Ownership is by folder (`OWNERS.md`; add a `CODEOWNERS` entry per folder once the GitHub team handles exist).

### 4.3 What lives where

| Kind of object | Where it's defined | How it gets into a migration |
|---|---|---|
| Tables, columns, defaults, PK/FK/unique/CHECK, indexes, RLS, policies, generated columns | `<history>/schema/**` | `npm run <history>:generate` |
| Extensions, schemas' grants, functions, triggers, GRANT/REVOKE, publication, backfills | hand-written SQL | `npm run <history>:generate:custom` |

To change a function or trigger, add a new custom migration with `create or replace`; never edit an old file.

### 4.4 Migrations as built

| History | File | Kind | Contents | Runs on prod? |
|---|---|---|---|---|
| identity | `0000_identity_schema` | generated + grants | `create schema identity`; usage + default privileges for `service_role` only | yes |
| persona | `0000_baseline_persona` | generated, then completed by hand (§4.8) | 28 tables + constraints, 43 indexes, 4 functions + ACLs, 1 trigger, RLS on 28 tables, 72 policies, realtime publication × 9 | **No.** Recorded with `db:baseline-sql` |
| persona | `0001_persona_drop_public_read` | generated | `drop policy "Public read persona agents"` | yes (the hotfix) |
| cards | `0000_cards_schema` | generated + custom | `create schema cards`; `service_role`-only grants and default privileges; `create extension vector with schema extensions`; `cards.skill_names()` | yes |
| cards | `0001_cards_tables` | generated | 4 tables in `cards` (+ `owner_user_id → auth.users`), indexes (HNSW, GIN), RLS, service-role policies | yes |
| cards | `0002_cards_search_functions` | custom | `cards.match_cards`, `cards.search_cards_fts` (`set search_path = cards, extensions`) | yes |

A fresh database (CI, local, a future dev project) applies identity → persona → cards.

### 4.5 Access to the `cards` and `identity` schemas

Supabase's default grants only cover `public`. The new schemas grant `usage` and default privileges to `service_role` only, and revoke function `execute` from `PUBLIC`. So anon/authenticated can't reach cards data even if a policy is wrong, which replaces the explicit revokes the single-history design needed (D7). For cards-api to query `cards` over PostgREST, a person adds `cards` to the project's API **Exposed schemas** setting (phase D).

### 4.6–4.7 Workflow and rules

See `packages/db/README.md` ("Making a schema change", "Rules").

### 4.8 How the baseline is built and proven

The complete aafo catalog is already in hand (§2.2), so the baseline can be built without a prod connection. It's proven against prod with the same catalog query.

1. **Write** `persona/schema/*.ts` for all 28 tables from the catalog: columns, defaults, constraints, 43 indexes, RLS and 72 policies.
2. **Generate:** `npm run persona:generate -- --name baseline_persona` produces `0000_baseline_persona.sql` plus a snapshot. Keep the snapshot, because it represents `schema.ts`. Move the generated SQL aside as `drizzle-generated.sql` (not committed).
3. **Replace** the SQL in `0000_baseline_persona.sql` with the full baseline:
   - Drizzle's table and index DDL.
   - The 4 functions, verbatim from the catalog, created **before** the tables whose policies call them.
   - The function ACLs.
   - The trigger.
   - The publication lines.
4. **Build scratch DB A:** stubs + `0000`. Run `scripts/catalog.sql` on A and save the output.
5. **Run the same query on prod aafo** (SQL editor, read-only) and save it to `introspection/aafo-<date>.txt`.
6. **Compare with `check-drift.ts`**, which normalizes ordering, the `realtime.messages_*` partitions and grant lines that come from default privileges. **It must match exactly.** Any difference is fixed in `schema.ts` or `0000`, then repeat from step 2.
7. **Check `schema.ts` against the baseline:** build scratch DB B from stubs + `drizzle-generated.sql` + the functions, trigger and publication; its tables, indexes and policies must equal A's.
8. **Confirm no pending changes:** `npm run persona:generate` must now report no changes.
9. **Record the baseline on prod (a person):** run the output of `npm run db:baseline-sql` once in the aafo SQL editor. It creates `drizzle.__persona_migrations` (renaming the earlier `__drizzle_migrations` if the first hotfix SQL was already run) and inserts 0000's hash and timestamp.

   The hash and timestamp format is checked against the pinned `drizzle-orm` migrator source in phase A before anyone relies on it: rows are applied only if their journal `when` is newer than the last `created_at`.

Local scratch cluster: Homebrew Postgres 18 on port 5544 (`initdb` + `pg_ctl`). The persona baseline needs nothing extra; the cards migrations need pgvector, installed with `brew install pgvector` (ask first). CI uses `pgvector/pgvector:pg17`.

### 4.9 CI: `.github/workflows/db.yml`

Triggers: `paths: packages/db/**`, on PRs to `dev` and pushes to `dev`.
1. `npm ci` in `packages/db`.
2. `npm run db:check`: snapshot/journal consistency for all three histories.
3. `npm run db:lint`: filename format, `-- owner:` header on every migration, journals match files, and no edits to already-merged migration files.
4. Postgres service `pgvector/pgvector:pg17`, then `psql -f test/supabase-stubs.sql`, then `npm run db:migrate -- --yes` **from empty** (identity → persona → cards).
5. `drizzle-kit generate` for each history must produce **no** new file, which proves each history's schema files and migrations are in sync.
6. `db:drift` against a fresh build (self-consistency of the catalog tooling).

Deploy jobs are deliberately not part of this workflow (D10).

### 4.10 Freezing the old SQL

- Add `README.md` "Frozen — schema changes go in `packages/db`" to `services/persona-api/db/`, `services/persona-api/supabase/migrations/`, `apps/persona-web/db/` and `services/cards-api/db/`.
- Remove the `db:policies` script from `apps/persona-web/package.json`.
- Update `AGENTS.md` §4 (where migrations live) and §7 (status) when `packages/db` lands.

---

## 5. Auth migration

### 5.1 Today

| Piece | Behaviour |
|---|---|
| Card login | xmfj Auth: Google, and `linkedin_oidc` for claims, via the dashboard |
| `services/cards-api/api/auth.py` | ES256 via the JWKS of **one** `SUPABASE_URL`, with an HS256 legacy fallback. **Returns only `email`**, and email is the principal |
| Ownership | `agent_profile_cards.owner_email` plus claim tokens (`claim_token_hash`) for anonymous publishes |
| `services/memory/app/supabase_auth.py` | Verifies against **one** project (`/token/exchange`, `/me/social-links`, `/oauth/complete`) |
| `apps/cards-web` | Already written against aafo (`@supabase/ssr`, Google, LinkedIn, magic link) |

### 5.2 Target

- **One identity provider, aafo, with persona's login: LinkedIn (OIDC) only (D12).**
  - **cards-web change:** drop the Google buttons (`app/auth/page.tsx`, `app/create/page.tsx`, `app/agent-card/auth-bar.tsx`), the GitHub option (`app/p/[handle]/profile-auth-actions.tsx`) and the magic-link form (`signInWithOtp`).
  - **Magic link:** returns when SMTP exists; `null` for now.
  - **Risk this creates:** xmfj card owners who signed in with **Google** must now use a LinkedIn account with the **same email**. Appendix F counts owners by provider before cutover, so we know how many are affected. Anyone whose LinkedIn email differs gets reassigned by support (one `update` on `owner_email`/`owner_user_id`) or re-claims with a claim token.
- **No copy of xmfj users.** Nothing in cards references an xmfj user id. xmfj also holds every dashboard developer account, which doesn't belong in persona. A card owner who already uses persona has an aafo user with a **different** UUID, so copying would create two users per person.
- **Ownership keeps working by email.** An owner signs in to cards.zynd.ai with the same email, which creates or reuses their aafo user, and `owner_email` matches as before. Supabase auto-links identities that share a **verified** email, so Google and LinkedIn with the same email end up as one user.
- **Linking the products:** `owner_user_id uuid → auth.users(id) on delete set null`.
  - **Backfill at cutover:** match by `lower(email)`. The SQL is in Appendix C.
  - **Going forward:** cards-api sets `owner_user_id = sub` on every aafo-authenticated publish, claim or edit.
  - `owner_email` stays the ownership authority until Stage 2 moves everything to one user id (`zynd_uid` = `auth.users.id`).

### 5.3 Token trust during the switch

Both backends accept xmfj **and** aafo tokens from D4 until 14 days after cutover.

- **cards-api:** `TRUSTED_SUPABASE_URLS=https://aafoguuvmaxymrtnfafn.supabase.co,https://xmfjvixclgqcmjmtecwv.supabase.co`.
  - **Verification:** one `PyJWKClient` per issuer, chosen by the token's unverified `iss`. The `iss` must be `<url>/auth/v1` exactly, algorithm ES256. HS256 stays only for the configured legacy secret, pinned to the project that secret belongs to.
  - **New return type:** `verify_supabase_jwt` returns a small principal `(email, sub, iss)` instead of `str`. Callers are updated, and `sub` is used only when `iss` is aafo.
- **memory:** `TRUSTED_SUPABASE_PROJECTS`, a list of `url|anon_key` pairs, with the same issuer pinning.
- **After day 14:** remove xmfj from both lists. That's config only, no code change.

### 5.4 Edge cases

| Case | Result | Handling |
|---|---|---|
| Owner signs in with the same email | owns the card | none |
| Emails differ in letter case | owns it only if the comparison is case-insensitive | `lower()` in the backfill; audit the cards-api comparisons in D4 |
| Owner signs in with a different email | not the owner (same as today) | claim token, or support reassigns (set `owner_email` / `owner_user_id`) |
| Owner already has a persona account | same aafo user, **linked automatically** | that's the goal |
| Magic-link email not verified | Supabase won't issue a session | none |
| Anonymous card with a pending claim token | still claimable (hash copied as-is) | none |

### 5.5 aafo Auth settings (a person, in dashboards)

- **OAuth apps:** none new. aafo's existing LinkedIn (OIDC) provider, the one persona uses, serves cards too (D12).
- **aafo → Authentication → URL configuration:** keep the Site URL as it is (persona). Add `https://cards.zynd.ai/**`, `https://*-zyndai.vercel.app/**` (previews) and `http://127.0.0.1:3000/**` to the redirect allow-list.
- **Email magic link / SMTP:** **not now (`null`).** When an email provider is chosen, configure custom SMTP (the built-in mailer is heavily rate-limited), enable the Email provider and bring back the magic-link form in cards-web.
- **aafo → Storage:** create a public bucket `avatars` with an INSERT/UPDATE policy for `authenticated`, limited to paths under the user's own id. Reads are public.

---

## 6. Data migration

### 6.1 Scope

| Object | Method | Notes |
|---|---|---|
| `agent_profile_cards` | `pg_dump --data-only` → `psql` | `search_tsv` is generated, so pg_dump leaves it out and aafo recomputes it. `embedding` is copied as-is (no re-embedding). `owner_user_id` stays NULL until the backfill |
| `x_accounts`, `x_conversations`, `x_mentions` | same | Load after `agent_profile_cards` (FKs) |
| `avatars` bucket | Storage API copy | same object paths |
| URLs inside card JSON | SQL `replace` | xmfj storage host → aafo storage host, in every jsonb column that contains it |

Row counts are still to be filled in from the pre-check (Appendix F).

### 6.2 Scripts: `services/cards-api/scripts/migrate_to_persona/`

The agent writes these, and **the user runs them**. They default to dry-run.
- **`copy_tables.sh SRC_URL DST_URL [--apply]`**
  1. `pg_dump "$SRC_URL" --data-only --no-owner --no-privileges -t public.agent_profile_cards -t public.x_accounts -t public.x_conversations -t public.x_mentions > cards_data.sql`. pg_dump writes explicit column lists, so the extra `owner_user_id` column doesn't matter.
  2. Retarget the dump from xmfj's `public` to aafo's `cards`: rewrite `COPY public.<table>` → `COPY cards.<table>` and `SELECT pg_catalog.setval('public.` → `'cards.` (there are no sequences today, but the script handles them), and fail if any other `public.` reference remains.
  3. With `--apply`: `psql "$DST_URL" -v ON_ERROR_STOP=1 --single-transaction` running `truncate cards.x_mentions, cards.x_conversations, cards.x_accounts, cards.agent_profile_cards;` and then `\i cards_data.sql`.
  4. Prints row counts on both sides.
- **`copy_avatars.py`**
  - List the xmfj `avatars` objects (service key), download each and upload it to aafo at the same path with the same content-type, skipping anything already there with the same size.
  - Then run a single SQL rewrite:
    `update cards.agent_profile_cards set card = replace(card::text, '<xmfj>/storage/v1/object/public/avatars/', '<aafo>/storage/v1/object/public/avatars/')::jsonb where card::text like '%<xmfj>/storage/v1/object/public/avatars/%';`
    and the same for `scrape_raw`, `user_intent` and `suggested_posts`.
  - Reports objects that are missing or failed, and URLs that still point at xmfj afterwards.
- **`verify.sql`:** run on both sides and diff (Appendix F).
- **`backfill_owner_user_id.sql`:** Appendix C.

### 6.3 Rehearsal first

There's no staging (D11), so the rehearsal happens in two places:
1. **Local:** scratch Postgres with stubs + all three histories, then `copy_tables.sh` from xmfj into it. This proves the dump loads, the generated column recomputes and the FKs hold.
2. **Prod aafo, while live (phase G):** the same scripts into the new, still-unused cards tables. Nothing reads aafo's cards tables until cutover, and the final copy re-truncates them, so the rehearsal leaves nothing behind.

---

## 7. Code changes

| File | Change | Tests |
|---|---|---|
| `services/cards-api/config.py` | **Done:** `SUPABASE_DB_SCHEMA` (default `public`; `cards` after cutover) is the Supabase client's default schema, so every `sb.table()`/`sb.rpc()` follows it. To do: `TRUSTED_SUPABASE_URLS` (list, defaults to `[SUPABASE_URL]`), `AAFO_ISSUER`, `MAINTENANCE_READONLY` (bool) | config parsing |
| `services/cards-api/api/auth.py` | Multi-issuer verification (§5.3); returns `Principal(email, sub, iss)` | a token from each issuer, an unknown issuer, a wrong `iss`, expired, HS256 legacy |
| `services/cards-api/api/onboard.py`, `api/cards.py` | Use `principal.email` for ownership as before; set `owner_user_id` on aafo-authenticated publish/claim/edit; case-insensitive owner comparison; publish de-dup (the owner's existing published card is updated; an anonymous publish with a matching `handle_github`/`handle_x` returns `{existing: true, handle}`); `archived` hidden everywhere | extend existing tests |
| `services/cards-api/main.py` | When `MAINTENANCE_READONLY` is on, POST/PATCH/DELETE return 503 `{"detail":"Cards is read-only for maintenance, back shortly"}` | middleware test |
| `services/cards-api/x/*` | The poller skips its loop while read-only | unit test |
| `services/memory/app/supabase_auth.py` | `TRUSTED_SUPABASE_PROJECTS`, issuer pinning | tests per issuer |
| `infra/api-box` env (not in git) | New variables above; at cutover, `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` switch to aafo | none |
| `apps/cards-web` | None. It already targets aafo. Vercel env is set in F | build/lint/tsc |
| persona | None besides migration `0001` | persona-web realtime smoke test after `0001` |

All code changes follow AGENTS.md §3: branch → `dev`, with tests compared against the §5 baselines (cards 2 failing, memory 9, persona 5).

---

## 8. Phases

**Progress (2026-09-29):**
- ✅ **A, B, C: done.** persona's baseline recorded on prod and `0001` applied; the anon key can no longer read `persona_agents` (checked 2026-09-28).
- ✅ **D: done on prod.** identity and cards histories applied; `cards` is in the API's exposed schemas (an anon request gets "permission denied for schema cards", as designed).
- 🟡 **E: code done, not deployed** (`0f164d6`, fixes in the verification commit after it, both re-verified 2026-09-29: cards-api 106 passed/2 known baseline failures, memory 207 passed/9 known baseline failures): cards-api and memory trust both projects, `owner_user_id` is written only once cards-api points at the `cards` schema (`WRITES_OWNER_USER_ID`), maintenance switch, one-card-per-owner publish. ⬜ **Not deployed:** set `TRUSTED_SUPABASE_URLS`, `AAFO_ISSUER` (cards-api) and `TRUSTED_SUPABASE_PROJECTS` (memory), then deploy.
- 🟡 **F: code done, U partly done** (`a7774d0`, `5adf726`, and the `exists` screen fix in the verification commit; re-verified 2026-09-29 — tsc/lint/build clean): cards-web is LinkedIn-only, avatar uploads go under the user's own folder, and a duplicate publish shows a proper screen. Of §5.5's U steps: ✅ aafo Auth redirect URLs added (`cards.zynd.ai/**`, `*-zyndai.vercel.app/**`, `127.0.0.1:3000/**` — confirmed 2026-09-28); ✅ `avatars` bucket created with correct owner-scoped INSERT/UPDATE policies (confirmed 2026-09-28, verified against aafo's Storage API directly). ⬜ **Not done:** Vercel project env vars for cards-web; opening a preview deploy to verify LinkedIn login against aafo (blocked on E's deploy above).
- 🟡 **G: scripts written and rehearsed locally (2026-10-01), not run against prod.** `services/cards-api/scripts/migrate_to_persona/` (`copy_tables.sh`, `copy_avatars.py`, `rewrite_avatar_urls.sql`, `backfill_owner_user_id.sql`, `verify.sql`, `owners_xmfj.sql`, `owners_aafo.sql`, README runbook). Rehearsed against a scratch Postgres shaped like xmfj and aafo (pgvector, generated `search_tsv` recomputes, embeddings and `public.`-looking text inside cards survive, re-runs are idempotent); `copy_avatars.py` is unit-tested against a fake Storage API. One change from §6.2: `copy_tables.sh` defaults to a **non-destructive merge** (skips a card whose id or handle already exists on aafo) because people may already be creating cards on aafo; `--replace` is the original truncate-and-load, refused if aafo already holds cards. ⬜ Still to do: a person runs them against prod (dry run first).
- ⬜ **H (cutover), I (cleanup): not started** — both depend on G's scripts existing first.
- **Full repo sanity check, 2026-09-29** (independent of the above — confirms nothing outside this plan's own scope is broken): `persona-api` 313 passed/5 known baseline failures; `cards-api` 106 passed/2 known baseline failures; `memory` 207 passed/9 known baseline failures/81 deselected; `packages/db` `db:check` clean on all 3 histories; `persona-web`/`cards-web` both `tsc`-clean and build successfully. `persona-web` has 24 pre-existing lint errors, `cards-web` has 3 — both predate this plan and don't block builds, so treat as separate cleanup, not part of A–I.

Stop after each phase, report, and wait for an OK. **A** = agent, **U** = user. Nothing touches prod unless a person runs it.

| | Phase | Who | What | Done when | Rollback |
|---|---|---|---|---|---|
| ✅ | **A. Scaffold** | A | `packages/db` package, config, stubs, scripts, README, OWNERS, CI workflow, frozen READMEs; confirm the migrator's hash/`when` semantics in the pinned version | `npm ci && npm run db:check` pass; CI green on a PR | revert the PR |
| ✅ | **B. Baseline** | A, then U | §4.8 steps 1–8 (A); U runs `catalog.sql` on prod for step 5; U runs `db:baseline-sql` output on prod | drift diff empty; `persona:generate` reports nothing; `drizzle.__persona_migrations` holds the baseline row on prod | `drop schema drizzle cascade` (tracking tables only) |
| ✅ | **C. Persona fix** | A, then U | `0001`; A rehearses it on the local scratch DB; U applies it to prod aafo (which dev.persona also uses) and smoke-tests persona-web (inbox, tasks, groups, realtime) on dev.persona, then prod | an anon `GET /rest/v1/persona_agents?select=agent_id&limit=1` returns `[]`; persona-web works | `create policy "Public read persona agents" on persona_agents for select using (true);` |
| ✅ | **D. Cards + identity schemas** | A, then U | identity `0000`, cards `0000`–`0002`; U runs `preflight-cards.sql`, then `db:migrate -- --project identity,cards --yes` on prod aafo; U adds `cards` to aafo → API settings → **Exposed schemas** | catalog shows the `cards` schema with 4 empty tables + 3 functions; an anon request with `Accept-Profile: cards` is denied | `drop schema cards cascade; drop schema identity;` (empty) + `drop table drizzle.__cards_migrations, drizzle.__identity_migrations` |
| 🟡 | **E. Code** | A, then U | §7 on a branch → `dev`; U deploys cards-api + memory with **both** issuers trusted; cards-api **still on xmfj** | tests at baseline; prod behaves as before; an aafo token is accepted by `/cards/*` auth | redeploy the previous image |
| 🟡 | **F. aafo auth + storage** | A, then U | A: cards-web goes LinkedIn-only (D12). U: §5.5 redirect URLs and `avatars` bucket; Vercel env for cards-web (aafo URL/anon key, `NEXT_PUBLIC_API_URL=https://api.zynd.ai`, `NEXT_PUBLIC_SITE_URL=https://cards.zynd.ai`); open a preview deploy | on the preview, LinkedIn login works against aafo; card pages render (data via cards-api from xmfj) | remove the redirect URLs |
| 🟡 | **G. Rehearsal** | U (A reviews output) | §6.2 all scripts into aafo | `verify.sql` matches; avatars report shows 0 missing | re-truncate the aafo cards tables |
| ⬜ | **H. Cutover** | U, A on call | runbook below | all checks pass | per step, below |
| ⬜ | **I. Cleanup** | U + A | day +14: remove xmfj from trusted issuers; dashboard P5 (remove cards UI, add 301s; the dashboard team's branch); day +14: rename xmfj cards tables `*_retired`; day +28: drop them and the xmfj `avatars` bucket. **xmfj persona copies (D13), can run any time:** U runs the activity check (Appendix F); if it's clean, U runs Appendix G part 1 (rename to `*_retired`), then part 2 (drop) 14 days later. `keyword_posts` stays | nothing in the logs uses xmfj for cards; the persona copies show no reads or writes | un-rename the tables (until the drop) |

### Phase H: cutover runbook (quiet hour, about 30–45 minutes)

None of H1–H9 have run — Phase H hasn't started (blocked on G).

| # | Step | Check | Rollback |
|---|---|---|---|
| H1 | Announce the window. Set `MAINTENANCE_READONLY=true` on cards-api and restart | POST returns 503; GET works; X poller log shows "paused" | set it back to `false` |
| H2 | `copy_tables.sh --apply` (final) | row counts equal | re-run |
| H3 | `copy_avatars.py --apply` + URL rewrite | 0 missing; 0 xmfj avatar URLs left in aafo | re-run |
| H4 | `verify.sql` on both sides | the diff shows only the expected lines (Appendix F) | stop; stay on xmfj; H1 rollback |
| H5 | `backfill_owner_user_id.sql` on aafo | reports matched vs unmatched owners | `update … set owner_user_id = null` |
| H6 | Switch cards-api `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` to aafo and set `SUPABASE_DB_SCHEMA=cards` in `infra/api-box`, restart | `/cards/search` (FTS + vector), `GET /cards/<handle>`, chat widget, X-bot dry run | switch the env back to xmfj (and `SUPABASE_DB_SCHEMA=public`), restart; xmfj is unchanged because it was read-only |
| H7 | Point `cards.zynd.ai` DNS at the Vercel project | login, claim (token and LinkedIn), create with avatar upload, edit, publish | remove the DNS record |
| H8 | `MAINTENANCE_READONLY=false` | a new publish lands in aafo | **after this, rolling back loses writes made on aafo**: decide within the first hour, then copy those rows back to xmfj manually |
| H9 | Watch for 24 hours: cards-api errors, auth failures, 401s by issuer | none | none |

---

## 9. Verification checklist

- **Baseline:** `catalog(prod aafo) == catalog(stubs + 0000)` after normalization.
- **Schema/migrations in sync:** `<history>:generate` produces nothing for any history after every merge (CI checks this).
- **Persona fix:** anon REST read of `persona_agents` returns `[]`; persona-web inbox, tasks and group realtime still update.
- **Cards schema:** as anon, the `agent_profile_cards` REST request is denied and RPC `match_cards` is denied; as service_role, both work.
- **Data:** equal counts per table and per `status`; equal `md5` over `id || md5(card::text)` (before the URL rewrite); `count(embedding)` equal; top 10 of the same `search_cards_fts('engineer')` and the same `match_cards(<fixed vector>)` identical on both sides.
- **Auth:** a card owner signs in to aafo and can edit their card; a persona user with the same email ends up as the **same** `auth.users` row as `owner_user_id`.

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| The baseline differs subtly from prod, so the next generated migration fights the real schema | §4.8 exact catalog comparison; `db:drift` before every prod migrate |
| Someone changes aafo in the SQL editor | README rule; drift check in the release steps; frozen old folders |
| A `drizzle-kit` upgrade changes the snapshot or migration-table format | exact pins; `baseline-sql.ts` tied to the pinned version; upgrade only in a dedicated PR |
| Drizzle rename prompts turn into drop + add | answer the prompts deliberately; review generated SQL in PRs |
| Dropping `persona_agents` public read breaks an unknown external reader | own migration `0001`, one-line rollback |
| No staging: a bad migration hits dev.persona **and** prod at once | local rehearsal with stubs (CI does the same from empty on every PR); expand-only migrations (D11); drift check before every apply; rollback SQL written before applying |
| Card owners who used Google on xmfj can't match their LinkedIn email | Appendix F counts them first; support reassigns or they re-claim (§5.2) |
| memory relies on `persona_agents` columns | `OWNERS.md` lists memory as a consumer, and memory's owner reviews those changes |
| Owner email differs between providers | claim tokens and support; `owner_user_id` makes reassignment one update |
| Magic links hit the mail rate limit | not launched until an SMTP provider exists (D12) |
| `vector` moves from `public` (xmfj) to `extensions` (aafo) and breaks function resolution | functions get `set search_path = public, extensions`; checked in D and G |
| xmfj persona copies are still written to by something | row-count pre-check (Appendix F) before I; the dashboard team decides their fate |

---

## 11. Effort (rough)

| Phase | Agent | User |
|---|---|---|
| A | about half a day | review the PR |
| B | about 1 day (28 tables by hand + diff loop) | 2 SQL-editor runs + Appendix D |
| C–D | about 2 hours | apply to prod after local rehearsal |
| E | about 1 day with tests | deploy |
| F | none | about 1 hour of dashboard settings |
| G–H | on call | about 1 hour + 45-minute window |
| I | about 1 hour | settings + dashboard PR merge |

---

## 12. Questions: answered 2026-09-26

| # | Question | Answer | Where it landed |
|---|---|---|---|
| 1 | Staging? | None. dev.persona uses the prod database and is only for testing logic | D11, §6.3, phases C/D |
| 2 | OAuth apps? | Use persona's login | D12, §5.2, §5.5, phase F |
| 3 | `keyword_posts`? | Maybe memory, but if nothing uses it, leave it as is | D13 (left alone; no code references found) |
| 4 | xmfj persona copies? | Remove them if nothing uses them | D13, Appendix F activity check, Appendix G |
| 5 | Who runs prod migrations / SMTP? | Anyone on the team. Magic link / SMTP is `null` for now, added once there's an email provider | D10, D12 |
| — | Drizzle? | Confirmed | D1 |

**Still open:** the duplicate cards (`0xsy3` / `0xsy3-pobf`, `chandan-kumar` / `chandan867`) need settling before phase G.

---

## Appendix A: catalog query

The query lives in [`packages/db/scripts/catalog.sql`](../../packages/db/scripts/catalog.sql). It is read-only, returns one text cell (so the SQL editor's 100-row limit doesn't apply), covers every schema the migrations own (`public`, `cards`, `identity`) with schema-qualified names, and its first line identifies the project (`developer_keys=true` means xmfj). The 2026-09-26 exports used an earlier, `public`-only version; re-export with the current file before running `db:drift` against prod.

## Appendix B: aafo policy inventory (72)

Per table: *svc* is the redundant `"Service role full access on …"` (`to public using (auth.role()='service_role')`); *own* is `auth.uid() = user_id`.

| Table | Policies |
|---|---|
| a2a_tasks | svc; participants read (via `dm_threads`/`persona_agents` subquery) |
| agent_tasks | svc; participants read; participants update |
| api_tokens | svc; own read/insert/update/delete |
| brief_todos | svc (with check); own read/update/delete; group members read (`is_persona_group_member`) |
| callback_results | svc; owner read; owner marks delivered (update, with check) |
| chat_messages | svc; own read |
| dm_messages | svc; read in non-blocked threads; send in accepted threads (insert with check) |
| dm_threads | svc; read own; start (insert with check); participants update |
| enriched_companies, enriched_contacts | svc (with check); own CRUD (all, with check) |
| github_profiles, linkedin_profiles, twitter_profiles, telegram_links | svc; own read; own delete |
| outbound_callbacks | svc; owner read |
| pending_approvals | svc; own read; own update |
| persona_agents | svc; **public read `true`** (dropped in 0001); own read; own update |
| persona_group_audit_events | svc (with check); affected user reads; managers read (`is_persona_group_manager`) |
| persona_group_constraints, _members, _messages | svc (with check); members read (`is_persona_group_member(group_id)`) |
| persona_groups | svc (with check); members read (`is_persona_group_member(id)`) |
| published_pages | svc; public read where `visibility='public'`; own CRUD |
| suggested_contact_runs | svc (with check); own read |
| suggested_contacts | svc (with check); own CRUD |
| telegram_chat_history | svc; own read |
| oauth_pending_state, persona_group_invitations | none (RLS on, service role only) |

The verbatim `using` / `with check` text comes from the catalog output saved in `packages/db/introspection/` during phase B.

## Appendix C: migration SQL and the owner backfill

The migration SQL is in the repo and is the source of truth: `packages/db/persona/migrations/0001_persona_drop_public_read.sql`, `packages/db/cards/migrations/0000_cards_schema.sql`, `0001_cards_tables.sql`, `0002_cards_search_functions.sql`, and `packages/db/identity/migrations/0000_identity_schema.sql`.

```sql
-- backfill_owner_user_id.sql  (run once at cutover, H5; idempotent)
with m as (
  update cards.agent_profile_cards c
     set owner_user_id = u.id
    from auth.users u
   where c.owner_user_id is null
     and c.owner_email is not null
     and lower(u.email) = lower(c.owner_email)
  returning c.id
)
select (select count(*) from m) as linked,
       (select count(*) from cards.agent_profile_cards where owner_email is not null and owner_user_id is null) as unmatched;
```

## Appendix D: recording persona's baseline

`cd packages/db && npm run db:baseline-sql` prints the SQL to run once in the aafo SQL editor. It records persona's `0000` in `drizzle.__persona_migrations` without running it, and first renames `drizzle.__drizzle_migrations` if the earlier hotfix SQL already created it.

## Appendix E: `test/supabase-stubs.sql` (CI and scratch DBs only)

- **Roles:** `anon`, `authenticated` (nologin) and `service_role` (nologin, `bypassrls`), each granted usage on `public`.
- **Schema `auth`:**
  - `auth.users(id uuid primary key, email text)`.
  - `auth.uid()`, `auth.role()` and `auth.jwt()` as `language sql stable` functions reading `current_setting('request.jwt.claims', true)`, same as Supabase.
- **Schema `extensions`:** `alter database … set search_path = "$user", public, extensions`.
- **Publication:** `create publication supabase_realtime` (empty).
- **Default privileges:** `alter default privileges in schema public grant all on tables to anon, authenticated, service_role`, and the same for functions and sequences, to mirror Supabase's defaults. Without this, grant lines would differ from prod in the drift diff.

## Appendix F: pre-check and verify queries (read-only)

**xmfj, before G:**
```sql
select 'cards: ' || status as what, count(*) from agent_profile_cards group by status
union all select 'x_accounts', count(*) from x_accounts
union all select 'x_mentions', count(*) from x_mentions
union all select 'x_conversations', count(*) from x_conversations
union all select 'distinct owners (non-archived)', count(distinct lower(owner_email)) from agent_profile_cards where status <> 'archived'
union all select 'owners differing only by case', count(*) from (select lower(owner_email) from agent_profile_cards where owner_email is not null group by 1 having count(distinct owner_email) > 1) t
union all select 'avatars objects', count(*) from storage.objects where bucket_id = 'avatars'
union all select 'xmfj copy: persona_agents', count(*) from persona_agents
union all select 'xmfj copy: dm_threads', count(*) from dm_threads
union all select 'keyword_posts', count(*) from keyword_posts;
```

**Both sides, at G and H4 (`verify.sql`):**
```sql
select 'rows ' || status, count(*)::text from agent_profile_cards group by status
union all select 'x_accounts', count(*)::text from x_accounts
union all select 'x_conversations', count(*)::text from x_conversations
union all select 'x_mentions', count(*)::text from x_mentions
union all select 'embeddings', count(embedding)::text from agent_profile_cards
union all select 'claim tokens', count(claim_token_hash)::text from agent_profile_cards
union all select 'ids+card md5', md5(string_agg(id || md5(card::text), ',' order by id)) from agent_profile_cards
union all select 'fts top10', string_agg(id, ',') from (select id from search_cards_fts('engineer', 10)) t;
-- On aafo the tables and function are in the cards schema: run `set search_path = cards, public, extensions;` first.
```
Expected difference after H3: the `ids+card md5` line changes, because avatar URLs are rewritten. Run it **before** H3 for the equality check and after H3 only for the URL report.

**xmfj: card owners by login provider** (sizes the Google → LinkedIn risk in D12):
```sql
select coalesce(i.provider, '(no xmfj user)') as provider, count(distinct lower(c.owner_email)) as owners
from agent_profile_cards c
left join auth.users u on lower(u.email) = lower(c.owner_email)
left join auth.identities i on i.user_id = u.id
where c.owner_email is not null and c.status <> 'archived'
group by 1 order by 2 desc;
```

**xmfj: are the persona copies used?** (D13). Run it now and again 7 days later. If `n_tup_ins/upd/del`, `seq_scan` and `idx_scan` haven't moved, and `pg_stat_statements` shows no queries against these tables, nothing uses them.
```sql
select relname, n_live_tup, n_tup_ins, n_tup_upd, n_tup_del, seq_scan, idx_scan, last_autoanalyze
from pg_stat_user_tables
where schemaname = 'public' and relname = any (array[
  'a2a_tasks','agent_tasks','api_tokens','brief_todos','callback_results','chat_messages','dm_messages','dm_threads',
  'enriched_companies','enriched_contacts','github_profiles','linkedin_profiles','oauth_pending_state','outbound_callbacks',
  'pending_approvals','persona_agents','persona_group_audit_events','persona_group_constraints','persona_group_invitations',
  'persona_group_members','persona_group_messages','persona_groups','published_pages','suggested_contact_runs',
  'suggested_contacts','telegram_chat_history','telegram_links','twitter_profiles'])
order by relname;

select calls, left(query, 120) as query
from extensions.pg_stat_statements
where query ~* '(persona_agents|dm_threads|dm_messages|api_tokens|brief_todos|persona_group|chat_messages|telegram_|enriched_|suggested_contact|published_pages|outbound_callbacks|callback_results|pending_approvals|a2a_tasks|agent_tasks|oauth_pending_state|linkedin_profiles|twitter_profiles|github_profiles)'
order by calls desc limit 50;
```

## Appendix G: removing xmfj's persona copies (D13)

Run this **on xmfj only**. Double-check the project before running it, because the same table names exist in aafo, where they are live. Only run it after the activity check above comes back clean twice. None of the dashboard tables references these tables, so `cascade` only reaches their own policies, indexes, FKs and trigger.

**Part 1: rename (reversible):**
```sql
-- guard: abort unless this is xmfj
do $$ begin
  if to_regclass('public.developer_keys') is null then
    raise exception 'not xmfj: developer_keys missing, refusing to run';
  end if;
end $$;

do $$
declare t text;
begin
  foreach t in array array[
    'a2a_tasks','agent_tasks','api_tokens','brief_todos','callback_results','chat_messages','dm_messages','dm_threads',
    'enriched_companies','enriched_contacts','github_profiles','linkedin_profiles','oauth_pending_state','outbound_callbacks',
    'pending_approvals','persona_agents','persona_group_audit_events','persona_group_constraints','persona_group_invitations',
    'persona_group_members','persona_group_messages','persona_groups','published_pages','suggested_contact_runs',
    'suggested_contacts','telegram_chat_history','telegram_links','twitter_profiles']
  loop
    execute format('alter table public.%I rename to %I', t, t || '_retired');
  end loop;
end $$;
```
*Rollback:* the same loop, renaming `t || '_retired'` back to `t`.

**Part 2: drop (14 days after part 1, if nothing broke):**
```sql
do $$ begin
  if to_regclass('public.developer_keys') is null then
    raise exception 'not xmfj: developer_keys missing, refusing to run';
  end if;
end $$;

-- explicit list, so it can't reach the cards tables, which phase I also renames *_retired
do $$
declare t text;
begin
  foreach t in array array[
    'a2a_tasks','agent_tasks','api_tokens','brief_todos','callback_results','chat_messages','dm_messages','dm_threads',
    'enriched_companies','enriched_contacts','github_profiles','linkedin_profiles','oauth_pending_state','outbound_callbacks',
    'pending_approvals','persona_agents','persona_group_audit_events','persona_group_constraints','persona_group_invitations',
    'persona_group_members','persona_group_messages','persona_groups','published_pages','suggested_contact_runs',
    'suggested_contacts','telegram_chat_history','telegram_links','twitter_profiles']
  loop
    execute format('drop table if exists public.%I cascade', t || '_retired');
  end loop;
end $$;

drop function if exists public.is_persona_group_member(uuid);
drop function if exists public.is_persona_group_manager(uuid);
drop function if exists public.persona_agents_search_vector_update();
drop function if exists public.search_personas_fts(text, integer);
```
`keyword_posts` is left as it is (D13). The xmfj cards tables are handled separately, in phase I.
