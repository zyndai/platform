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

### Phase 2 — @-mention persona dispatch (in progress)
- `backend/agent/group_dispatch.py` — `extract_mentions`,
  `resolve_mentions_to_members`, and `dispatch_group_mention`. Routes
  through `handle_user_message(is_external=True, …)` with group
  permissions translated to the existing `external_permissions` shape.
- `POST /api/groups/{id}/messages` now parses `@DisplayName` mentions
  on the way in, fires a background `asyncio.create_task` for each
  resolved member, and returns `mentioned_user_ids` in the response so
  the client can render a thinking indicator.
- Replies are written back as `channel='agent'` rows with
  `metadata.reason='group_mention'` — realtime delivers them like any
  other message.
- Composer in `/dashboard/groups/[id]` has an `@`-typeahead picker
  (Up/Down/Enter/Tab/Esc). Sent messages render `@Name` as a styled
  chip with a distinct color when it's "@you".
- Pending indicator: "X's persona is thinking…" chip above the
  composer, cleared when the agent row arrives or after 60s.

Still in **Pending end-to-end** below: the cross-instance signed
`group_context` claim (current code is same-instance only).

---

## Pending end-to-end (must do before users see groups)

### 1. Apply the Supabase migration
The SQL patch isn't auto-run — `/supabase/` is gitignored. Apply it once
per environment (local, staging, prod):

```bash
# Local Supabase CLI
supabase db push --file backend/db/patch_add_persona_groups.sql

# Or paste the contents into the Supabase Studio SQL editor and run.
```

What it creates:
- `persona_groups` — group rows with slug, owner, visibility, invite_token
- `persona_group_members` — join table with role + permissions JSONB
- `persona_group_messages` — chat content, with `channel ∈ {human, agent, system, broadcast}`

### 2. Enable Realtime on `persona_group_messages`
The chat view subscribes to `postgres_changes` on this table. Until
realtime is enabled, new messages only appear on page refresh.

Supabase Studio → **Database** → **Replication** → toggle on for
`persona_group_messages`. (`persona_group_members` and `persona_groups`
don't need realtime for phase 1.)

### 3. Confirm RLS works for your service-role key
The API uses the service-role key, which bypasses RLS. The RLS policies
are defense-in-depth for any direct frontend reads (notably the realtime
channel). Sanity-check that:
- A signed-in member CAN read messages via the realtime channel
- An anonymous client CANNOT subscribe to a group they're not a member of

### 4. Set a max-members policy
Phase 1 doesn't enforce a member cap. Small-team scope is 3–15, but the
backend will let an admin add 200 members. Either:
- Add a cap check in `add_member` / `join_via_invite` (recommended),
- Or wait until a real customer is approaching the limit.

### 5. Decide owner-transfer flow before shipping publicly
The current schema has a single `owner_user_id` on `persona_groups`.
Owners can't currently transfer ownership through the UI — they have to
archive the group and start over. Either:
- Add a `PATCH /api/groups/{id}/transfer-owner` endpoint, or
- Document the limitation and revisit if users hit it.

---

## Phase 2 prerequisites (not yet in code)

### A2A `group_context` claim — cross-instance dispatch
Current dispatch is **same-instance only**: all group members are
expected to live on the same backend. Cross-instance deployment needs:
- `group_seed` derivation in `agent/persona_manager.py` keyed off
  `persona_groups.group_seed_index` (the column exists and is populated
  at create time; the keypair derivation is not wired yet).
- A2A v3 envelopes carrying a `group_context` claim signed by the
  derived group keypair, with `group_id` + asker `agent_id`.
- Receiver validates the signature + membership before honoring the
  dispatch. The current code path (`group_dispatch.dispatch_group_mention`)
  is where the cross-instance wrap would sit.

### Per-member permission UI
The schema carries `can_see_brief`, `can_query_calendar`, and
`can_speak_for_group` on `persona_group_members.permissions`. The
**dispatcher already honors them** via `_group_perms_to_external`, but
the settings page has no UI to toggle them yet — members get the
defaults from the migration until that lands.

### Brief content injection (when `can_see_brief` is on)
`can_see_brief` currently maps to `can_view_full_profile`, which
controls the orchestrator's profile redaction but doesn't automatically
expose brief content as additional context. To make `can_see_brief`
actually answer "what is Sarah working on?", we need to either:
- Inject the target's brief snippet into the orchestrator's system
  prompt at group-dispatch time, **or**
- Add a `read_my_own_brief` MCP tool the target persona can call (since
  it's the target's own brief, not a cross-agent leak).

The first option ships faster; the second is the more orthogonal fix.

---

## Future phases (not scoped yet)

- **Phase 3** — group brief Google Doc (parallel to the per-user brief),
  group calendar overlay (free/busy across members), group meeting proposals.
- **Phase 4** — shared constraints / "group memory" applied as guards on
  outgoing messages from any member's persona.
- **Phase 5** — discoverable groups, domain auto-join, audit dashboards
  ("who saw my brief, when").

See the design discussion in chat for context on why we chose this order
(small teams + per-group visibility + proactive personas).
