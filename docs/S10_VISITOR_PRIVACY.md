# Profile view counts and visitor names

## Why human views could stay unchanged

Previously, the profile page had no browser-view tracking call. The Cards API
counted `/cards/by-handle/...` reads, but Next's server-side fetch is not the
visitor's browser and can be cached. The dashboard counts only `view` events
classified as `human`. Browser analytics also defaulted to off.

Now `ProfileView` records a `view` when a public profile actually mounts in the
browser. Link prefetching and server rendering do not count as a browser visit;
the effect guards against duplicate development Strict Mode runs. Browser events
use same-origin `POST /api/events`, forwarding the real browser User-Agent to
Cards API so it can classify human traffic. This avoids cross-origin beacon/CORS
issues. Refreshes count as additional recorded visits; these are not unique people.
A direct browser API read can still produce its own legacy view event.

Both `NEXT_PUBLIC_S04_EVENTS` in Cards web and `FEATURE_S04_EVENTS` in Cards API
now default to true. Explicit false overrides still disable collection. Existing
S04 tables on `SUPABASE_DB_SCHEMA=cards` are required. Event collection remains
best effort; failed database inserts are logged by the API. `/home` refreshes on
window focus and once a minute while visible, without overwriting an active save.

The live site is not updated by local edits. Rebuild/restart Cards web and deploy
reviewed Cards API changes before expecting new behavior at cards.zynd.ai.

## Named visitor rules

- Anonymous browsing is **on by default**. Signed-out visitors are anonymous.
- A signed-in person can turn **Anonymous browsing** off in their `/home` settings.
  Public profile pages do not show this control. The text asks for agreement to
  share their name with owners of profiles they visit.
- The preference belongs to the verified user session. Request bodies cannot
  choose another user or supply the visitor's name. Names come from the visitor's
  own card, matched by verified email and account ID where backfilled (cards linked
  to another account are excluded), with signed account metadata
  as a fallback. Names are capped at 80 characters, with a generic fallback instead of
  exposing an email. A name is self-reported, not proof of real-world identity.
- Sessions must belong to the same Supabase project as the database, since
  `auth.users.id` is the preference/visitor identity. A trusted legacy-project
  token cannot collide with a user UUID in the new project.
- Named rows are created only for an opted-in visitor, on a published owned card,
  excluding self-visits. Counts still include anonymous and self browser visits.
- Turning anonymous mode back on hides earlier named visits on subsequent owner
  reads. A later opt-in starts a new consent version and does not republish old
  history. It cannot retract a name the owner already saw or copied.
- Named history is scoped to the current card owner's email snapshot, preventing
  a different owner from inheriting previous named visitor history after transfer.
- Owners see at most 20 distinct consenting visitors from the last seven days,
  with display name, latest visit time, and visit count. Raw visitor IDs, session
  hashes, and emails are not returned. Public cards/JSON never include the list.
- New named-visit tables are service-only with RLS. Direct authenticated database
  clients cannot read them or execute the service functions. User deletion
  cascades preferences and visits. The existing event-purge job also removes
  named visits older than 180 days when that job runs.

## Schema and deployment

New local migrations (review before applying):

- `0015_s10_visitor_privacy.sql`: service-only preference and named-visit tables.
- `0016_s10_visitor_consent_operations.sql`: atomic consent and owner-list RPCs.
- `0017_s10_visit_owner_binding.sql`: owner binding on the new visit rows.

These are generated/custom migrations in `packages/db/cards`. **No shared
migrations have been applied.** Auth and shared-schema review are required before
deployment. Rehearsal used a disposable local database with a minimal Cards
fixture; full pgvector/card-history validation remains a database CI check.

Until the migrations are applied, named history reports unavailable and the
privacy control cannot change preferences. Anonymous browser counting continues
through the existing event table independently.

## Manual checks

Use Alice's `saraffa13` card, a separate signed-in Bob account, and incognito:

1. Record Alice's human-view count on `/home`.
2. In incognito visit `/p/saraffa13`. In Network, check `POST /api/events` returns
   204. Its forwarded request contains a `view` event for `saraffa13` and the
   browser User-Agent. Return to Alice's home tab/reload; the count increases.
3. Sign in as Bob, open Bob's `/home`, and confirm Anonymous browsing starts on. Visit Alice again.
   Her count increases, but Bob's name is absent.
4. Bob returns to his `/home` and turns Anonymous browsing off after reading the
   agreement, then visits Alice's profile. Refresh Alice's home: Bob's own card
   name appears, rather than Alice's name. The profile has no privacy checkbox.
5. Reload Alice's profile as Bob: the visitor list aggregates his new visits.
6. Bob turns Anonymous browsing on from his `/home`. Refresh Alice's home: Bob disappears while
   historical anonymous view totals remain intact.
7. Bob opts in again without visiting Alice: old visits stay hidden. A new visit
   can show Bob again, under the new consent version.
8. Check Alice's public card and public JSON in incognito: no visitor identities.
9. Alice visits her own card: count can increase; her name is not listed as a
   visitor of her own profile.
10. In a failed-preference-save test, confirm the UI retains the prior saved
    setting and shows an error instead of claiming anonymity changed.

No live consent changes, named-visitor writes, emails, or deployment were
triggered by the implementation tests. Tests use mocked HTTP/auth and disposable
SQL fixtures.

## Automated verification

Local verification passed: 27 Cards browser tests (mocked services), 9 disposable
Postgres consent/security tests, both TypeScript checks (web and database), the
Cards production build, migration lint, and Drizzle journal checks. The Cards API
suite recorded 366 passed and 11 skipped, with the same five pre-change failures
(three rename mocks and two X-bot tests). No new API failures were introduced.
Full-web lint retains its pre-existing violations; the new visitor files passed
targeted lint. The disposable database is stopped after verification.
