# S10 owner home

S10 lives in cards-web and cards-api. Memory exposes authenticated owner status
and activity in `get_my_context` through the same Cards status aggregation.
Persona is unchanged.

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
- Section saves in the editor: serialized, visible saved state, row-locked
  comparison of acknowledged values. Edits are saved only when the owner clicks
  Save changes (or presses Cmd/Ctrl+S), so an accidental removal can be discarded
  with Discard instead of being persisted by a timer; the hook still supports
  debounced autosave (`auto` argument) if that is wanted back. Other sections and
  memory updates are preserved. Memory/source refreshes use atomic JSON patches
  when S10 is enabled, including for private cards. A source refresh asks the
  owner to save or discard first. Internal link navigation and hard unloads warn
  while changes are unsaved; failed saves keep the draft in the editor. The
  photo is not editable: it comes from the linked accounts and the server keeps
  the stored one when a section is saved.
  A session-local backup, scoped to owner and handle, offers restoration after
  browser-back navigation or a reload. It contains editable values, never tokens.
- MCP `get_my_context.status` and `get_my_context.activity` derive the owner
  from the authenticated memory uid and use one protected service-to-service
  status request. These sections require `cards:read` or legacy `user` scope;
  `cards:approve` alone does not grant read access. Without read access both keys
  are omitted; with read access both are null when disabled or unavailable.

## Gates and external dependencies

Cards web and Cards API enable S10 owner home by default when their respective
flags are unset. Set either flag to `false` to disable it explicitly. Changing
the web flag requires a rebuild. Memory owner tools and email sending remain
opt-in.

| Service | Setting | Purpose |
|---|---|---|
| cards-api | `FEATURE_S10_HOME=true` (default) | Owner endpoints, preferences, section saves, merge, nudge scanner |
| cards-web | `NEXT_PUBLIC_FEATURE_S10_HOME=true` (default) | Home/nav/editor behavior; rebuild the web app |
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

## Delivery and save failure behavior

SMTP cannot guarantee exactly-once delivery across a process crash. The worker
claims a unique `(owner_email, kind, period)` before sending, then marks the result.
It never automatically retries an ambiguous `claimed` or `failed` delivery;
review these records manually. This guarantees at-most-one send attempt per owner
per ISO week (and per day for reminders). Test previews/no-op never consume a claim.

Saving a section clears stale embeddings and regenerates them, guarded by
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

For repeatable notification sends to one selected owner or all owners, see
[Send a notification test email](S10_TEST_EMAIL.md). This uses the existing cron
credential, bypasses preferences/limits for those explicit test sends, and leaves
the scheduled notification path unchanged.

## Profile-assistant question history

New admitted profile-chat questions are saved in existing `cards.card_events`
metadata alongside their category and length. Cards API now defaults to
`FEATURE_S04_EVENTS=true` and `SUPABASE_DB_SCHEMA=cards`; explicit environment
overrides still take precedence. Existing cards migrations must be applied.
No additional schema migration is needed for question history.
Question storage remains best-effort analytics: event collection must be on and
the event insert must succeed; it is not a guaranteed conversation archive.

Owner home shows the latest 20 saved questions from the last seven days under
**Recent assistant questions**. The existing owner-authenticated status API (and
its authorized owner reads) returns question text/category/time only, without
visitor/session identifiers. Public card JSON does not include question history.
**Questions that found your card** still refers to discovery/search queries and
is independent from questions asked directly to the profile assistant.

Email/phone-containing questions remain refused by the existing chat filter.
URLs, common contact patterns, and long token-like strings are redacted before
storage and again on owner read. Redaction is best-effort; visitors must avoid
private information. Unicode/long excerpts are shortened to fit the existing
2 KB event-metadata cap and labelled shortened in the UI. Only the latest user
question is saved, not earlier conversation messages or assistant replies.
The public `/events` batch route strips reserved question-history fields; it
cannot populate this history by submitting arbitrary analytics metadata.

Questions follow the existing card-event retention: the configured purge job
removes events older than 180 days when it runs. The seven-day dashboard window
is not a seven-day deletion policy. Historical category-only records have no
question text to backfill. The chat input notice now explains owner review and
storage; the owner settings copy no longer promises text is never saved.
This deliberately extends the original S14 length/category-only event design.

## Browser views and visitor-name consent

See [Profile view counts and visitor names](S10_VISITOR_PRIVACY.md) for the new
browser tracking path, anonymous-by-default preference, consent revocation,
owner-only visitor list, and local migrations 0015–0017. Those migrations remain
unapplied to the shared database; anonymous view collection works independently.
