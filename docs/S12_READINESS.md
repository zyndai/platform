# S12 readiness and prerequisite work

Assessment date: 13 October 2026.

After this initial assessment, the user authorized implementing the prerequisites
locally and then human-only S12. The issues below describe the starting revision;
local corrections and the resulting feature are documented in
[S12 intros](S12_INTROS.md). Live identity cutover and shared-database application
remain unconfirmed/unperformed.

**S12 is not ready to build against the shared environment yet.** S09 and S11
code are present, but shared identity is unconfirmed and the Persona auth review
found remaining issues. This assessment does not implement S12 or approve a rollout.

The [S12 convention](../conventions/S12-intro-request-via-persona.md) states:

> Status: spec only — do not start until the gates below are cleared.

## Decisions and scope

- The user selected **signed-in humans first** for intro initiation.
- AI assistants must not initiate or accept S12 intros in that initial release.
- No commits or pushes without the user's approval.
- No application of migrations to the shared database without human approval.
- Existing `.gitignore` edits and the two explanation/testing documents are preserved.

## What is already present

| Prerequisite | Repository evidence | Remaining uncertainty |
| --- | --- | --- |
| S09 assistant identity and scopes | `services/memory/app/services/mcp_clients.py`, `mcp_scopes.py`, `mcp_gate.py`, `tests/test_s09.py` | Live rollout and connector behavior were not verified. |
| S11 public Cards MCP | `services/memory/app/cards_public_mcp.py` | Intro action is still a disabled stub; it should remain unavailable for assistant initiation in the human-only release. |
| Persona route guards | `services/persona-api/api/guards.py`, `tests/test_guards.py`, `tests/test_route_guards.py` | Declaring a guard does not prove the action's permissions are sufficiently narrow. |
| Identity linkage fields | Cards `owner_user_id`, Persona `persona_agents.user_id`, memory `users.supabase_user_id` | The user could not confirm the shared aafo identity cutover. Existing fields alone do not prove deployed linkage is correct. |

## Persona auth audit findings

Reviewed local `main` at `36612ed6e8e383c569a34c1df1008b059585a5a4` and the
working branch at `91bdb8de91149ba965d9c3bbd5f46cfb199aaeab`. The four relevant
files (`api/guards.py`, `api/telegram.py`, `api/persona.py`,
`agent/a2a_router.py`) have no differences between those revisions. This is an
audit of the available local refs, not a claim about a newer remote or deployed revision.

### 1. Inbound A2A callbacks can bypass identity checks

In `services/persona-api/agent/a2a_router.py:1726`, invalid signature verification
is caught and processing continues. Callback correlation can fall back to a
task id without the issued callback bearer token. User and peer mismatches are
logged but allowed at lines 1775–1784. Part of the bearer header is also logged.

A local reproduction used an unsigned request, no callback token, and a mock
callback belonging to a different user. The handler returned HTTP 200 and
recorded the push. DB writes and background fetches were mocked.

**Required correction:** Validate the accepted callback authentication contract,
reject invalid signatures, enforce callback ownership and peer binding, and remove
credential logging. Task ids can help correlate a request after authentication;
they must not substitute for authentication. If unsigned bearer-authenticated
peers must remain compatible, that policy must be explicit and enforce token
ownership rather than accepting all verification failures.

### 2. Telegram fails open when the secret is absent

In `services/persona-api/api/telegram.py:934`, the secret check only runs when
`TELEGRAM_WEBHOOK_SECRET` is configured. Otherwise an arbitrary caller can submit
a message for a linked chat.

A local reproduction with an empty configured secret returned HTTP 200 and
invoked a mocked message processor without a secret header.

**Required correction:** Refuse to process webhook messages when the secret is
not configured; continue rejecting missing or wrong headers when it is configured.
Any live webhook registration or secret rotation remains a separate human action.

### 3. Either participant can grant connection permissions

`services/persona-api/api/persona.py:724` requires thread participation, then
updates a shared permission object. It does not verify who owns the permissions
being granted. A requester must not be able to grant access to the recipient's
accounts, private profile, or calendar.

A local reproduction overrode the participant guard with a requester identity
and successfully enabled `can_post_on_my_behalf` in a mocked thread.

The baseline `dm_threads` RLS also allows participant updates. A REST-only fix
would therefore be incomplete: clients can update the row directly. Persona web
currently accepts connections with a direct Supabase update.

**Required correction:** Define whose permission grant each connection stores;
enforce that owner at the API and database boundaries. Restrict direct writes to
security-sensitive fields and move approval/permission changes to authorized,
atomic transitions. Preserve ordinary messaging and mode controls.

## Minimum identity work before the intro flow

Use one verified canonical identity across products. The existing shared aafo
`auth.users.id` is a candidate for the stable `zynd_uid`, subject to confirmation
of the cutover and the intended identity architecture.

1. Confirm which Supabase issuer is authoritative in the target environment.
2. Verify Cards ownership links to that user's id, Persona's agent belongs to
   that id, and memory resolves that id through its service HTTP API.
3. Reject legacy-project tokens, missing links, and contradictory links for
   S12. Never silently repair ownership by matching a name or email.
4. Provide a read-only readiness check and a local fixture covering the complete
   linkage, an absent link, and a conflicting link.
5. Any live identity backfill or cutover needs maintainer review and explicit
   authorization. Do not infer migration state from the presence of source files.

## Implementation order once the gates are cleared

1. Run relevant baselines and rehearse additive migrations on disposable data.
2. Create authenticated intro intake in Cards for eligible claimed, public
   cards with an active linked Persona; derive requester identity from the session.
3. Add a narrowly authenticated Cards-to-Persona service endpoint that creates
   the connection request, permission snapshot, and audit trail atomically.
4. Add owner approval/decline and time suggestions using Persona's existing
   connection and meeting services. Cards remains a client of that workflow.
5. Add the public request form, requester status, and the owner inbox in Cards
   and Persona. Both interfaces must show the same decision.
6. Add limits per requester/card, owner allow/deny controls, retry/replay protection,
   and durable request/acceptance events for S04/S10.
7. Add digest links to authenticated review; opening an email link must not
   accept an intro automatically.
8. Test ownership, permissions, duplicate submissions, service failures,
   concurrent decisions, and end-to-end request → approval → meeting proposal.
9. Keep flags off until schema/identity readiness and human review are complete.

Auth and shared schema changes require special review under
[AGENTS.md §6](../AGENTS.md). Schema work belongs in `packages/db`, including
any Persona RLS changes; frozen service SQL folders must remain untouched.

## Checks performed

- Persona baseline: **318 passed**, with 1 warning. The suite includes guard and
  route declaration tests. These passing tests do not cover away the reproduced issues.
- Auth audit: **three issues reproduced** with mocked DB/network calls. No real
  messages, callback fetches, or database writes occurred.
- Cards baseline with the locally loaded configuration: **259 passed, 11 failed,
  11 skipped**. Failures existed before any application-code change, including
  X-bot tests and older mocks incompatible with enabled S10 paths.
- Cards web: TypeScript passed; lint has **1 existing error** in
  `McpConnectPanel.tsx` and 25 warnings.
- Persona web: TypeScript passed; lint has **24 existing errors** and 31 warnings.
- No live identity checks, deployments, SQL, secret changes, commits, or pushes.
