# Cards-native network

Cards owns the connection graph for verified Cards. Persona is not involved in
connection requests, DMs, groups, or the Cards MCP network tools.

## Rules

- Both sides must have a claimed, published Card linked to the shared aafo
  account.
- A connection starts as `pending`; only the receiving Card can accept or
  decline it.
- DMs are available only after `accepted`.
- Group invitations are sent only to accepted connections and do not create
  membership until the invitee accepts.
- Cards web and authenticated MCP use the same Cards API and tables.
- Invitations expire after seven days. Acceptance checks expiry, connection
  status, membership, and group capacity in one transaction.
- Cards web refreshes requests/invitations every five seconds and open chats
  every three seconds. Message reads show the latest 100 messages.

## Surfaces

- Cards web: `/network`
- Card profile: `Request connection`
- Cards API: `/cards/network/*`
- Authenticated MCP: `list_card_connections`, `request_card_connection`,
  `respond_card_connection`, `read_card_dm`, `send_card_dm`, and the
  `card_group` tools.

The public, unauthenticated Cards discovery MCP remains read-only. Actions use
the authenticated MCP at `/mcp` and require the `people:message` scope.

## Database

Cards schema migration `0019_cards_network` owns the connection, DM, group,
membership, invitation, and group-message tables. `0020_network_atomic_operations`
adds service-only functions for atomic group creation and invitation decisions.
`0021_reconcile_owner_metadata` tracks the existing owner-digest columns without
resetting their values. `0022_reconcile_cards_live_contracts` reconciles the
reviewed older drift while preserving the live analytics view. These migrations
must be applied before deploying this API.

Test the full Cards migration history and concurrent invitation decisions on a
disposable local Postgres with pgvector (never set this to Supabase):

```bash
cd packages/db
CARDS_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5559/postgres npm test
```

## Dev rollout and rollback

- Squash-merge the feature into `dev` only after verification. Deploy Cards web,
  Cards API, and the Cards MCP bridge; there are no Persona service changes.
- Cards' build uses webpack to avoid the Next.js Turbopack/Google Fonts query
  failure. This changes the build tool only, not the app's runtime behavior.
- Dev and production currently share the Cards database. Migrations are a
  separate, explicitly approved operation; the deploy script never applies them.
- Record the pre-merge `dev` commit and the squash commit. If testing finds a
  problem, revert the squash commit and redeploy dev. Keep the additive network
  tables/functions and their data; reverting code must not drop user messages.

### Shared database preflight — 2026-10-17

The initial read-only check found `0019_cards_network` already applied and `0020` pending.
The comparison was repeated against **PostgreSQL 17**, matching the shared
database. The earlier default-permission differences disappeared: those were
PostgreSQL 16/17 comparison noise, not live permission changes.

Before reconciliation, the full drift gate reported **9 entries only in the live database and 5
only in the migrations**. These describe older Cards objects: four owner-digest
columns, `card_events.actor_class` nullability/default/check, two people-search
function definitions, `purge_card_events`, and `v_funnel_daily`. No networking
table differences were reported.

Additional local verification on PostgreSQL 17:

- All 15 database tests pass, including concurrent invitation decisions and
  group-capacity checks.
- A schema-only copy of the actual live Cards schema restores locally. No user
  rows were copied.
- Applying `0020` to that copy adds exactly the two expected networking
  functions; no existing schema object changes.
- Group creation, owner membership, invitation acceptance, and expiry rejection
  work against that live-schema copy using synthetic accounts.

### Authorized reconciliation

The owner subsequently approved applying the Cards migrations. The reconciliation
is explicit and preserves existing records:

- `0021` adopts all four live owner-metadata columns with `ADD COLUMN IF NOT EXISTS`.
- `0022` restores the intended event default, non-null rule, and allowed-value
  constraint. The read-only preflight found all 1,484 existing events valid; the
  migration aborts rather than coercing unexpected classifications.
- The live `v_funnel_daily(day,event,actor_class,n)` is not replaced or renamed.
  The historical wide totals contract is available as `v_funnel_daily_totals`.
  Renaming the historical wide view occurs only on old-shape local/fresh replays,
  not against the differently shaped deployed view. Its dependencies are retained.
- Existing search and retention function definitions are recorded in a new
  migration. The retention function is **not called** and its live grants are
  preserved; browser database roles still have no Cards schema usage.
- ACL serialization is sorted with C collation for accurate comparisons across
  database locales. Actual permission changes still fail the comparison.
- All 20 tracked applied migration hashes match. Two older unmatched migration
  history records from October 9 are preserved unchanged, not deleted or rebased.

The actual live schema-only copy, including its existing migration history,
successfully applies all three pending migrations and converges with a clean
PostgreSQL 17 replay. Existing rows, owner preferences, daily-view OID/definition,
and dependent reads are preserved in the rehearsal. The authorized drift repair
preflight rejects any difference outside the exact reviewed Cards object list;
the rehearsal passes the unfiltered drift check. Live application must also pass
that full check.

### Live application — 2026-10-17

Applied `0020_network_atomic_operations`, `0021_reconcile_owner_metadata`, and
`0022_reconcile_cards_live_contracts` in one Cards-only Drizzle transaction, using
the owner's exported connection without printing credentials. Lock timeout was
five seconds and statement timeout was thirty seconds.

Post-application verification:

- **No drift: 1,164 catalog entries match** a full clean PostgreSQL 17 replay.
- Cards is applied through `0022`; no Cards migrations remain pending.
- All **20/20 Cards table row counts are identical** before and after application.
- All earlier Cards history entries, including the two legacy entries, remain
  unchanged. Only the three new migration records were appended.
- Identity and Persona migration histories are unchanged.
- The deployed analytics view's OID and definition are unchanged.
- Both new network RPCs are visible through Supabase/PostgREST, remain service-only,
  and browser roles still have no Cards schema usage.
- Existing dev and production Cards API health endpoints both return HTTP 200.
- All 19 database tests pass; Cards API remains at its known two X-bot failures,
  with 390 tests passing and no new failures.

The shared database is now ready for this feature. No application was merged or
deployed by the migration task. PR #68 targets `dev` and remains unmerged; the
next step is squash-merge and dev deployment when authorized. Production app code
was not deployed, but the database changes are live for both environments because
they share the same Cards schema.
