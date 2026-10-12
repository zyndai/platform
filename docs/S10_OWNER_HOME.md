# S10 owner home

S10 lives in cards-web and cards-api. Memory exposes the two authenticated MCP
read tools through the same Cards status aggregation. Persona is unchanged.

## What ships

- `/home`: completeness and three actions, private review count, seven-day human
  views/agent hits, source freshness, notifications, visibility, digest preview,
  and duplicate cards. Missing upstream data displays as unavailable.
- `/cards/mine/status` and `/cards/mine/activity`: owner-only, identity derived
  from the existing verified session. Memory is called over its service HTTP API.
- Weekly activity digest and optional email nudges, SMTP provider adapter and a
  default no-op adapter. `/internal/owner-notifications` scans daily; SQL unique
  constraints limit weekly deliveries and daily reminder emails per owner.
- Unsubscribe GET asks for confirmation; POST disables both email preferences
  for every card owned by the matching subscription. SMTP includes one-click
  unsubscribe headers. GET does not unsubscribe email-link scanners.
- Owner-initiated merge: either owned card can be canonical. The other is
  archived, with its complete pre-merge row in `card_merges`. Content is not
  automatically combined or newly published. Handles/aliases redirect to the
  canonical published card with 301; redirects are flattened on later merges.
  Same LinkedIn URL produces a claim-first prompt for unowned cards. Shared
  names are insufficient evidence for ownership or a merge.
- Section autosave in the editor: debounced, serialized, visible saved state,
  row-locked comparison of acknowledged values. Other sections and memory
  updates are preserved. Memory/source refreshes use atomic JSON patches when
  S10 is enabled, including for private cards. Internal link navigation flushes saves; failed saves
  keep the draft in the editor. Hard unloads warn while changes are unsaved.
  A session-local backup, scoped to owner and handle, offers restoration after
  browser-back navigation or a reload. It contains editable values, never tokens.
- MCP `get_card_status` and `get_card_activity` derive the owner from the
  authenticated memory uid and use a protected service-to-service request.

## Gates and external dependencies

Default-off configuration:

| Service | Setting | Purpose |
|---|---|---|
| cards-api | `FEATURE_S10_HOME=true` | Owner endpoints, preferences, autosave, merge, nudge scanner |
| cards-web | `NEXT_PUBLIC_FEATURE_S10_HOME=true` | Home/nav/editor behavior; rebuild the web app |
| memory | `FEATURE_S10_HOME=true` | Enable the owner MCP reads |
| memory | `CARDS_API_URL` | Cards API origin for the service HTTP bridge |
| cards-api | `FEATURE_S10_DIGEST=true` | Permit weekly/reminder sends |
| cards-api | `S10_MAILER=smtp` | Use SMTP; the default `noop` never sends or claims deliveries |

`SUPABASE_DB_SCHEMA=cards` is required. `MEMORY_SERVICE_TOKEN` must match
between services. SMTP uses `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD`, `SMTP_FROM`; TLS is required. `SITE_BASE_URL` is the Cards web
origin and `API_BASE_URL` is the publicly routed Cards API origin used for
unsubscribe links. Configure `WEB_REVALIDATE_URL`/`WEB_REVALIDATE_SECRET` for
cache invalidation, including old aliases. Public card/view reads and public
JSON bypass caches with S10 enabled. Existing morning digests remain independent.

S04 collection must be enabled for activity counts. Matching query capture is
an S11 dependency; the current emitter does not record queries. The aggregation
can consume owner-scoped `agent_fetch` events with `meta.endpoint=ask` and
`meta.query`, group the top questions, and create a weekly matched-card nudge.
It reads at most the latest 1,000 query events and redacts URLs/contact details
before returning them. Until these exist, the digest/home show unavailable data.
Intro requests require S12's real intro events. S09 must supply per-assistant
connection health; a memory account alone is not an active assistant connection.

## Schema review and rollout

**Shared database schema change: human review and approval are required.** New
expand-only Cards migrations are `0010_s10_owner_home` and
`0011_s10_owner_operations`; the filename `0007` in the original slice is stale.
No production SQL is part of local implementation or tests.

1. Review schema, service-only policies/functions, and ownership checks. Apply
   through `packages/db` only after a human approves; dev shares the production
   database. Run the normal drift/preflight checks from its README.
2. Configure web/API origins and revalidation; deploy with S10 flags off.
3. Enable home and MCP reads for the intended test deployment. Keep the mailer
   `noop`; inspect the owner preview or `POST /internal/owner-notifications?dry_run=true`
   with `Authorization: Bearer <CRON_SECRET>`.
4. Confirm sender domain, SMTP provider sandbox, delivery, consent, and unsubscribe
   with test accounts before enabling real email. A dedicated test deployment
   is needed for cohort isolation; there is no per-user cohort bypass in these flags.
5. `.github/workflows/owner-notifications.yml` invokes the job daily at 08:00 IST
   with existing `CRON_SECRET`/`CARDS_API_URL` secrets. A scheduled workflow on
   `dev` will not run until it reaches GitHub's default branch; use manual
   dispatch or an external scheduler during dev verification.

Rollback: flags off. Keep additive schema, archived rows, audits, and delivery
records. Public merged redirects continue resolving after disabling home.

## Delivery and autosave failure behavior

SMTP cannot guarantee exactly-once delivery across a process crash. The worker
claims a unique `(owner_email, kind, period)` before sending, then marks the result.
It never automatically retries an ambiguous `claimed` or `failed` delivery;
review these records manually. This guarantees at-most-one send attempt per owner
per ISO week (and per day for reminders). Test previews/no-op never consume a claim.

Autosave clears stale embeddings and regenerates them after saving, guarded by
the returned row timestamp. Full-text search updates in the transaction. A
failed embedding call leaves FTS available and the vector empty; regeneration
can be run via the existing re-embedding script. Conflicts require reloading,
so the editor never silently overwrites someone else's changes.

## Validation

Cards API: `pytest -q`; memory: `pytest -q -m 'not integration'`; Cards web:
`npm run lint`, `npx tsc --noEmit`, `npm run build`, `npm run test:e2e`.

`tests/test_s10_postgres.py` additionally rehearses the two S10 migrations on
a disposable local Postgres with a minimal pre-S10 Cards table; it does not
require pgvector or access Supabase. Set
`S10_TEST_DATABASE_URL=postgresql://<local-user>@127.0.0.1:5548/s10_rehearsal`.
The test rejects every other database target. Full-history migration/drift
validation stays in the existing packages/db CI workflow.

In environments where Turbopack's CSS worker cannot bind its temporary port,
validate the production build with `npm run build -- --webpack`.
