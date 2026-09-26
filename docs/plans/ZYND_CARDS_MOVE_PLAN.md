# Cards move: dashboard → `apps/cards-web` in zyndai/platform, xmfj → persona DB

| | |
|---|---|
| **Status** | Ready to start once the monorepo lands · 2026-09-25 |
| **Depends on** | `ZYND_MONOREPO_PLAN.md` M1–M4 done — `apps/cards-web` and `packages/db` live inside `zyndai/platform`, not in new standalone repos |
| **Goal** | Cards gets its own frontend, `apps/cards-web` in the monorepo (**cards.zynd.ai**). Its data and login move from the dashboard Supabase project (**xmfj…**) to the persona project (**aafo…**). Cards and persona then share one database with **one migration history**. |
| **Paused** | Stage 2 (Zynd Account, `ZYND_STAGE2_PLAN.md`) waits until this is done |
| **Background** | `ZYND_PLATFORM_ARCHITECTURE.md`, `ZYND_PLATFORM_LLD.md` §4.3 and §4.8 |
| **Superseded in part (2026-09-26)** | §3, P1, P3 and P4 are replaced by `ZYND_DB_UNIFY_PLAN.md` (Drizzle instead of the Supabase CLI for `packages/db`, plus the auth approach). P0, P2 and P5 still apply |

---

## 1. Decisions (final, don't re-ask)

- **Frontend:** `apps/cards-web` (Next.js) inside `zyndai/platform`, deployed on Vercel at **cards.zynd.ai**.
- **Backend:** `services/cards-api` (FastAPI) — the monorepo path for what was `zynd-cards` — stays at `api.zynd.ai`.
- **Data and login:** cards moves to the persona Supabase project (aafo). New app login is Google, LinkedIn and email magic link.
- **Old zynd.ai URLs** (`/p/*`, `/create`, `/directory`, `/find`, `/search`, `/tag/*`, `/profile/*`, `/agent-card`, `/for-ai`) 301-redirect to cards.zynd.ai.
- **The zynd.ai registry keeps listing cards**, read-only through the public cards API, with canonical URLs on cards.zynd.ai.
- **One migration history for the shared DB:** **`packages/db`** in the monorepo owns the aafo schema (§3) — replacing the earlier idea of a separate `zynd-db` repo consumed as a git submodule. Every product in the monorepo (agent-persona → `services/persona-api`, cards → `services/cards-api`/`apps/cards-web`) shares that one folder directly, so there's no submodule pin to fall behind.

## 2. Facts (verified 2026-09-25)

**Cards UI in `dashboard/src` (all of this moves):**
- Pages: `app/(site)/create`, `app/(site)/p/[handle]/**` (19 files: page, edit, data.json, dossier, resume-pdf, share-controls, claim actions, …), `profile/[id]`, `directory`, `find`, `search`, `tag/[skill]`, `for-ai`, and `app/agent-card/**`
- Shared code: `lib/cards.ts`, `lib/memory.ts`, `lib/memory-facts.ts`, `components/memory/*`, `hooks/useMyCard.ts`, `components/ProfileChatWidget.tsx` + `app/api/chat/profile/route.ts`
- Card entries in `app/sitemap.ts`, `llms.txt`, `llms-full.txt` and `api/indexnow`
- Claim-token support is on dashboard branch `fix/card-claim-token` (not merged). Include it.

**Stays in the dashboard, read-only:** `app/api/registry/entities/**` and `app/(site)/registry/layout.tsx` list cards via the cards API (`cardCanonicalUrl`).

**Cards data in xmfj:**
- Tables: `agent_profile_cards`, `x_accounts`, `x_mentions`, `x_conversations`
- Functions: `skill_names`, `match_cards`, `search_cards_fts`
- A `vector(1536)` column with an HNSW index, a GIN tsvector index, and RLS policies
- Storage bucket **`avatars`**. Card JSON stores avatar URLs on the xmfj storage host.

**Prod schema ≠ repo SQL.** `owner_email` is written by the code but created in no `zynd-cards/db/*.sql` file. The prod dump is the source of truth.

**Login today:**
- The dashboard uses xmfj login (Google, plus `linkedin_oidc` for claims). Card ownership is `owner_email`, so ownership survives a change of login provider as long as the email matches.
- zynd-cards verifies tokens against ONE project (its `SUPABASE_URL`).
- memory-layer's `/token/exchange` and `/me/social-links` verify against ONE project, and the dashboard's claim flow sends them xmfj tokens.

**Persona has no migration tracking.** SQL sits in `backend/db/patch_*.sql` (30 files), `backend/supabase/migrations/` (3 files, CLI format, no config) and `db/migrations/000N_*` (5 folders). All three were used in the last month, and nothing records which files were applied to the live DB.

**Cleanup already done:** 30 duplicate cards were archived (`status='archived'`), and 6 kept cards moved to their clean handles. Still open: Sahil's two owned cards (`0xsy3` / `0xsy3-pobf`), and whether `chandan-kumar` / `chandan867` are the same person.

## 3. Migration strategy for the shared DB (`packages/db`)

```
packages/db/
├── supabase/
│   ├── config.toml                  # project_id = aafo…
│   └── migrations/
│       ├── 20260925000000_baseline_persona.sql   # schema dump of aafo as it is today
│       ├── 20260926000000_cards_tables.sql       # agent_profile_cards, x_* + functions, indexes, RLS
│       └── <timestamp>_<owner>_<change>.sql      # every future change, from any product
├── OWNERS.md        # table → owning product (persona | cards | shared)
├── scripts/check_drift.sh   # compare prod schema vs migrations (read-only)
└── README.md        # how to add a migration; who applies it; staging first
```

**Rules**
- **One place.** Every schema change for the aafo DB is a migration in `packages/db`, whichever product needs it. No changes through the SQL editor on prod unless they're committed as a migration first.
- **Tracked.** The Supabase CLI records applied versions in `supabase_migrations.schema_migrations`. The baseline is marked as already applied (`supabase migration repair --status applied <version>`) and is never re-run on prod.
- **Consumers.** Every product already lives in the same monorepo as `packages/db`, so there's no submodule to pin or fall behind — `services/persona-api` and `services/cards-api`/`apps/cards-web` read migrations straight from `packages/db` at whatever commit the monorepo is on. A `packages/db` CI job checks migration filename format and the `-- owner:` header on every new file, in place of the old "CI fails if the submodule is behind" check.
- **Ownership.** Each migration starts with `-- owner: persona|cards|shared`. Product folders never create SQL files of their own.
- **Apply path.** Staging first, then prod. `supabase db push` is run by a person (later by CI with manual approval). Before every prod push, `check_drift.sh` must show no drift.
- **Freezing the old SQL.** `services/persona-api/db`, `services/persona-api/supabase/migrations`, `apps/persona-web/db` and `services/cards-api/db` get a README saying "frozen — see packages/db", and nothing new is added there.
- **Writes.** `apps/cards-web` never writes tables directly. Everything goes through the cards API, except Storage uploads to `avatars` and Supabase Auth. That keeps one writer per table.

## 4. What only a human can do

| # | Where | Action |
|---|---|---|
| H1 | GitHub | None — no new repos. `apps/cards-web` and `packages/db` are folders inside `zyndai/platform`, created by the monorepo plan's M2 |
| H2 | aafo → Database → Extensions | Enable `vector` (and confirm `pg_trgm`/`citext` if the dump needs them) |
| H3 | aafo → Storage | Create a public bucket `avatars`, with an upload policy restricted to authenticated users |
| H4 | aafo → Auth | Enable Google (+ LinkedIn, email). Add `https://cards.zynd.ai/**` to the redirect URLs |
| H5 | Vercel + DNS | New Vercel project pointed at `zyndai/platform`, **Root Directory = `apps/cards-web`**, with an "Ignored Build Step" so it skips builds when that path (and `packages/contracts`) is unchanged; `cards.zynd.ai` points to it. A private org repo needs Vercel Pro/Team to connect |
| H6 | SQL editor (read-only) | Run the dump/pre-check queries the agent gives you and paste back the output |
| H7 | Pending Stage 1 | Already done in monorepo M0.3/M0.5 — the memory-layer PR `fix/bridge-contract-and-uid` is merged and deployed, and cards `main` is redeployed, before the monorepo freeze |
| H8 | Supabase CLI | `npx supabase login` on your machine; link `packages/db` (inside your `zyndai/platform` checkout) to aafo (staging project too, if you have one) |

## 5. Phases

Stop after each phase, report, and wait for an OK.

**P0: Prep code (no user-visible change).** Each item is a flag or additive.
- **`services/cards-api/api/auth.py`:** trust tokens from a list of Supabase projects (`TRUSTED_SUPABASE_URLS`). One JWKS client per issuer, `iss` pinned, ES256. The legacy HS256 path stays only for the configured legacy secret. The principal is still the verified email.
- **`services/memory/app/supabase_auth.py`:** the same multi-project support (`TRUSTED_SUPABASE_PROJECTS`: URL + anon key pairs) for `/token/exchange`, `/me/social-links` and `/oauth/complete`.
- **cards publish de-dup:**
  - A signed-in owner who already has a published card: update it instead of creating another.
  - An anonymous publish where a published card has the same `handle_github`/`handle_x`: return `{existing: true, handle}`, so the UI offers "claim".
  - `archived` stays hidden everywhere.
- **cards `MAINTENANCE_READONLY` flag:** POST/PATCH/DELETE return 503 with a message, and the X-bot poller pauses.

**P1: `packages/db`** — a branch off the monorepo's `dev`, not a new repo.
- **Baseline:** give me read-only commands to dump the aafo schema (`pg_dump --schema-only --no-owner` via the pooler, or `supabase db dump`). Create `…_baseline_persona.sql` from my output, plus the `migration repair` command.
- **Cards tables:** give me read-only dump commands for the 4 tables, 3 functions and policies from **xmfj** prod. Write `…_cards_tables.sql`: idempotent, functions before tables, `create extension if not exists vector`, and include `owner_email` and `claim_token_hash`.
- **Preflight SQL for aafo:** name clashes, extension availability, row counts.
- Also: `OWNERS.md`, `README.md`, `check_drift.sh`.
- Add the "frozen" READMEs to the old SQL folders (§3). No submodule wiring — `packages/db` is already in the same checkout as everything that reads it.

**P2: `apps/cards-web`** — a folder in the monorepo, not a new repo.
- Next.js, same major versions as the dashboard. Port every file in §2 except the registry.
- **Auth:** the aafo project via `@supabase/ssr` (cookie client, `/auth/callback`, Google, LinkedIn and email login).
- Claim tokens (from `fix/card-claim-token`).
- Avatar uploads to the aafo `avatars` bucket.
- **Env:** `NEXT_PUBLIC_SUPABASE_URL`/`ANON_KEY` (aafo), `NEXT_PUBLIC_CARDS_API_URL`, `NEXT_PUBLIC_MEMORY_API_URL`, `NEXT_PUBLIC_SITE_URL=https://cards.zynd.ai`.
- Sitemap, llms.txt and indexnow for `/p/*`, with canonical URLs on cards.zynd.ai.
- Build, lint and typecheck must pass. Write a README with the Vercel env list.

**P3: Migration scripts** (`services/cards-api/scripts/migrate_to_persona/`, dry-run by default).
- **`copy_tables.sh`:** `pg_dump --data-only` of the 4 tables from xmfj, restored into aafo. Verify row counts and id checksums.
- **`copy_avatars.py`:** copy xmfj `avatars` objects to aafo `avatars`, then rewrite the avatar URL fields in card JSON from the xmfj host to the aafo host. Report missing objects.
- **`verify.sql`:** counts per status, unique handles, embeddings present, a sample `match_cards`.

**P4: Cutover runbook** (`docs/cards/CUTOVER.md`). You run it; the agent guides.
1. Deploy P0 with trusted projects = [xmfj, aafo].
2. Set `MAINTENANCE_READONLY=true`, then do the final copy of tables and avatars, then run verify.
3. Switch cards' `SUPABASE_URL`/`SERVICE_KEY` to aafo via `infra/api-box`, restart, and verify reads, search and chat.
4. Launch cards.zynd.ai and smoke-test login, claim, edit and publish.
5. Set `MAINTENANCE_READONLY=false`.
6. Keep the xmfj tables untouched for 14 days as the rollback, then drop them via a dashboard-side cleanup.

Every step needs a rollback line.

**P5: Dashboard cleanup** (only after P4 is live; dashboard feature branch).
- Remove the cards UI files and add the 301s in `next.config.ts`.
- The registry keeps reading the cards API, with canonical URLs on cards.zynd.ai.
- Remove the card links from `Navbar`/`sidebar` and the card intent in `auth/callback`.
- Typecheck and lint must be clean.

## 6. Working rules

- **Before touching anything:** `git -C <monorepo checkout> pull --ff-only`, then branch off `dev`.
- **Push policy:**
  - `services/cards-api`, `packages/db`, `apps/cards-web` → a feature branch → `dev`. `main` only by a PR that you merge (the monorepo's protected-`main` policy, `ZYND_MONOREPO_PLAN.md` D5/M3.5).
  - `services/memory` changes (P0's `supabase_auth.py`) → same: feature branch → `dev`, PR to `main`.
  - dashboard (P5) → feature branch only, you merge.
- **Tooling:** no Docker and no `gh`. Use `uv venv --python 3.12` venvs in the scratchpad. Node 26. Supabase CLI via `npx supabase`.
- **Never run anything against prod yourself:** no SQL, dumps, storage copies or `db push`. Give the user commands, and wait for their output.
- **Ask before:** deploys, server env changes, DNS/Vercel, deleting data.
- **Tests:** run before and after each phase, and report only new failures. Baselines (see `ZYND_MONOREPO_PLAN.md` Appendix A4): cards 2 failed (`test_x_bot`, 89 passed), memory 9 failed (203 passed, 81 deselected), persona backend 5 failed (313 passed).
- **After each phase, report:** files changed, tests before and after, commits/branches pushed, and the exact commands, SQL and env changes the user must run, in order.
