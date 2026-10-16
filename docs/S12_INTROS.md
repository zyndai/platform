# S12: human intro requests

S12 now has a local implementation of **request an intro → owner decides →
optionally propose a call**. Persona owns the connection and approval state;
Cards presents the request form and owner inbox.

Feature flags default to off. The shared database migrations have **not** been
applied, and the live identity cutover has **not** been confirmed. Local tests
use mocked services and a disposable Postgres, not production accounts.

## What this release includes

- Human requests on claimed, published cards whose owner has an active linked
  Persona and a verified Memory account link.
- A verified shared Supabase session for the requester. The requester also needs
  an active Persona and linked Memory account, but does not need their own card.
- Received/sent inboxes in Cards at `/intros`, plus received requests on S10
  `/home`. Persona's inbox links to `/dashboard/intros` for the same requests.
- Accept, decline, and block decisions. Approving a connection does not grant
  meeting permission automatically. Requesting account/posting/private-profile
  access through the form is unsupported and rejected.
- An optional owner-selected 20-minute call proposal, stored in Persona's
  existing `agent_tasks` meeting flow. Booking still requires the existing
  participant confirmations and calendar setup.
- Owner allow/deny rules in Persona. An allow list restricts new requests to
  listed people; it does not approve requests automatically.
- Durable submission keys, atomic decisions and audit records, per-requester
  and per-card daily limits, and retry-safe activity projections.
- Real `intro_request` and `intro_accepted` events when S04 collection is on.
  S10 digests include the pending intro count and an authenticated review link.
- Authenticated MCP `list_intros`, requiring `cards:read` or the legacy owner
  scope. This is read-only. Public MCP does not offer `request_intro`, and no
  assistant approval action is enabled in this human-only release.

This release proposes the time the owner selects. It does not automatically
search both calendars for free slots or introduce a new email-sharing permission.
Those remain later additions to the broader convention.

## Identity and auth prerequisites implemented locally

The canonical `zynd_uid` in this path is the shared Supabase `auth.users.id`.
Cards uses `owner_user_id`, Persona uses `persona_agents.user_id`, and Memory
checks `users.supabase_user_id` through its protected HTTP identity endpoint.
Missing links, duplicate links, legacy issuers, and contradictory service
responses fail closed. There is no email/name fallback and no automatic backfill.

Persona auth corrections cover the issues in [the readiness audit](S12_READINESS.md):

- Callback bearer tokens must exist, be unexpired, and belong to the addressed
  user and task. Signed callbacks must also pass signature/replay checks and
  match the registered peer. Unsigned peers remain supported with a valid
  bound callback token. Task-id-only correlation is refused. Credential/body
  logging was removed from this handler.
- An unconfigured Telegram webhook refuses processing. No live webhook
  registration or secret rotation was performed.
- The receiving owner controls permissions. Direct client changes to thread
  security fields and meeting decisions are blocked by database triggers;
  Persona web uses authorized API transitions instead.
- Pending S12 connections cannot be used for additional messages or meeting
  proposals before approval. Revoked meeting permission blocks later proposals, ticket acceptance, and
  entry into calendar booking.

The S09 remote MCP transport now accepts granular scoped tokens without requiring
the legacy `user` scope; each tool still enforces its own scope.

New S12 foreign keys preserve the existing explicit account-deletion flow.
Deleting a conversation removes its intro and related audit rows; deleting an
account removes its intro rules and Cards projections. Meeting-ticket deletion
clears the optional ticket reference. Migration itself deletes no data.

The new permission API and triggers affect existing Persona connections too.
**Auth and shared-schema review are required before deployment.** Turning off
S12 does not undo these security fixes.

## Configuration

Configure these only in a reviewed test deployment with linked test accounts:

| Service | Setting |
| --- | --- |
| Cards API | `SUPABASE_DB_SCHEMA=cards` |
| Cards API | `AAFO_ISSUER=<shared SUPABASE_URL>/auth/v1`; must match the database project |
| Cards API | `FEATURE_S12_INTROS=true` |
| Cards API | `PERSONA_API_URL=http://localhost:8000` |
| Cards API | `PERSONA_SITE_URL=http://localhost:3000` |
| Cards API and Persona API | Matching, dedicated `CARDS_INTRO_SERVICE_TOKEN` |
| Persona API | `FEATURE_S12_INTROS=true` |
| Persona API | `S12_REQUESTER_DAILY_CAP=10`, `S12_CARD_DAILY_CAP=20` by default |
| Memory | `S12_IDENTITY_ISSUER=<shared SUPABASE_URL>/auth/v1` |
| Memory, optional owner MCP reads | `FEATURE_S12_INTROS=true`, `CARDS_API_URL=http://localhost:8002` |
| Both web apps | `NEXT_PUBLIC_FEATURE_S12_INTROS=true`; rebuild for production |

The existing `MEMORY_SERVICE_TOKEN` must match between Cards and Memory.
Daily limits reset on UTC day boundaries. Limits and allow/deny decisions are
enforced in Postgres, including across multiple API workers.

Do not put `CARDS_INTRO_SERVICE_TOKEN` into `INTERNAL_SERVICE_KEYS` or a
`NEXT_PUBLIC_*` variable. It is a separate credential for the narrow intro
bridge, not a general Persona service credential.

Required new migrations in `packages/db`:

| History | Migrations |
| --- | --- |
| Persona | `0002_s12_intro_requests`, `0003_s12_intro_operations`, `0004_s12_audit_details`, `0005_s12_deletion_compatibility`, `0006_s12_meeting_grants` |
| Cards | `0012_s12_intro_projection`, `0013_s12_intro_events`, `0014_s12_deletion_compatibility` |

Follow [packages/db/README.md](../packages/db/README.md). Apply the reviewed
schema before deploying code that uses the new permission RPC. The actual
shared database apply/cutover is a separate human-approved action.

## API and state ownership

| Surface | Purpose |
| --- | --- |
| `GET /cards/by-handle/{handle}/intro-eligibility` | Public eligibility only; no private owner identity or inbox data. |
| `POST /cards/by-handle/{handle}/intro` | Verified human request with `why`, `asks`, and `idempotency_key`. |
| `GET /cards/mine/intros?outgoing=true&offset=0` | Owner/requester-scoped list; pages of 100, with older-request controls. |
| `POST /cards/mine/intros/{id}/respond` | Receiving-owner decision or time proposal. |
| `GET /api/intros` | Persona owner's inbox; `outgoing=true` selects sent requests. |
| `POST /api/intros/{id}/respond` | Same authoritative Persona decision. |
| `/api/intros/rules/mine` | Owner's allow/deny preferences. |
| `/api/intros/internal/*` | Dedicated Cards-to-Persona bridge. |
| `GET /v1/service/identity/{uid}` | Memory service-only UUID linkage check. |
| `POST /internal/owner-intros` | Memory-to-Cards read bridge for authenticated owner MCP. |

The first supported asks are `message` and `meeting`. New requests start with
all four Persona permission flags off. The owner may grant only meeting
coordination in this release; private-profile, calendar-query, and account-posting
permissions stay off. Existing A2A tasks freeze the thread permission snapshot.

Persona stores the full request and audit. Cards stores only ids, handle,
participants, state, and timestamps. Cards reconciles state when an inbox or
owner digest is read. Persona decisions therefore appear in Cards on refresh.
Retries repair a missing Cards projection without creating another connection
or duplicate event. Older pending snapshots cannot overwrite a later decision.

Only one connection is supported for a given Persona pair. If a thread already
exists, the requester is directed to continue in Persona; S12 does not reset a
declined, blocked, revoked, or existing accepted connection.

## Verification

The added tests cover identity boundaries, human-only initiation, owner decisions,
callback/Telegram auth, direct-client permission escalation, concurrent retries,
limits, allow/deny rules, pending-message refusal, permission revocation, audit
records, and exactly one projection/event per request or acceptance.

The SQL rehearsal uses **only** this disposable target:

```text
S12_TEST_DATABASE_URL=postgresql://<local-user>@127.0.0.1:5549/s12_rehearsal
```

The test refuses another host, port, or database name. It builds the full Persona
migration history and a minimal Cards fixture; it does not replace full Cards
pgvector/drift validation in database CI.

Cards browser tests use local fixture APIs/auth/Memory and exercise request,
approval, time proposal, failed-send recovery, and unclaimed-card eligibility.
They do not prove a live cross-service identity cutover or calendar integration.

Follow [the manual scenarios](S12_MANUAL_TESTING.md) after the reviewed test
environment is configured. No real intro or email has been sent by this work.

## Local verification results (2026-10-13)

These automated checks ran locally with dummy credentials/mocked external services:

| Check | Result |
| --- | --- |
| Persona API, including disposable Postgres regressions | 353 passed |
| Cards API | 270 passed, 11 skipped; same 11 failures as the configured pre-change baseline |
| Memory non-integration suite | 258 passed, 87 deselected; same 12 failures as the configured pre-change baseline |
| Cards browser suite, including S10 regression coverage | 22 passed |
| Both web production builds and TypeScript checks | Passed |
| Database migration lint, TypeScript, Drizzle journals | Passed |
| Full Persona migration history in a fresh local database | Passed; rehearsal transaction rolled back |

The local Cards/Memory baseline counts differ from the root guide's generic
counts because of this checkout's environment and installed dependency versions.
Their failing test names were compared before/after; no new failures remain.
Frontend lint retains existing violations outside the new S12 files. New S12
frontend files passed lint. No production migration, real email, live intro, or
calendar booking was executed. Full Cards pgvector/drift validation remains a
required database CI check before deployment.
