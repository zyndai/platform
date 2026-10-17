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
membership, invitation, and group-message tables. The migration is expand-only;
it must be reviewed and applied before enabling the feature in a deployment.
