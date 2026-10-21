# Cards-native network

Cards owns the connection graph for verified Cards. Persona is not involved in
connection requests, DMs, groups, or the Cards MCP network tools.

## Rules

- Both sides must have a claimed, published Card linked to the shared aafo
  account.
- A connection starts as `pending`; only the receiving Card can accept or
  decline it.
- There is one connection row per pair of people, and a decided one is final:
  a second request returns the existing row whatever its status, and only
  `pending` can be accepted or declined. So `declined`, `revoked` and
  `blocked` can never become a new request, and the UI does not offer one
  (status reports `can_connect: false` with a reason).
- DMs are available only after `accepted`.
- Group invitations are sent only to accepted connections and do not create
  membership until the invitee accepts.
- Cards web and authenticated MCP use the same Cards API and tables.
- Invitations expire after seven days. Acceptance checks expiry, connection
  status, membership, and group capacity in one transaction.
- Messaging v2 (migration `0023`) adds a per-conversation `seq`, idempotent
  `client_id` sends, read cursors, inbox summaries, and Realtime Broadcast on
  private `cards:dm:*`, `cards:group:*`, and `cards:user:*` topics. The inbox,
  a message page, a send, and a read receipt are each one service-only RPC.
- The v2 web UI is behind the server-side `FEATURE_NETWORK_V2` flag (or the
  `/network?v2=1` preview query). The old UI remains the fallback until the
  migration and Realtime policy are verified. The old endpoints keep their
  response shapes for the authenticated MCP tools.

## Surfaces

- Cards web: `/network` (legacy) and `/network?v2=1` (preview). v2 also takes
  `?c=<connection id>`, which opens that conversation once the inbox loads
  (an accepted DM, or the Requests tab for a pending request); the signed-out
  redirect keeps it in `next`. The legacy inbox ignores it.
- Card profile: a Connect / Message button in the hero (under the name; at the
  top of the actions on an edition card). It shows what can work for the viewer:
  Connect (with an optional note), Requested, Accept, or Message
  (`/network?c=<id>`). Never shown on your own Card.
- Start a connection (v2): a name-or-handle combobox over
  `GET /people/suggest?q=`; typing an exact handle and sending still works.
- Cards API: `/cards/network/*`, including `GET /inbox`, message cursors
  (`before_seq` / `after_seq`), idempotent `client_id` sends, and `POST /read`
- Cards API people lookup: `GET /people/suggest?q=` (claimed, published Cards
  by handle or name, with the caller's connection to each; public Card data
  only) and `GET /connections/status?handle=` (`{self}` or `{connection,
  can_connect, reason}`; it reports state and never 409s for a caller with no
  Card)
- Cards API group memory: `GET/POST /groups/{id}/memory` (summary, facts,
  semantic search, Remember) and `GET/PUT /agent-preferences`
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
reviewed older drift while preserving the live analytics view.
`0023_network_messaging_v2` adds message sequences, idempotency keys, read
cursors, inbox summaries, and Realtime Broadcast triggers. **Apply `0023`
before deploying the v2 API code**; the new endpoints call its RPCs.
`0026_group_memory_agent_replies` adds group summaries/facts, message
remembering, durable agent jobs, and the group-memory/agent RPCs. It is
additive and was applied to aafo on **2026-10-21** together with the pending
`0024` and `0025` Cards migrations. `0027_group_memory_followups` fixes the
read cursor for assistant replies, stuck-job recovery, retry state, memory
broadcast noise, and assistant-reply remembering.
`0028_agent_reply_limit` raises the stored length of an assistant reply from
4000 to 8000 characters. It was applied to aafo on **2026-10-21**; see
[Long replies, streaming and sources](#long-replies-streaming-and-sources-migration-0028).

Test the full Cards migration history and concurrent invitation decisions on a
disposable local Postgres with pgvector (never set this to Supabase):

```bash
cd packages/db
CARDS_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5559/postgres npm test
```

## Messaging v2 (migration 0023)

- `dm_messages` / `group_messages` get a per-conversation `seq` assigned under
  the parent row lock, plus a nullable `client_id` unique per sender and
  conversation. Retries return the stored row instead of inserting twice.
- `dm_read_state` / `group_read_state` hold `last_read_seq`. Unread is
  `message_count - last_read_seq`, so the inbox does not count history.
- `dm_threads` / `groups` carry the last-message summary; triggers keep it
  current for every writer, including MCP.
- `cards.network_inbox`, `network_dm_messages`, `network_send_dm`,
  `network_group_messages`, `network_send_group_message`,
  `network_mark_read`, and `network_group_members` are service-only.
- Database triggers publish private Realtime events. The browser subscribes
  with the user JWT; `cards.network_can_subscribe` authorizes the topic.
  Browser roles still have no table grants in `cards`; the only new grant is
  schema usage for that boolean function.
- Before applying, audit existing policies on `realtime.messages`
  (`select * from pg_policies where schemaname = 'realtime' and tablename = 'messages'`).
  A broad `USING (true)` policy from another feature would bypass the
  `cards:*` topic checks; remove or scope it first. Also confirm Realtime
  private channels are enabled in the project.
- `realtime.send` failures are caught and logged. Realtime is delivery, not
  storage; clients catch up with `after_seq` on reconnect.
- Apply `0023` before deploying API code that calls the new RPCs. The API and
  old endpoints remain backward compatible.

## Group memory and Card assistant replies (migration 0026)

- The group conversation is **not** copied into memory. Agents get the last
  `GROUP_MEMORY_RECENT_MESSAGES` messages (default 50) as raw context.
- `cards.group_memory` stores only a rolling **summary** and durable **facts**.
  A member can press **Remember** on a message; that message becomes a fact and
  is highlighted in the Cards accent colour for everyone in the group.
- The summarizer runs every `GROUP_MEMORY_SUMMARY_EVERY` new messages (default
  30), folds the previous summary into a new one, and extracts up to six durable
  facts. Embeddings are filled asynchronously by the same worker.
- Typing `@` in the group composer opens a member picker; choosing a member
  inserts their Card handle. Messages that start with **Remember** are saved to
  group memory automatically and highlighted in the accent colour, in addition
  to the per-message **Remember** action.
- `@handle` in a group message queues that member's **Card AI assistant**, not
  the Persona agent. The assistant gets the recent messages, the group
  summary/facts, and only that member's approved public memory facts. It can
  call tools for semantic group-memory search, more recent messages, another
  member's public memory, group facts, and the member list.
- Replies are stored with `sender_kind='agent'` and `agent_for_user_id`. The UI
  puts a reply on its owner's side: your own assistant is on the right under a
  **Your AI assistant** label in its own bubble style, and everyone else's is on
  the left as **AI assistant for <name> @handle** with the owner's photo and a
  bot badge. Replies render as markdown (no raw HTML; remote images show as
  links); human messages stay plain text. Agent messages never trigger more
  agent jobs.
- Avatars in the network UI go through the first-party `/api/img` proxy (the
  same one the profile page uses), pass the Card handle so an expired LinkedIn
  photo triggers a refresh, and fall back to the initial if the image still
  fails. The inbox and member payloads come from SQL (`network_card_payload`),
  so a GitHub fallback photo there would need a migration.
- Realtime events: `agent_typing` (`pending`, `running`, `done`, `failed`),
  `agent_stream` (the reply as it is being written, below) and `memory`
  (summary/fact saved, message remembered).
- Flags: `FEATURE_GROUP_MEMORY` and `FEATURE_GROUP_AGENT_REPLIES`, both off by
  default. They require `packages/db` cards migration `0026`. Apply the
  migration only with explicit approval; the migration is additive and does not
  touch Persona.
- The web cache is client-side: the inbox and per-conversation pages are kept
  in memory and IndexedDB per signed-in user. Revisiting a conversation renders
  the cached messages immediately and fetches only `after_seq` deltas. The last
  80 messages per conversation, 30 conversations, and a 7-day TTL are kept.
- `FEATURE_GROUP_MEMORY` gates the memory endpoints; the web UI still renders
  the current conversation if memory is disabled. `FEATURE_GROUP_AGENT_REPLIES`
  gates mention queueing and the worker.

## Long replies, streaming and sources (migration 0028)

The assistant stays terse by default and can write a full answer when asked,
and the group watches that answer being written.

**Short by default, long when asked.** A tagged message gets one to four plain
sentences. If it asks for a plan, steps, a strategy, a comparison or a detailed
explanation, the assistant writes a complete answer in Markdown (headings,
numbered or bulleted lists, bold), and the web UI renders it. The prompt tells
the model its word budget (`GROUP_AGENT_MAX_REPLY_CHARS / 6`). Replies are no
longer stripped of Markdown; only whitespace is tidied. Anything over the cap is
cut at the last paragraph break, else the last sentence end, else the last word,
never mid-word. Group summaries (memory) are still cleaned to plain text.

**Configuration** (`services/cards-api`, also in `.env.example` and
`.env.prod.example`):

| Variable | Default | Meaning |
|---|---|---|
| `GROUP_AGENT_MAX_TOKENS` | `1800` | Model output ceiling per call. |
| `GROUP_AGENT_MAX_REPLY_CHARS` | `4000` | Longest stored reply. **Keep at 4000 until 0028 is applied, then set 8000.** |
| `GROUP_AGENT_LLM_TIMEOUT` | `120` | Seconds per model call (was 60); a long answer takes about a minute. |
| `FEATURE_GROUP_AGENT_STREAMING` | `true` | Stream the reply to the group. Does nothing without `SUPABASE_URL` + `SUPABASE_SERVICE_KEY`. `false` goes back to one plain model call and no `agent_stream` events. |
| `FEATURE_AGENT_DEBUG_SOURCES` | `false` | **Dev only.** Adds the context and tool calls behind a reply to `agent_stream`. |

**Migration `0028_agent_reply_limit`** replaces
`cards.network_send_agent_group_message` with its `0026` definition (`0027` did
not touch it) changing only `left(btrim(...), 4000)` to `8000`. Signature,
service-only grants and `client_id` idempotency are unchanged; human DMs and
group messages keep their 4000 limit, and so do group facts and summaries. It is
expand-only, was rehearsed on a disposable local Postgres 17 with pgvector (the
test in `packages/db/test/cards-network-sql.test.ts` fails against `0027` and
passes against `0028`). Rollout:

1. Apply `0028` with explicit approval (`npm run db:migrate -- --project cards`
   from `packages/db`, dry run first). **Done 2026-10-21.**
2. Set `GROUP_AGENT_MAX_REPLY_CHARS=8000` and restart cards-api.

Never raise the cap before step 1: the function would cut the stored reply at
4000, mid-word, after the stream already showed more. The code defaults to 4000
precisely so it can ship before or after the migration.
Rollback: set `GROUP_AGENT_MAX_REPLY_CHARS=4000` and restart, then run the
rollback SQL in the header of `0028_agent_reply_limit.sql` (the `0026` body).
Replies already stored keep their length; only new writes are capped again.

**Streaming (`agent_stream`).** The worker calls the model with `stream=true`
and, while text is generated, POSTs snapshots to Supabase Realtime's REST
broadcast endpoint (`{SUPABASE_URL}/realtime/v1/api/broadcast`, service key as
`apikey` and bearer, one private message on topic `cards:group:<group_id>`, no
`realtime:` prefix). They reach the same members who may subscribe to the topic
(`network_can_subscribe`) and receive the saved message. A tool step ends in
tool calls and continues as before; if streaming is unsupported or fails before
any output, the worker falls back to the plain call.

| Field | Meaning |
|---|---|
| `job_id` | The job. The saved reply carries it as its `client_id`, which is how the UI matches them. |
| `group_id`, `user_id`, `message_id` | The group, the member whose assistant is writing, and the tagged message. |
| `attempt`, `seq` | Ordering. A retried job has a higher `attempt`; `seq` restarts within it. A stale snapshot is ignored. |
| `text` | The **full** text so far, never a delta, so a dropped or repeated snapshot costs nothing. An empty `text` after text was shown is a reset (the step turned out to be tool calls). |
| `done` | `true` on the last snapshot, whose `text` is exactly what is about to be saved. |
| `status` | `thinking`, `tool`, `writing` or `done`. |
| `sources` | Only with `FEATURE_AGENT_DEBUG_SOURCES`; see below. |

Snapshots are throttled to one per 200 ms (a snapshot is skipped while one is in
flight), with forced ones for status changes and the final text. It is best
effort: a failed POST is logged, three failures in a row stop broadcasting for
that job, and nothing fails the job. The durable write is unchanged (same
`client_id` = job id), so a reload or a missed stream still shows the final
message. Streaming itself needs no migration.

**Web.** `ConversationPane` subscribes to `agent_stream` and keeps one stream
per job (`src/lib/agent-stream.ts`, pure; its `node:test` file runs with
`npx tsx --test src/lib/agent-stream.test.ts` from `apps/cards-web`, like
`profile-quality.test.ts`). A streaming bubble
sits at the bottom on the owner's side like a finished reply, with a caret and
"Writing…", replacing that user's "is thinking" row once there is text (a tool
step shows "Looking things up…"). It is dropped as soon as a message with the
same `client_id` is in the conversation, whether that arrived as the realtime
`message` event or in a fetched page (both carry `client_id`), and a snapshot
that straggles in afterwards never brings it back. A retry (`agent_typing`
`pending`) or a failure clears it; a failure keeps the existing error line. At
the bottom the view follows the stream; scrolled up, the "New messages" pill
shows.

**Where did this come from (dev only).** With `FEATURE_AGENT_DEBUG_SOURCES=true`,
tool-step snapshots and the final snapshot carry `sources`: what the assistant
was given (number of recent messages, whether a group summary existed with a
short preview, saved facts, the tagged member's public facts, each with short
previews) and each tool call with its arguments and a one-line result summary.
The trace is capped at about 6 KB. The UI shows it as a collapsed "Sources
(dev)" panel under the streaming bubble and under the saved reply. **Never
enable this in production:** every member of the group receives it, including
the tagged member's approved public facts and the group summary. With the flag
off no `sources` leave the server. Sources are not stored anywhere: no schema
change, and in the browser they live in memory only (`network-cache`, outside
what is written to IndexedDB), so they survive switching conversations but not a
reload.

**Not verified against a real Supabase project.** The request shape was taken
from `@supabase/realtime-js` 2.117.2 (`RealtimeChannel.js`) and is covered by
unit tests with a fake HTTP transport and by Playwright with injected events
(local e2e runs have no Realtime socket, so `use-network-realtime` also accepts
a `zynd:test-broadcast` window event while `NEXT_PUBLIC_DISABLE_REALTIME=true`).
Before relying on it in dev, confirm that the project's Realtime accepts the
service key on `/realtime/v1/api/broadcast` (a legacy JWT key works; a newer
non-JWT secret key may not) and that private messages from it reach the
`cards network can receive broadcasts` policy's subscribers. If it does not, the
log shows `agent_stream broadcast failed` three times per reply and replies
arrive as before.

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
- Messaging v2 rollout order: (1) apply `0023` after review, (2) deploy
  cards-api, (3) deploy cards-web with `FEATURE_NETWORK_V2=false`, (4) verify
  `/network?v2=1`, (5) set `FEATURE_NETWORK_V2=true` and restart cards-web.
  Rollback is step 5 reversed; the additive tables and message data stay.
  Do **not** deploy cards-api before `0023`, because the old endpoints now
  read through `network_inbox`.
- Group memory rollout: (1) confirm `0024`/`0025` are applied, (2) apply
  `0026` after review, (3) deploy cards-api with both group flags false,
  (4) deploy cards-web with both group flags false, (5) set
  `FEATURE_GROUP_MEMORY=true` and verify Remember/search, (6) set
  `FEATURE_GROUP_AGENT_REPLIES=true` and verify a tagged assistant reply and
  the typing indicator. Rollback is the reverse flag order; the additive
  tables and saved facts stay. The client cache needs no flag and ships with
  the v2 UI.
- Streaming and long replies: deploy cards-api and cards-web together (an
  older web ignores `agent_stream` and shows the saved reply as before; an
  older API sends nothing). The kill switch is
  `FEATURE_GROUP_AGENT_STREAMING=false` on cards-api. Long replies need no
  code flag: raise `GROUP_AGENT_MAX_REPLY_CHARS` to 8000 only after `0028` is
  applied (see above). Leave `FEATURE_AGENT_DEBUG_SOURCES` off everywhere
  except a dev box you control.

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

### Live application — 2026-10-20 (messaging v2)

Applied `0023_network_messaging_v2` to aafo through the session pooler. Only
that Cards migration was pending. Post-application verification:

- All existing DM and group message rows have a non-null `seq`; message counts
  and last-message summaries are backfilled.
- Read cursors were created for existing DM participants and group members, so
  old conversations start read.
- The only policy on `realtime.messages` is
  `cards network can receive broadcasts`, scoped to `authenticated` and
  `cards:*` topics.
- `authenticated` has schema usage and execute on
  `cards.network_can_subscribe(text)` only. It has no table grants in `cards`,
  and `cards.purge_card_events` is not executable by browser roles.
- Safe service-role smoke calls to `network_inbox` and `network_dm_messages`
  return the expected empty/404 payloads.
- Full drift check against prod: **No drift: 1,295 catalog entries match**.
- Cards API and Cards web were not deployed by this migration step. Apply the
  code in the rollout order above; the migration is additive and the currently
  deployed API keeps working.

### Live application — 2026-10-21 (assistant reply limit, 0028)

Applied `0028_agent_reply_limit` to aafo through the session pooler, with the
owner's approval, after the code (#84) was merged to `dev`. The dry run listed
only that Cards migration as pending; identity and persona had none.

- Cards is applied through `0028`; nothing is pending in any history.
- Full drift check against a clean replay: **No drift: 1,504 catalog entries
  match.** The count is unchanged because the function is replaced, not added.
- cards-api still runs with `GROUP_AGENT_MAX_REPLY_CHARS=4000` until that env
  var is raised to 8000 and the service restarted; until then nothing changes
  for users.

### Live application — 2026-10-21 (group memory, 0026)

Applied the three pending Cards migrations through the session pooler:
`0024_connection_invites`, `0025_networking_controls`, and
`0026_group_memory_agent_replies`, then the follow-up
`0027_group_memory_followups`. Identity and persona had no pending
migrations and were untouched.

`0027` fixes the tagged member's read cursor on assistant replies, reclaims
stuck `running` jobs after five minutes, keeps retrying jobs `pending` instead
of flashing `failed`, stops embedding backfills from re-broadcasting memory,
and rejects remembering an assistant reply.

Post-application verification:

- Cards has **30** migration records; identity remains **1** and persona **9**.
- `cards.group_memory`, `group_memory_state`, `group_message_memory`,
  `group_agent_jobs`, and `group_agent_preferences` exist.
- `group_messages` has `sender_kind`, `agent_for_user_id`,
  `reply_to_message_id`, and `mentions`.
- All group-memory/agent RPCs and event triggers are present.
- Browser roles have no table grants on the new tables and cannot execute the
  new service-only functions.
- The only `realtime.messages` policy is still
  `cards network can receive broadcasts`.
- Full drift check against a clean replay: **No drift: 1,504 catalog entries
  match.**
- Application code and feature flags were not deployed by this migration step.
  Use the group-memory rollout order above; both flags stay off until the code
  is deployed and verified.

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