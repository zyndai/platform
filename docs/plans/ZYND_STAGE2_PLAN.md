# Zynd Platform: Stage 2 implementation plan

| | |
|---|---|
| **Document** | Implementation plan for Stage 2 ("Next"): sub-stages 2.0, 2A, 2B, 2C, 2D |
| **Source of truth** | [ARCHITECTURE](./ZYND_PLATFORM_ARCHITECTURE.md) (ADRs 1–14, §9) · [HLD](./ZYND_PLATFORM_HLD.md) (§3, §5, §6, §8) · [LLD](./ZYND_PLATFORM_LLD.md) (§4, §7, §9.2, §10) |
| **Written** | 2026-09-25, from the repos as fetched that day |
| **Rule** | After each sub-stage: stop, report, wait for an OK. Update the LLD status table when a sub-stage finishes |

Where this plan departs from the LLD, the change is marked **Deviation** and gives the reason.

---

## 0. Preconditions: checked 2026-09-25

| # | Precondition | Result | Evidence |
|---|---|---|---|
| 1 | Zynd Account JWKS serves an EC (ES256) key | **Pass** | `aafoguuvmaxymrtnfafn.supabase.co/auth/v1/.well-known/jwks.json` → one key: `kty=EC, crv=P-256, alg=ES256, kid=adc7ada2…`. No HS256 key is listed |
| 2a | Google, LinkedIn OIDC and email enabled; confirm email on | **Pass** | `/auth/v1/settings`: `google=true`, `linkedin_oidc=true`, `email=true`, `mailer_autoconfirm=false` (so confirm email is on), `github=false`, `anonymous_users=false` |
| 2b | Custom SMTP, manual identity linking, redirect URLs | **Can't check from outside.** Needs your confirmation | The public settings endpoint doesn't expose these. Required redirect URLs: `https://persona.zynd.ai/**`, `https://dev.persona.zynd.ai/**`, `https://cards.zynd.ai/**`, `http://localhost:3000/**`, `http://localhost:3001/**` |
| 3 | You've given me the prod Supabase project that zynd-cards and memory-layer use | **Missing** | The local `.env` files don't show it. I need `SUPABASE_URL` for both services, plus which project `SUPABASE_JWT_SECRET` belongs to in cards. This decides how dashboard (xmfj) tokens reach cards today, and which project memory's `/token/exchange` and Claude's Supabase-direct flow verify against |
| 4 | memory-layer Stage 1 PR merged | **Waived** (you closed the PR, 2026-09-25) | `origin/main` (`4bcefdf`) still has no `/me/whoami` or `/me/findability/declare-batch`, and zynd-bridge calls both (its contract test asserts them). They move into B1 (§5.1), ported from `e08cd2d`. The path-id self check is superseded by the B1 resolver |

**Found 2026-09-25:** the dashboard project (xmfj) also signs with **ES256** now (kid `ac0499da…`). If cards' `SUPABASE_URL` points at aafo, cards fetches aafo's JWKS, misses xmfj's `kid`, and its HS256 fallback can't verify an ES256 token. **Every signed-in dashboard publish would then count as anonymous**, and claims would fail. That's a possible source of the 30 duplicates. `zynd_env_check.py` (run on the api box) answers this without printing secrets.

**Per your rule, I don't start 2.0 until all four pass.** How each one gates the sub-stages, in case you want to relax the rule:

| Sub-stage | Needs |
|---|---|
| 2.0 (cards + dashboard) | #3, to know which tokens cards accepts as "signed in" today |
| 2A (local repo, nothing deployed) | none |
| 2B | #1, #2, #3, #4 |
| 2C, 2D | everything above, plus 2B deployed |

---

## 1. Repo baseline (fetched 2026-09-25)

| Repo | Local branch | `origin/main` | `origin/dev` vs main | Base for Stage 2 work |
|---|---|---|---|---|
| agent-persona | `fix/route-auth-guards` | `b7aada4` | dev is **1 ahead** (`c6e2948`, the Stage 1 guards) | `origin/dev` |
| zynd-cards | `main` | `88bd60d` (Stage 1) | no dev | `main` |
| memory-layer | `fix/bridge-contract-and-uid` (`e08cd2d`, PR closed) | `4bcefdf` | dev is **29 behind** main (stale; don't use it) | `main` |
| zynd-bridge | `main` | `7f1acd2` (Stage 1 contract test) | no dev | `main` |
| dashboard | `fix/card-claim-token` (`b9fd331`, unmerged) | `9907ce7` | dev is **200 behind** main (stale) | 2.0 stacks on `fix/card-claim-token` |
| zynd-account | new | — | — | local `main` |

**Local tooling (no Docker, no gh):** `uv 0.12`, Node 26, `pnpm`, Homebrew **Postgres 18** (`citext` and `pgcrypto` available, **no pgvector**), **no Redis**. The system Python is 3.9, so every venv is made with uv on Python 3.12, matching the Dockerfiles.

---

## 2. Procedure for every sub-stage

1. For each repo I'll touch: `git status` → `git pull --ff-only` → compare `origin/dev` with `origin/main` → create the branch listed in the sub-stage.
2. Build a uv venv in the scratchpad and record the **before** test run:
   ```bash
   SP=<scratchpad>
   uv venv $SP/venv-cards   --python 3.12 && VIRTUAL_ENV=$SP/venv-cards   uv pip install -r zynd-cards/requirements.txt pytest pytest-asyncio
   uv venv $SP/venv-persona --python 3.12 && VIRTUAL_ENV=$SP/venv-persona uv pip install -r agent-persona/backend/requirements.txt pytest pytest-asyncio
   uv venv $SP/venv-memory  --python 3.12 && VIRTUAL_ENV=$SP/venv-memory  uv pip install -r memory-layer/pyproject.toml --group dev
   (cd zynd-cards && $SP/venv-cards/bin/pytest -q)                 # baseline: 2 fail (x_bot)
   (cd agent-persona/backend && $SP/venv-persona/bin/pytest -q)    # baseline: 5 fail (MEMORY_LAYER_JWT_SECRET)
   (cd memory-layer && $SP/venv-memory/bin/pytest -q)              # baseline: 9 fail (need Postgres + pgvector + Redis)
   (cd zynd-bridge && npm ci && npm test)
   ```
3. Implement, with unit tests for every new branch of logic.
4. Record the **after** run. Report only failures that are new relative to the baseline.
5. Commit with the `Co-Authored-By` trailer and push according to policy:

   | Repo | Push to |
   |---|---|
   | zynd-cards, zynd-bridge | `main` |
   | memory-layer | the feature branch; I give you the PR URL (main is PR-protected) |
   | agent-persona | merge into `dev` and push `dev` (auto-deploys dev.persona.zynd.ai). Never main |
   | dashboard | the feature branch only |
   | zynd-account | local commits only, until you create the GitHub repo |

6. Report: changes per repo, tests before/after, the SQL/env/deploy steps you must run (in order), commits and branches, and what's next. Update the LLD status table.
7. Things I always ask about first: prod SQL, prod deploys, secret rotation, creating GitHub repos, publishing packages, deleting data. SQL comes to you as files plus read-only pre-checks; I never run it against prod.

---

## 3. Sub-stage 2.0: stop duplicate cards

**Goal:** one published card per person. Re-publishing updates the existing card; anonymous re-publishing of a known GitHub/X profile points at the existing card; archived cards are invisible everywhere.

### 3.1 Behavior matrix for `POST /onboard/{job_id}/publish`

| Caller | Owns a published card? | Published card with the same `handle_github` / `handle_x` (case-insensitive)? | Result |
|---|---|---|---|
| Signed in | yes | (not checked) | **Update the owned card in place.** Response: the card plus `"updated": true` |
| Signed in | no | yes | **No write.** Return that card plus `"existing": true, "owned": <bool>`. See decision D1 |
| Signed in | no | no | Insert, as today |
| Anonymous | — | yes | **No write, no claim token.** Return that card plus `"existing": true, "owned": <bool>` |
| Anonymous | — | no | Insert plus claim token, as today |

- **Response code for "existing": 200**, with the card JSON at top level as today. Older dashboard builds read `published.handle` and redirect to `/p/<handle>`, so they land on the existing card instead of creating a copy. That's a safe fallback until the UI change ships.
- **"Update in place" keeps** `id`, `handle` (unless a valid, free `custom_handle` is sent), `created_at`, the first `published_at`, the `zynd_memory` snapshot and `owner_email`. It **replaces** the card content, `scrape_raw`, `user_intent` and the embedding, then runs the publish hooks (IndexNow).
- **Race:** two concurrent signed-in publishes. The second insert fails the new unique index (§3.3, SQLSTATE `23505`); the handler re-reads the owner's card and takes the update path.

### 3.2 zynd-cards changes (branch `fix/one-card-per-person` → `main`)

| File | Change |
|---|---|
| `services/cards.py` | New `find_published_by_owner(email)` (normalized email, `status='published'`, newest first). New `find_published_by_social(handle_github, handle_x)` (`ilike` with `%`/`_` escaped; `status='published'`). New `replace_card_content(row, card, custom_handle)` sharing the write code with `update_card` (factor out `_write_update`). `insert_card` and `update_card` store `owner_email` as `lower(trim(…))` |
| `services/cards.py::get_card_by_owner` | Filter `status='published'`, so `/cards/mine` never returns archived or draft cards (**today it returns them**) |
| `services/cards.py::update_card` (PATCH) | Refuse archived cards (404). **Ignore `status` in the body** and keep the stored status. Today an owner can PATCH an archived card with `"status": "published"` and resurrect it. Compare owner emails case-insensitively |
| `api/onboard.py::publish_card` | Implement §3.1. Catch `23505` and fall back to the update path |
| `api/cards.py` refresh routes | Already 404 for non-published cards through `get_card_by_handle`. Add `status` to the owner re-read so the check can't drift |
| `x/mentions.py::_publish_card` | Before inserting, look for a published card with the same `handle_x` / `handle_github`. If one exists, link the X account to it (`upsert_account`) and send `reply_already_exists` |
| `x/mentions.py` answer path (~line 315) | **Bug found:** it calls `insert_card` (an upsert on `id`) on every answer, which re-runs `_assign_handle`. That function finds the card's own row, treats the handle as taken, and renames the card to `<base>-<id4>`. Switch it to a content update that keeps the handle |
| Handle availability | Archived cards **keep** their handles (no reuse, so old links can't be taken over). Document this in `check_handle_available` |
| Sitemap, directory, search, `/ask`, `/v1/agents`, `/v1/chat` | Already published-only (`list_published`, `match_cards`, `search_cards_fts`, `get_card_by_handle`). Add regression tests that lock this in |

**Tests** (`tests/test_publish_dedupe.py`): signed-in owner republish updates (row count unchanged, id/handle kept, content replaced); race → update; anonymous duplicate → `existing:true`, no token, no row; signed-in without a card + match → `existing:true`; custom handle on update (free vs taken); archived card hidden from `/cards/mine`, by-handle, search, list, `/v1/agents/search`; PATCH on archived → 404; PATCH can't change status; X bot: existing card → no insert; X bot answers keep the handle; mixed-case owner email still matches.

### 3.3 SQL for you to run: `zynd-cards/db/patch_one_card_per_owner.sql`

Order: (1) read-only pre-checks → send me the output → (2) normalize → deploy code → (3) indexes. The code works with or without the index.

```sql
-- (1) PRE-CHECKS (read-only). The index in (3) fails if the first query returns rows.
select lower(trim(owner_email)) as email, count(*), array_agg(handle order by created_at) as handles
  from public.agent_profile_cards
 where status = 'published' and owner_email is not null
 group by 1 having count(*) > 1;

select count(*) as mixed_case_emails
  from public.agent_profile_cards
 where owner_email is not null and owner_email <> lower(trim(owner_email));

select lower(handle_github) as gh, count(*), array_agg(handle) from public.agent_profile_cards
 where status = 'published' and handle_github is not null group by 1 having count(*) > 1;
select lower(handle_x) as x, count(*), array_agg(handle) from public.agent_profile_cards
 where status = 'published' and handle_x is not null group by 1 having count(*) > 1;

-- (2) NORMALIZE
update public.agent_profile_cards set owner_email = lower(trim(owner_email))
 where owner_email is not null and owner_email <> lower(trim(owner_email));

-- (3) INDEXES: run each statement on its own (CONCURRENTLY can't run inside a transaction)
create unique index concurrently if not exists agent_profile_cards_one_published_per_owner_email
  on public.agent_profile_cards (lower(owner_email))
  where status = 'published' and owner_email is not null;
create index concurrently if not exists agent_profile_cards_published_github_idx
  on public.agent_profile_cards (lower(handle_github)) where status = 'published' and handle_github is not null;
create index concurrently if not exists agent_profile_cards_published_x_idx
  on public.agent_profile_cards (lower(handle_x)) where status = 'published' and handle_x is not null;
-- Rollback: drop index concurrently if exists agent_profile_cards_one_published_per_owner_email;
```

Sahil's two cards sit under two different emails, so they don't violate the index. They stay two cards until you decide which one to archive (D2).

### 3.4 dashboard changes (branch `fix/card-dedupe`, stacked on `fix/card-claim-token`; push the branch only)

| File | Change |
|---|---|
| `src/app/(site)/create/page.tsx` | Handle `existing: true`: don't save a claim token. Show "A card for @x already exists" with **View card**, plus **Sign in to claim** (unowned) or **Sign in as its owner to edit** (owned). A signed-in user who already has a card sees **Update my card** (the server now updates in place). Remove the "or create a new one" copy. `updated: true` → go to `/p/<handle>` |
| `src/app/(site)/p/[handle]/unclaimed-card-actions.tsx` | On 403 show "We couldn't confirm this card is yours" plus a help link, instead of failing silently |
| `src/lib/cards.ts` | New `interpretPublishResponse()` helper (`created` / `updated` / `existing`) with a unit test next to `post-login.test.ts` |

Merge order for you: `fix/card-claim-token`, then `fix/card-dedupe` (or merge only `fix/card-dedupe`, which contains both).

### 3.5 Deploy and verify

1. Run SQL (1) and (2).
2. Deploy cards (compose on the api box).
3. Run SQL (3).
4. Deploy the dashboard branch once you merge it.
5. Verify:
   - Publishing twice while signed in leaves one row, with the same id and new content.
   - An anonymous publish with a known GitHub URL returns `existing: true` and inserts no row.
   - `select count(*) … where status='published' group by lower(owner_email) having count(*)>1` returns no rows.

**Size: S.**

---

## 4. Sub-stage 2A: `zynd-account` (new local repo `p3ai/zynd-account`)

Nothing is deployed in 2A. Everything is written and tested locally; the SQL is handed to you at the end.

### 4.1 Layout
```
zynd-account/
├── sql/0000_preflight.sql  0001_identity.sql  0002_outbox.sql  0003_functions.sql  0004_views.sql  0005_backfill.sql
├── sql/tests/                     # pytest + psycopg against a scratch Postgres 18
├── py/pyproject.toml              # package zynd-account, import zynd_account, Python >=3.11
├── py/zynd_account/{session,identity,service,keys,fastapi,errors,middleware,events,relay,consumer}.py
├── py/tests/
├── ts/package.json                # @zynd/account, tsup (ESM+CJS), vitest
├── ts/src/{browser,server,cookies,react,login,safe-next}.ts(x), ts/src/next/callback.ts
├── ts/tests/
├── .github/workflows/ci.yml       # stays local until the GitHub repo exists
└── README.md  CHANGELOG.md
```

### 4.2 SQL (LLD §4.1.1–4.1.5, with these changes)

- **Deviation: renumbered.** Order becomes 0001 identity → **0002 outbox** → **0003 functions** → **0004 views** → 0005 backfill. In the LLD, `handle_new_user` (0002) inserts into `event_outbox` (0004). Between applying those two files, **every signup would fail**, because a trigger error aborts the `auth.users` insert.
- **Deviation: `handle_new_user` can never block a signup.** Its body runs inside `begin … exception when others then raise warning …; end`. The library's lazy `ensure_profile` on first sight fills any gap.
- **`0000_preflight.sql`** (read-only, for you to run first):
  - lists existing non-internal triggers on `auth.users`
  - checks for tables or views already named `profiles`, `product_memberships`, `handle_aliases`, `handle_reservations`, `reserved_words`, `event_outbox`, `event_deliveries`, `event_subscriptions`, `processed_events`, `card_public`, `persona_public`, `person_public`
  - checks that `citext` is installed

  The persona repo migrations define none of these, but the prod DB may.
- **Views need `agent_profile_cards.owner_id`**, which arrives in 2B (`zynd-cards/db/patch_owner_id.sql`). Apply order: 0001–0003 in 2A/X1, then cards `patch_owner_id.sql` → 0004 → 0005 in X2. `persona_public` uses `persona_agents(user_id, agent_id, name, description, capabilities, active)`; all six columns exist in `backend/db/schema.sql`.
- **Hardening:**
  - Every `security definer` function sets `search_path = public, pg_temp`.
  - `revoke execute … from public` on every function (Postgres grants EXECUTE to PUBLIC by default).
  - `fanout_event` also sets `search_path`.
- **Deviation: `processed_events` gets a `consumer` column**, primary key `(consumer, event_id)`. Cards and persona both consume events and share the Zynd Account DB, so a single-column key would let one consumer's dedupe hide an event from the other. The DDL lives in 0002 and is reused in memory's schema.
- **SQL tests** run on a scratch cluster (`initdb` + `pg_ctl -o "-p 5544"` in the scratchpad) with a stub `auth` schema: `auth.users`, `auth.uid()` reading `request.jwt.claim.sub`, and the roles `anon`, `authenticated`, `service_role`. Cases:
  - `handle_is_free` rules (format, reserved word, taken, another user's alias, reserved)
  - `set_handle` writes an alias and a `profile.updated` event, and reclaims an own alias
  - `adopt_handle` releases only the matching reservation and keeps an existing handle
  - `generate_handle` suffixes and pads short bases
  - `touch_membership` first-sight flag
  - the trigger creates a profile plus `account.created`, and a signup still succeeds when the outbox insert fails
  - fan-out creates one delivery per subscriber
  - RLS: a user reads only their own memberships; an authenticated user can update only `display_name`, `avatar_url`, `headline`, `discoverability`
  - `card_public` hides non-published cards (stub table with no vector column)
  - backfill is idempotent

### 4.3 Python `zynd_account`

| Module | Contents |
|---|---|
| `session.py` | `SessionVerifier`: ES256 only; `iss` pinned to `<url>/auth/v1`; `aud=authenticated`; requires `exp iat sub iss aud`; rejects `role != authenticated` and `is_anonymous`. JWKS cached 1 h through `PyJWKClient`, which refetches once when it sees an unknown `kid`. `ZyndUser`, `AuthError` |
| `identity.py` | `fetch_verified_identity()` via a live `GET /auth/v1/user`. Trusted providers: `google`, `linkedin_oidc`, `email`. Checks `app_metadata.providers` (a linked account can have several), not only `provider`. Requires `email_confirmed_at` |
| `service.py` | `ServiceAllowlist` (SHA-256 → name and scopes, two hashes per service for rotation), `ServiceClient`, `service_headers()` |
| `keys.py` | `new_key(prefix)` → (key, sha256, display prefix). `hash_key`. Regexes for `zk_(live\|test)_…` and `zsk_live_<svc>_…`. CLI `python -m zynd_account.keys zsk_live_persona_`, which prints the key and its hash **on your terminal only** |
| `fastapi.py` | `ZyndAccount`, `Principal`, and the dependencies `user`, `optional_user`, `self_or_service`, `service(*scopes)`, each marked `__zynd_guard__`. Membership touch cached 10 min. `on_first_seen(uid, token)` hook. Service calls with `obo` are audit-logged |
| `errors.py` | Error body `{"error": {code, message, request_id}}` plus an exception handler |
| `middleware.py` | `X-Request-Id`: generated when missing, stored in a contextvar, echoed in the response. `current_bearer` contextvar, used by persona to forward the user's JWT |
| `events.py` | `envelope()`, and `emit(conn, …)` for asyncpg producers (memory) |
| `relay.py` | Delivery loop (LLD §4.10): claims rows in a short transaction with `FOR UPDATE SKIP LOCKED`, delivers outside it, exponential backoff capped at 1 h, dead-letters after 24 h, wakes on LISTEN/NOTIFY with a 2 s poll fallback. CLI `python -m zynd_account.relay`. Wired up in 2C |
| `consumer.py` | `/internal/v1/events` router factory with `processed_events` dedupe (the row is committed only after the handler succeeds, so a failed handler is retried) |

Dependencies: `pyjwt[crypto]`, `httpx`; extras `fastapi`, `relay` (`asyncpg`). **Tests:** everything in LLD §10.1 for py, using keys generated in the test and a patched JWKS: ES256 ok; expired → `token_expired`; wrong `iss`; HS256 rejected; anonymous rejected; unknown `kid` refetch; unknown `zsk_` → 401; `zsk_` + `X-Zynd-User` without `obo` → 403; `self_or_service` mismatch → 403; first-sight flag; relay retry/backoff/dead-letter against local Postgres; consumer dedupe.

### 4.4 TypeScript `@zynd/account`

LLD §4.1.7, plus these notes:
- Peer dependencies: `next >=15`, `react >=19`, `@supabase/ssr >=0.6`, `@supabase/supabase-js >=2.50` (`getClaims`).
- `react.tsx` and `login.tsx` carry a `"use client"` banner.
- `ZyndAccountProvider` / `useZyndAccount` are ported from `dashboard/src/hooks/useAuth.tsx`, keeping the `knownUserIdRef` de-dupe and dropping the developer-key logic.
- `ZyndLogin` offers Google, LinkedIn and an email magic link. It stores `next` **in a cookie**, not sessionStorage: a magic link opens a new tab, and sessionStorage doesn't carry over.

**Tests (vitest + jsdom):**
- `safeNextPath`: rejects `//`, `\`, absolute URLs and encoded variants
- cookie options per environment
- the callback handler: success, error, missing code, `zynd_next` cookie cleared
- `ZyndLogin` sets `zynd_next` and calls the right provider
- the provider ignores a repeated `SIGNED_IN`

### 4.5 Exit and report
All py, ts and SQL tests pass. I hand over:
- `0000_preflight.sql` → 0001–0003 for **staging first**, then prod (X1)
- the draft cards `patch_owner_id.sql` plus 0004/0005 for X2

You decide when to create the GitHub repo (D4).

**Size: M.**

---

## 5. Sub-stage 2B: backends accept old and new credentials

**Order inside 2B** (each step deployable and reversible on its own):

| Step | Repo | Why this order |
|---|---|---|
| B1 | memory-layer: resolver, `zynd_uid`, API keys, taxonomy | Everyone else starts sending session JWTs and `zsk_` keys to memory |
| B2 | agent-persona: `za` auth, `/internal/v1/*`, token broker, memory client | Memory's switch in B3 needs these endpoints |
| B3 | memory-layer: stop direct persona-table access | Needs B2 in prod |
| B4 | zynd-cards: `za` auth, `owner_id`, legacy claim, `zsk_cards`, seed memory | Needs B1 (declare-batch with session JWT, `interested_in`) and X2 SQL |

**Package delivery (D4):** the backends need `zynd_account` before any package is published. Recommendation below.

### 5.1 B1: memory-layer (branch `feat/zynd-account-auth` → PR)

| Area | Change |
|---|---|
| `sql/schema.sql` | `users.zynd_uid uuid` + unique index; `api_keys` (LLD §4.6.1); `assertions.provenance`; `users.has_persona boolean default false`. The outbox and `processed_events` DDL wait for 2C |
| `app/principal.py` (new) | `resolve(authorization, x_zynd_user)` in the order `zk_` → `zsk_` (+obo) → JWT by `iss` (Zynd Account ES256 → memory HS256) → dev bearer → 401 (LLD §4.6.2) |
| Compatibility (**deviation**) | memory HS256 tokens in the wild carry `sub` = internal id (GPT/MCP) **or** the persona/Supabase uuid (persona-minted, bridge dev fallback). Look up by `zynd_uid`, then internal id, then `supabase_user_id`. The last fallback stays until X8. The LLD deletes it now, which would break persona before B2 ships |
| `app/main.py::current_user` | Delegates to `resolve()` and still returns the internal id, so the ~40 routes don't change. New `current_principal` plus `require_scope()`: `zk_` keys need `memory.read` for reads and `memory.write` for writes. `/me/api-keys` accepts session credentials only |
| `app/mcp_http.py::ZyndTokenVerifier` | Uses `resolve()`. A `zk_` key's scopes limit which tools it can call. `_suid()` returns `zynd_uid` (persona `api_tokens` are keyed by the Zynd Account uid, which is the `zynd_uid`) |
| First sight | `_user_by_zynd_uid(create=True)`: a live `fetch_verified_identity`, then link an existing row by verified email where `zynd_uid IS NULL`, otherwise insert. `ON CONFLICT` on the unique index handles races |
| Token issuance | `sub` = `zynd_uid` when the user has one, otherwise the internal id |
| `app/api_keys.py` (new) | `POST/GET/DELETE /me/api-keys` (LLD §4.6.4): cap of 20 active keys, scopes ⊆ `memory.read memory.write people.search`, expiry 1–730 days (default 180), key shown once. `ZK_PREFIX` env (`zk_live_` / `zk_test_`) |
| `/me/whoami`, `/me/findability/declare-batch` | **Not on main** (the Stage 1 PR was closed). Port both from `e08cd2d`; `whoami` also returns `zynd_uid`. declare-batch caps at 50 items and accepts an optional `source` |
| `/v1/service/findability/{id}` | Accepts `zsk_cards` (`findability.read`, lookup by `zynd_uid` only) **and** the legacy `MEMORY_SERVICE_TOKEN` path, unchanged |
| `declare-batch`, `/me/memory/declare` | Optional `source` → `assertions.provenance` |
| `app/taxonomy.py` | `interested_in`: `PREDICATE_HALFLIFE_DAYS` (which defines `ALLOWED_PREDICATES`), `FINDABILITY_PREDICATES`, `DECLARE_ENTITY_TYPE` (`concept_topic`), `CLUSTER_PREDICATES["intent_cluster"]`, and `PREDICATE_PHRASE` "You're interested in {obj}". New `GET /v1/taxonomy` (JSON) |
| `app/oauth.py` (front door) | `ZYND_LOGIN_URL` (falls back to `PERSONA_LOGIN_URL`). The signed `req` now carries `code_challenge` and its method. `/oauth/complete` verifies the session with `resolve()` (local ES256), not `/auth/v1/user`. **Deviation:** sending *all* clients (Claude/DCR/CIMD) to the front door sits behind `FRONT_DOOR_ALL_CLIENTS=false` until 2D. Persona's login is LinkedIn-only until then, so turning it on now would take Google away from Claude users. The `state_id` / `/oauth/callback` path keeps working until X10 |
| `/token/exchange`, `/me/social-links` | Unchanged. The dashboard still uses them with xmfj tokens until 2D |
| `scripts/backfill_zynd_uid.py` | You run it once with the Zynd Account service key **in your shell only**. It pages `auth/v1/admin/users` and sets `zynd_uid` where `supabase_user_id` matches an existing uid. `--dry-run` prints counts first |
| Config | `SERVICE_CLIENTS`, `ZYND_ACCOUNT_URL`, `ZYND_LOGIN_URL`, `RESOLVER_V2` (default true; false restores the old `current_user`) |

**Tests:** resolver matrix (6 credential types × valid/invalid); obo without scope → 403; unknown `zsk_` → 401; `zk_` create → use → revoke → 401, expiry, the 20-key cap, scope enforcement on REST and MCP; first-sight link by verified email, and an unverified email isn't linked; persona HS256 tokens still accepted; `whoami` includes `zynd_uid`; `interested_in` declarable. Postgres-backed tests stay in the known-failure baseline unless you approve `brew install pgvector redis` (D6).

### 5.2 B2: agent-persona backend (branch `feat/zynd-account-auth` → merge to `dev`)

| File | Change |
|---|---|
| `api/auth.py` | `get_current_user` → local ES256 via `zynd_account`, still returning `{id, email, user_metadata}` (Supabase access tokens carry `user_metadata`). Drop the 60 s cache. `PERSONA_AUTH_MODE=legacy` restores `sb.auth.get_user` |
| `api/guards.py` | Stays the thin wrapper. `_service_name` adds the `ServiceAllowlist` (`zsk_memory`, `zsk_cards`) **alongside** the interim `SUPABASE_SERVICE_KEY` / `INTERNAL_SERVICE_KEYS` compare, which stays until B3 is proven. `self_only(live=True)` → `fetch_verified_identity` plus an `iat` < 10 min check |
| `api/internal.py` (new) | `/internal/v1/*` from LLD §6.3, each guarded by `service("persona.internal")`. `X-Zynd-User` must equal the path uid when acting for a user. Also covers the calls memory makes today that §6.3 doesn't list (table below) |
| Token broker | `GET /internal/v1/users/{uid}/provider-token/{provider}` (scope `tokens.broker`): refreshes through persona's `services/token_store.py` and returns only `{access_token, expires_at}`. Audit-logged |
| `agent/memory_client.py` | Delete `_make_jwt`. `headers_for(user_id)` forwards the caller's JWT (from the middleware contextvar) when a user request is in flight, otherwise sends `service_headers(ZSK_PERSONA, obo=user_id)`. `MEMORY_AUTH_MODE=legacy\|zsk`, default legacy until memory B1 is in prod |
| Config | `ZYND_ACCOUNT_URL`, `SERVICE_CLIENTS`, `ZSK_PERSONA`, `MEMORY_URL`. **Remove `MEMORY_LAYER_JWT_SECRET`** from code and env only after `MEMORY_AUTH_MODE=zsk` has run clean in prod |
| Memberships | `za` touches `persona` on user calls |

**Memory's direct persona access → persona internal endpoints** (built in B2, called from B3):

| memory call site | Replacement |
|---|---|
| `services/token_store.py::get_tokens` (the only function memory calls; `save_*`/`delete_*` are unused) | `GET /internal/v1/users/{uid}/provider-token/{provider}` |
| `services/matching.py:225,243` (`persona_agents` names) | `POST /internal/v1/people/batch` |
| `services/meetings.py` (344 lines: create, respond, list, get, book, unbook, `book_failed`) | `POST /internal/v1/meetings`, `POST …/{task_id}/respond`, `GET …/users/{uid}/meetings/pending`, `GET …/threads/{id}/meetings`, `GET …/meetings/{task_id}`. **Booking runs inside persona**, which already has `services/meetings.py` and the Google tokens |
| `services/pages_agent.py` (create, get, list, cleanup) and `main.py:587` | `POST /internal/v1/users/{uid}/pages`, `GET /internal/v1/pages/{slug}`, `GET /internal/v1/users/{uid}/pages`. Persona runs the expiry cleanup |
| `tools/brief.py` (read, append, replace, clear, todo) | `GET/PATCH /internal/v1/users/{uid}/brief`, `POST …/todos` |
| `tools/zynd_network.py` (persona search, avatar map via **`auth/v1/admin/users`**, `webhook_url`, `dm_threads` insert/list, `dm_messages` read) | `GET /internal/v1/personas/search`, `POST /internal/v1/people/batch` (with avatars), `POST …/users/{uid}/threads`, `GET …/users/{uid}/connections`, `GET …/threads/{id}/messages` (obo, participant-checked), `POST …/users/{uid}/agent-send` (persona resolves the webhook itself) |
| `services/persona.py` (status, register, social, introduce, send, connections via `/rest/v1/dm_threads`, meetings) | The same operations under `/internal/v1/users/{uid}/…` |

**Tests:** `test_route_guards.py` stays green (the internal router is guarded); new `test_internal_api.py` (scopes, obo mismatch → 403, the broker never returns a refresh token); `test_memory_client_auth.py` (forwarding vs `zsk`+obo); update `test_guards.py` for `zsk_`. The 5 baseline failures that need `MEMORY_LAYER_JWT_SECRET` are rewritten for the new auth modes.

### 5.3 B3: memory-layer switches to persona `/internal/v1` (branch `feat/persona-internal-client` → PR)

- New `app/services/persona_internal.py`: an httpx client with `zsk_memory` + obo + `X-Request-Id`, 8 s timeout, typed errors.
- Every call site in the table above goes through it, behind `PERSONA_ACCESS_MODE=direct|internal`. The direct path stays for one release, then it and `supabase` / `SUPABASE_SERVICE_KEY` are deleted.
- Tests use a fake persona (httpx `MockTransport`) for each tool path.
- **Exit gate (X6):** 7 days with no `SUPABASE_SERVICE_KEY` reads in the logs → you remove the env var.

### 5.4 B4: zynd-cards (branch `feat/zynd-account-auth` → `main`)

| File | Change |
|---|---|
| `db/patch_owner_id.sql` | LLD §4.2.1: column, index, one published card per `owner_id`. Plus the `handle_reservations` insert for unowned cards (the 0005 backfill does existing rows) |
| `api/auth.py` | `za = ZyndAccount(product="cards")`. A token with the Zynd Account `iss` goes through `za`. Anything else goes through the old `verify_supabase_jwt` **only if `LEGACY_DASHBOARD_TOKENS=true`**, which yields an email-only principal |
| Ownership (dual mode) | Zynd Account principal: allowed if `owner_id == uid`, or if `owner_id` is null and `lower(owner_email)` equals the **live-verified** email (claim now: set `owner_id`, then `adopt_handle`). Legacy principal: allowed if `lower(owner_email) == email` (today's rule). 2.0's dedupe keys on `owner_id` when known, otherwise on email |
| `api/onboard.py` publish | `owner_id` + `owner_email` from the principal. Unowned publish → `handle_reservations('card:<id>')` (skipped with a log line if the table doesn't exist yet). Owner publish → `adopt_handle(uid, handle, 'card:'+id)` so the profile gets the card handle |
| First sight | `za.on_first_seen` → `claim_legacy(uid, verified_email)` (LLD §8.4) |
| `services/zynd_memory.py` | `fetch_findability(zynd_uid)` → `{MEMORY_INTERNAL_URL}/v1/service/findability/{uid}` with `zsk_cards`. Falls back to the email + `MEMORY_SERVICE_TOKEN` path for cards without `owner_id` |
| Seed memory on publish | Background, non-blocking, 8 s timeout. `declare-batch` with **the user's JWT** (Zynd Account principals only) using `source=cards:onboarding` and the LLD §4.2.3 map, plus `industries`/`affiliations` → `is_affiliated_with`. `connect_with` is mapped to memory's enum values (`is_seeking` / `open_to`); unmapped values are skipped. Dashboard (legacy) publishes keep the dashboard's own `syncMemoryOnClaim` until 2D |
| `main.py` | CORS adds `https://cards.zynd.ai`, `https://persona.zynd.ai`, `https://dev.persona.zynd.ai` |
| Config | `ZYND_ACCOUNT_URL`, `SUPABASE_ANON_KEY`, `SERVICE_CLIENTS`, `ZSK_CARDS`, `MEMORY_INTERNAL_URL`, `LEGACY_DASHBOARD_TOKENS=true` |

**Tests:**
- Owner checks for each principal type.
- Claim happens only with a live-verified email match.
- The reservation is released on claim.
- Seeding sends the mapped declarations with the forwarded JWT and never blocks publish.
- `connect_with` enum mapping.
- Legacy dashboard tokens accepted only when the flag is on.
- The 2.0 tests still pass.

### 5.5 2B runbook for you (LLD X1–X7)

| # | Step | Verify | Rollback |
|---|---|---|---|
| 1 | Zynd Account SQL `0000_preflight` → 0001–0003 on **staging**, then prod | Tables and functions exist; a test signup creates a profile and an `account.created` row | Drop the new objects |
| 2 | cards `patch_owner_id.sql` → 0004 views → 0005 backfill | Every `auth.users` row has a profile; unowned card handles are reserved | Truncate reservations |
| 3 | Generate `zsk_persona`, `zsk_cards`, `zsk_memory` with `python -m zynd_account.keys` **on your machine**. Plaintext goes to the caller's env; hashes go into the receivers' `SERVICE_CLIENTS` (LLD §7) | — | Remove the hashes |
| 4 | Deploy memory B1 (PR merge + compose), then run `backfill_zynd_uid.py --dry-run`, then for real | Logs show `credential_type` counts; no rise in 401s | `RESOLVER_V2=false` |
| 5 | Deploy persona B2 to dev, then prod; then `MEMORY_AUTH_MODE=zsk` | Memory sees no persona-minted HS256; obo audit lines appear | `MEMORY_AUTH_MODE=legacy` |
| 6 | Deploy memory B3 with `PERSONA_ACCESS_MODE=internal` | Brief, meetings, pages and MCP Google tools work end to end | `PERSONA_ACCESS_MODE=direct` |
| 7 | Deploy cards B4 with `LEGACY_DASHBOARD_TOKENS=true` | `/cards/mine` works with both token kinds; publishing through the dashboard still works | Revert the image |
| 8 | After 7 clean days: remove `SUPABASE_SERVICE_KEY` from memory and `MEMORY_LAYER_JWT_SECRET` from persona. **Rotating memory `JWT_SECRET` (X8) is a separate, explicitly approved step** | — | Re-add the env vars |

**Size: L** (the largest sub-stage).

---

## 6. Sub-stage 2C: events (LLD §4.10, HLD §8)

### 6.1 Producers

**Deviation: triggers instead of `emit()` calls in cards and persona.** Both write through supabase-py/PostgREST, where each call is its own transaction. A trigger is the only way to get a true transactional outbox there.

| Event | Producer | Mechanism |
|---|---|---|
| `account.created`, `profile.updated` | Zynd Account | Already in 0003 (trigger, `set_handle`) |
| `card.published`, `card.updated` | cards | `zynd-cards/db/patch_card_events.sql`: an AFTER INSERT/UPDATE trigger on `agent_profile_cards`, fired when a card becomes or stays `published` and `card` or `status` changed. Payload: id, handle, bio and project text |
| `persona.created` | persona | Trigger on a `persona_agents` insert (or change to `active=true`) |
| `connection.added` | persona | Trigger on `dm_threads.status` → `accepted` |
| `findability.changed` | memory | `zynd_account.events.emit` inside the same asyncpg transaction as approve / revoke / declare / declare-batch |

### 6.2 Relays (one per DB)

| DB | Where it runs | Signs with |
|---|---|---|
| Zynd Account | pm2 app `relay` on the persona host, using a **session-mode** Postgres URL (LISTEN needs a direct or session connection, not transaction pooling) | `zsk_persona` |
| memory | new compose service `relay` (same image) | `zsk_memory` |

`EVENT_SUBSCRIBERS` JSON maps each subscriber to its `/internal/v1/events` URL.

### 6.3 Consumers

All consumers use `consumer.py` with `processed_events(consumer, event_id)`.

| Consumer | Handles |
|---|---|
| cards | `findability.changed` → refresh that user's card `zynd_memory` snapshot (debounced 60 s per user; asyncio task, retried through the relay on failure). `profile.updated` → sync the card handle. `persona.created` → set the flag |
| memory | `card.published` / `card.updated` → store bio/projects text and enqueue a facet refresh (the new bio/projects facets are Later, §5.1). `profile.updated` → `display_name`. `account.created` → pre-create the user. `persona.created` → `has_persona` |
| persona | `account.deleted` → no-op when persona is the originator |

**`account.deleted` deletes data**, so its memory and cards handlers ship **disabled** (`EVENTS_HANDLE_ACCOUNT_DELETED=false`) until you approve. The persona `DELETE /api/account` fan-out is Later §5.4.

### 6.4 Cron, tests, runbook

- **Cron:** the 6-hour `memory_refresh_loop` stays. Remove it once `findability.changed` has delivered for 7 days with zero dead letters. I give you the SQL that checks this.
- **Tests:**
  - triggers fire only on the right transitions
  - relay: SKIP LOCKED with two relays, backoff, dead letter, NOTIFY wake
  - consumers: dedupe, a failed handler is retried, the wrong scope → 403
  - end to end on local Postgres: approve → event → card snapshot refreshed
- **Runbook:**
  1. memory schema (outbox, subscriptions, `processed_events`)
  2. Zynd Account trigger patches
  3. cards and persona consumers
  4. relays (pm2 / compose)
  5. verify delivery lag and dead letters

**Size: M.**

---

## 7. Sub-stage 2D: frontends

### 7.1 `zynd-cards/web` (new Next.js 16 app; pushed with zynd-cards `main`)

- **Port** LLD §4.3: about 11k lines from the dashboard. The largest files:
  - `create/page.tsx` (1.9k)
  - `p/[handle]/page.tsx` (1.3k)
  - `agent-card/page.tsx` (950)
  - `edit-client.tsx` (850)
  - `share-controls.tsx` (670)
  - `profile/[id]` (530)

  Plus `lib/cards.ts`, `useMyCard`, the claim-token helpers from 2.0, and the card intent in `post-login`. The dashboard's global Webflow CSS doesn't come along: only the styles these pages use are ported.
- **New files:** `login` (`<ZyndLogin/>`), `auth/callback`, `settings/connections` (links to persona), `components/MemorySuggestions.tsx` (owner only; memory `/me/findability/suggestions` with the session JWT), and `sitemap` / `llms.txt` / `llms-full.txt` for `/p/*`.
- **Handle resolution** in `p/[handle]`: `profiles.handle` → unowned card handle → `handle_aliases` redirect → 404.
- **Redirects:** Next's `permanent: true` and `permanentRedirect()` send **308**. Where a literal 301 is wanted, use `statusCode: 301` in `next.config` or `NextResponse.redirect(url, 301)`.
- **Env:** LLD §7 "zynd-cards web". The Vercel project, DNS for `cards.zynd.ai` and the first deploy are yours to do (or approve).

### 7.2 agent-persona webapp (branch `feat/cookie-sso` → `dev`)

| File | Change |
|---|---|
| `src/lib/supabase.ts` | Returns a singleton `createZyndBrowserClient()` and runs `migrateLegacySession()` once. The 29 files that call it don't change |
| `src/lib/legacy-session.ts` (new) | localStorage `sb-aafo…-auth-token` → `setSession`, then remove the key |
| `LandingClientWrapper.tsx` | `<ZyndLogin providers={["google","linkedin_oidc","email"]}/>`, redirecting to `/auth/callback` |
| `src/app/auth/callback/route.ts` | Re-exports the callback handler from `@zynd/account` |
| `src/lib/zynd-oauth.ts` | **Fix found:** the pending `zynd_oauth` request lives in **sessionStorage**, which a magic link opened in a new tab can't see. Move it to a short-lived cookie |
| `dashboard/settings/connections` (new) | AI clients, bridge, and LinkedIn/GitHub/X/Google/Notion connections. Needs a **new memory endpoint `GET /me/connections-status`** (none exists today) and a small memory `oauth_grants` table written at `/oauth/token`, because JWT access tokens aren't stored anywhere |
| `dashboard/settings/api-keys` (new) | List, create (shown once, with a copy button) and revoke via memory `/me/api-keys` |
| `src/app/p/[userId]` | Redirect to `https://cards.zynd.ai/p/<handle>`, with the handle added to the persona public endpoint's response |
| Cookie domain | `.zynd.ai` in prod. **dev.persona uses host-only cookies**, so dev builds never overwrite the session prod reads |

Then turn on memory `FRONT_DOOR_ALL_CLIENTS=true`, so Claude, ChatGPT and the bridge all land on the unified login.

### 7.3 zynd-bridge (branch `feat/api-key-login` → `main`)

- `zynd login`: OAuth by default; `--api-key` stores the key in the keychain and checks it with `/me/whoami`. `ZYND_API_KEY` env. `init` calls `login`.
- Auth order: API key → OAuth (with refresh).
- **Remove** `jwtSecret`, `userId`, `makeLocalJwt`, the secret discovery in `discoverMemoryLayer`, and the env vars `MEMORY_LAYER_JWT_SECRET`, `ZYND_JWT_SECRET`, `ZYND_USER_ID`, `ZYND_MEMORY_USER_ID`.
- Tests; version 0.2.0. **Publishing to npm needs your OK.**

### 7.4 dashboard cards removal: last, only after you confirm cards.zynd.ai is live

- LLD §4.8 delete list plus the redirects, on branch `feat/remove-cards` (branch only).
- Then cards sets `LEGACY_DASHBOARD_TOKENS=false`.
- Then X10: remove memory `/connect`, `/oauth/callback`, `/token/exchange`, and dashboard `/authorize`.

**Size: L.**

---

## 8. Flags and removal gates

| Flag | Repo | Default | Removed when |
|---|---|---|---|
| `LEGACY_UNOWNED_CLAIM` | cards | false | Later §5.6 |
| `LEGACY_DASHBOARD_TOKENS` | cards | true from B4 | Dashboard cards removed (7.4) |
| `RESOLVER_V2` | memory | true | X8 |
| `FRONT_DOOR_ALL_CLIENTS` | memory | false | On after 7.2; code removed at X10 |
| `PERSONA_ACCESS_MODE` | memory | direct → internal | 7 clean days (X6) |
| `PERSONA_AUTH_MODE` | persona | za | After B2 has run clean |
| `MEMORY_AUTH_MODE` | persona | legacy → zsk | X8 |
| `EVENTS_HANDLE_ACCOUNT_DELETED` | memory, cards | false | Your approval |
| `memory_refresh_loop` (cron) | cards | on | 7 days of events with zero dead letters |

---

## 9. Decisions I need from you

| # | Question | Recommendation |
|---|---|---|
| **P** | Preconditions 2b and 3 (§0) | Confirm the SMTP / linking / redirect settings, and run `zynd_env_check.py` on the api box |
| D1 | A card already exists for the same GitHub/X, and the caller didn't publish it (no claim token) and has no matching `owner_email`. How can they prove it's theirs? | Keep the strict rules for 2.0 ("contact support"). Later add proof by matching the scraped GitHub public email to the signed-in user's verified email |
| D1b | Also de-dupe on the LinkedIn profile slug (`identity.links.linkedin`)? LinkedIn-only cards have neither `handle_github` nor `handle_x` | Yes. It's cheap, and LinkedIn is the main source for many users |
| D2 | Sahil's two cards (two emails) and Chandan Kumar's possible two cards | You pick the one to keep; I give you the archive SQL. Or wait for identity linking in 2B/2D |
| D3 | A signed-in user without a card publishes a GitHub that's already on **someone else's** owned card | Return `existing` (no copy). The UI shows "already claimed" with a report link |
| D4 | How the backends and apps get `zynd_account` / `@zynd/account` before anything is published | Create the GitHub repo at the end of 2A. Python: pin a git tag (`zynd-account @ git+https://github.com/zyndai/zynd-account@py-v0.1.0#subdirectory=py`; a private repo needs a deploy token in the Docker builds). TS: publish `@zynd/account` to npm under the existing `@zynd` scope (needs your OK), because npm git dependencies can't point at a subdirectory. Fallback: vendored copies plus a drift-check test |
| D5 | Default expiry for personal API keys | 180 days (LLD) |
| D6 | May I `brew install pgvector redis`, so memory's 9 integration tests run locally instead of being skipped as baseline? | Yes. It makes B1 and B3 verifiable before the PR |

---

## 10. Sequence at a glance

```
preconditions ──► 2.0 cards+dashboard (S) ──► 2A zynd-account (M, local)
                                               │
                                               ▼
              2B: B1 memory ─► B2 persona ─► B3 memory ─► B4 cards   (L)
                                               │
                                               ▼
              2C: triggers + relays + consumers; cron kept 7 days     (M)
                                               │
                                               ▼
              2D: cards.zynd.ai ─► persona SSO + login ─► bridge 0.2 ─► [you confirm live] ─► dashboard removal (L)
```
