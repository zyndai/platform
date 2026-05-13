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

### Phase 3a — shared group brief (commit pending)
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

### 1. Apply the Supabase migration
The SQL patch isn't auto-run — `/supabase/` is gitignored. Apply once
per environment (local, staging, prod):

```bash
# Local Supabase CLI
supabase db push --file backend/db/patch_add_persona_groups.sql
supabase db push --file backend/db/patch_add_persona_group_brief.sql

# Or paste each into the Supabase Studio SQL editor and run.
```

What they create:
- `persona_groups` — group rows with slug, owner, visibility, invite_token,
  and (phase 3a) `brief_doc_id` / `brief_doc_url`
- `persona_group_members` — join table with role + permissions JSONB
- `persona_group_messages` — chat content, with
  `channel ∈ {human, agent, system, broadcast}`

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

## Future phases (scoped only as ideas)

- **Phase 3** — group brief Google Doc (parallel to the per-user brief),
  group calendar overlay (free/busy across members), group meeting proposals.
- **Phase 4** — shared constraints / "group memory" applied as guards on
  outgoing messages from any member's persona.
- **Phase 5** — discoverable groups, domain auto-join, audit dashboards
  ("who saw my brief, when").

See the design discussion in chat for context on why we chose this order
(small teams + per-group visibility + proactive personas).
