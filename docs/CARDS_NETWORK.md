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
Both migrations are expand-only and must be applied before deploying this API.

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

The read-only check found `0019_cards_network` already applied and `0020` pending.
The drift gate did **not** pass: older Cards objects differ from their tracked
migrations (owner-digest columns, `card_events.actor_class`, the people-search
functions, and `v_funnel_daily`). No shared migration was applied in this fix pass.
Review that drift before applying `0020` or deploying this API; do not delete the
extra columns or rewrite old migrations as part of the networking rollout.
