# Persona Groups — rollout notes

Living checklist of things that must be done outside the code repo before
Persona Groups is production-ready, and the scope of each shipped phase.

## What's in the repo

### Phase 1 — human chat MVP (commit `3e3266a`)
- 3 tables in `backend/db/patch_add_persona_groups.sql`
- 14 routes in `backend/api/groups.py`, mounted at `/api/groups`
- Sidebar nav + 4 pages (`/dashboard/groups`, `/dashboard/groups/[id]`,
  `/dashboard/groups/[id]/settings`, `/g/[slug]/[token]`)
- Supabase Realtime subscription for `persona_group_messages` filtered
  by `group_id`

### Phase 2 — @-mention persona dispatch (commit `8c77aaa`)
- `backend/agent/group_dispatch.py` — `extract_mentions`,
  `resolve_mentions_to_members`, `dispatch_group_mention`. Routes
  through `handle_user_message(is_external=True, …)` with group
  permissions translated to the existing `external_permissions` shape.
- `POST /api/groups/{id}/messages` parses `@DisplayName` mentions on the
  way in, fires a background `asyncio.create_task` for each resolved
  member, and returns `mentioned_user_ids` for the thinking indicator.
- Replies written back as `channel='agent'` rows with
  `metadata.reason='group_mention'`; realtime delivers them.
- Composer: `@`-typeahead picker (↑↓/Enter/Tab/Esc). Sent messages
  render `@Name` as styled chips; "@you" gets its own highlight.
- "X's persona is thinking…" indicator above the composer, cleared
  when the agent row arrives or after 60 s.

### Phase 5 — discovery, domain auto-join, audit receipts
- `backend/db/patch_add_persona_group_discovery_audit.sql`:
  - `persona_groups.join_domain` column (open groups only).
  - `persona_group_audit_events` table for privacy-sensitive reads.
  - RLS: affected users see their own receipts; owner/admin sees the
    whole-group feed.
- 3 new routes:
  - `GET /api/groups/discover` — open, non-archived groups the caller
    isn't already in. Optional `query` for keyword filtering.
  - `GET /api/groups/auto-join-candidates` — open groups whose
    `join_domain` matches the caller's email domain. Returns the
    invite token so the existing `/by-invite/{token}/join` path
    handles the actual join.
  - `GET /api/groups/{id}/activity?scope=me|all` — audit feed.
    "me" returns the caller's own receipts (any member); "all"
    requires owner/admin.
- Audit logger fires `brief_shared` events from the @-mention
  dispatch path (only when brief content actually crossed the
  boundary) and `calendar_queried` events from
  `GET /availability` for each member whose calendar was read.
  Self-checks are filtered out.
- Frontend:
  - `/dashboard/groups` gains a Discover panel below the user's
    groups, with an "Open to you via @yourdomain" auto-join section
    when applicable. Search + one-click join.
  - Group settings: `Auto-join domain` field appears when visibility
    is open.
  - Group settings: new `Activity` section showing the caller's
    receipts. Owner/admin gets a toggle to view the whole-group feed.

### Phase 4 — group memory / shared constraints (commit `4aa7f83`)
- New table `persona_group_constraints` with three kinds:
  - `fact` — positive context the team has agreed on
  - `rule` — guardrails to avoid (do NOT do X)
  - `voice` — style/tone guidance
- `backend/db/patch_add_persona_group_constraints.sql` — table, index,
  RLS (members read, service-role full). Soft-archive via
  `archived_at` so removed rules stay queryable for audit.
- 4 new routes (`/{id}/constraints` GET / POST and
  `/{id}/constraints/{cid}` PATCH / DELETE). Writes are owner/admin
  only. `MAX_CONSTRAINTS_PER_GROUP = 20` enforced on POST — keeps
  the LLM's working set focused.
- Dispatcher: `dispatch_group_mention` accepts a `group_constraints`
  list. `_format_constraints_block` groups by kind and emits a
  "Group rules — must-follow guardrails" prompt section. Rules
  listed first (model honors earlier-listed instructions more
  reliably), then facts, then voice. Unlike the brief, constraints
  are NOT gated by `can_see_brief` — they're team-wide guardrails
  that apply regardless of asker permissions.
- Right rail gains a Memory tab. Members read; owner/admin can add
  one-liners (with inline help text per kind) and remove existing
  rules. Optimistic remove with rollback on failure.

### Phase 3b — calendar overlay + meeting proposals (commit `7742820`)
- `backend/agent/group_calendar.py`:
  - Concurrent free/busy fan-out via Google Calendar's
    `freebusy.query` (no event titles/attendees cross member
    boundaries — only "busy from X to Y").
  - `find_common_slots` walks the window in N-minute steps with
    business-hours + weekday gating, projected into the viewer's local
    TZ via a passed offset.
- 2 new routes:
  - `GET /api/groups/{id}/availability?start&end&duration_minutes&tz_offset_minutes`
    — gated by the asker's `can_query_calendar`. Returns per-member
    busy blocks and a list of `common_slots` (capped at 12).
  - `POST /api/groups/{id}/meetings` — creates an event on the
    asker's calendar with other members as attendees (Google handles
    invite emails), then posts a `channel='system'` message to the
    group with the meeting metadata.
- Right rail gains a `Schedule` tab: range + duration picker → "Find
  slots" → list of "everyone is free" slots → click to propose →
  modal asks for title/description/location, then sends invites.
- Members without a connected calendar are flagged in the UI and
  excluded from the common-slot intersection so we never claim
  "everyone is free" based on missing data.

### Phase 3a — shared group brief (commit `45bbb88`)
- New columns on `persona_groups`: `brief_doc_id`, `brief_doc_url`
  (`backend/db/patch_add_persona_group_brief.sql`).
- 3 new routes:
  - `POST /api/groups/{id}/brief/init` (owner-only) — creates a Google
    Doc in the owner's Drive, seeded with the group description.
  - `GET /api/groups/{id}/brief` (members) — live-fetched body.
  - `PATCH /api/groups/{id}/brief` (owner/admin) — replaces the body.
- Dispatcher injection: when `can_see_brief` is on for the asker and
  the group has a brief, the doc body is pre-fetched once per turn
  (in `_spawn_mention_dispatch`) and threaded into each target's
  prompt via `dispatch_group_mention(group_brief_content=…)`. The
  prefix labels it explicitly as "shared group brief" so the LLM
  doesn't confuse it with the persona's own per-user brief.
- UI: chat right rail is now a tabbed pane (`People` / `Brief`).
  Brief tab shows the doc body, an "Open in Docs" link, a Reload
  button, and an Edit-in-place flow for owner/admin.

### Phase 2 polish — follow-ups completed
- **Brief gating is now hard, not just behavioral.** `_format_user_brief`
  takes a new `redact_brief` flag. When the asker doesn't have
  `can_see_brief`, the brief Google Doc body is stripped from the
  system prompt entirely — it never enters the LLM's context window
  for that turn. The dispatch prefix also threads an explicit hint so
  the LLM doesn't leak equivalents from memory.
- **Per-member permission toggles** in the group settings page. Each
  non-owner row has an expandable Permissions panel with three
  switches: see briefs of mentioned members, check their calendars,
  and post in the group (mute toggle). Auto-saves optimistically with
  rollback on PATCH failure.
- **Member cap** (`MAX_GROUP_MEMBERS = 15`) enforced in `add_member`
  and `join_via_invite` — keeps the @-mention dispatch fan-out and
  future calendar overlay scope bounded.
- **Owner transfer**: `POST /api/groups/{id}/transfer-owner` plus a
  "Make owner" action on each admin's row in settings. The previous
  owner is demoted to admin in the same call.
- **Group keypair derivation foundation**: `derive_group_seed` and
  `derive_group_keypair` in `zynd_identity.py` (domain-separated from
  agent derivation), plus `build_group_context_claim` /
  `verify_group_context_claim` in `group_dispatch.py`. The
  cryptographic primitives are ready for cross-instance dispatch; the
  routing layer that uses them is still pending (see below).

---

## Pending end-to-end (must do before users see groups)

These are operational items that the code can't do for itself.

### 1. Apply the schema via Prisma
The canonical schema is now `prisma/schema.prisma` — the `backend/db/*.sql`
patches are historical and shouldn't be applied directly on a Prisma-managed
project (they'd duplicate what Prisma generates). See `prisma/README.md`
for the full flow.

```bash
cd webapp
npm install                                      # picks up prisma devDep
# Edit webapp/.env with DATABASE_URL + DIRECT_URL (see prisma/.env.example)

npm run prisma:validate                          # sanity-check the schema
npm run prisma:migrate:deploy                    # tables + indexes + enums
npm run prisma:policies                          # RLS + realtime publication
```

If the existing DB already has these tables (from the legacy .sql patches),
adopt under Prisma without re-creating — see `prisma/README.md` →
"Adopting on an existing database".

What it creates (all 19 public tables):
- Core: `api_tokens`, `chat_messages`, `persona_agents`, `dm_threads`,
  `dm_messages`, `agent_tasks`, `a2a_tasks`, `pending_approvals`,
  `telegram_links`, `telegram_chat_history`, `linkedin_profiles`,
  `brief_todos`, `outbound_callbacks`, `callback_results`
- Groups (phases 1–5): `persona_groups`, `persona_group_members`,
  `persona_group_messages`, `persona_group_constraints`,
  `persona_group_audit_events`

### 2. Enable Realtime on `persona_group_messages`
The chat view subscribes to `postgres_changes` on this table. Until
realtime is enabled, new messages only appear on page refresh.

Supabase Studio → **Database** → **Replication** → toggle on for
`persona_group_messages`. (`persona_group_members` and `persona_groups`
don't need realtime for phase 1 or 2.)

### 3. Confirm RLS works for your service-role key
The API uses the service-role key, which bypasses RLS. The RLS policies
are defense-in-depth for any direct frontend reads (notably the realtime
channel). Sanity-check that:
- A signed-in member CAN read messages via the realtime channel
- An anonymous client CANNOT subscribe to a group they're not a member of

---

## Still pending (code, lower priority)

### Cross-instance `group_context` dispatch
Phase 2 dispatch only routes through the in-process orchestrator. When
persona members live on different Zynd backends, dispatch needs to:
- Build a signed `group_context` claim via the helpers already shipped
  (`build_group_context_claim`).
- Send it as part of the A2A v3 envelope to the target's host.
- The receiving host verifies via `verify_group_context_claim`,
  resolves `asker_agent_id` against its own group roster
  (defense-in-depth — the signature alone doesn't prove membership),
  and then calls the same `dispatch_group_mention` logic.

The orchestrator/A2A wrapping is the missing piece. Crypto + permission
mapping are in place.

### Asker- vs target-side permission model
The current model is "asker permissions": the group owner decides which
members are allowed to see briefs / calendars of anyone they @mention.
A more conservative model is "target permissions": each member toggles
whether their *own* brief/calendar is sharable inside the group. We can
add a second permission key (e.g. `share_my_brief`) on top of the
existing one and intersect at dispatch time. Worth revisiting if real
users push back on the asker-only model.

---

## Beyond phase 5 — possible next-up

Phases 1–5 are in main. Things worth doing next if the feature gets
traction:

- **Cross-instance dispatch** — wire the existing
  `build_group_context_claim` / `verify_group_context_claim` helpers
  into the outbound A2A v3 envelope so personas hosted on different
  Zynd backends can answer @-mentions in shared groups.
- **Target-side privacy preferences** — today permissions live on the
  ASKER ("X is trusted to see briefs"). Adding `share_my_brief` /
  `share_my_calendar` on each member would let users opt out of being
  read regardless of the asker's permissions.
- **Brief redaction layers** — same brief, different views per group.
  Useful when one person is in multiple groups and wants engineering
  to see different details than HR.
- **Domain auto-join: automatic** — currently surfaces as a CTA on
  the discover page. A signup-time hook could auto-add new users
  matching `join_domain` rules to their team's group.
- **Activity export** — let users download their audit log as JSON or
  CSV for a self-managed privacy record.
- **Group-level approvals** — meetings booked through `POST /meetings`
  could optionally require N member acknowledgments before the calendar
  event is actually created (reuses the existing approvals indicator).
