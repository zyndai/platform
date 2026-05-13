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

### Phase 2 — proactive personas (in progress)
TBD as commits land. Tracked below in **Pending end-to-end** under
"Phase 2 prerequisites" until shipped.

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

### A2A `group_context` claim
When a member's persona answers a question inside a group, the receiver
needs proof the caller is actually a group member. Plan:
- Add `group_seed` derivation in `agent/persona_manager.py` keyed off
  `persona_groups.group_seed_index` (column already exists).
- Sign outgoing A2A envelopes that originate inside a group with the
  derived group keypair; include the group_id + asker's agent_id.
- Receiver validates the signature + membership before honoring
  brief/calendar queries.

For **same-instance** deployments (phase 2 ships here first), we can
skip the signed-envelope step and route through the orchestrator directly
with an in-memory `group_context` object. The cross-instance case still
needs the signed claim.

### @-mention parsing + orchestrator hook
Phase 2 UI work:
- Composer detects `@` and pops a member picker (members fetched from
  `/api/groups/{id}/members` already).
- On send, parse `@name` tokens → resolve to agent_ids.
- POST a new endpoint that:
  1. Persists the human message as `channel='human'`,
  2. For each mentioned agent, calls the orchestrator with the
     `group_context` and the user's question,
  3. Persists each persona's reply as `channel='agent'` with
     `sender_agent_id` set.

The chat view already renders `channel='agent'` rows (`via persona` tag,
already implemented in phase 1) so no UI change needed for the response.

### Permission gating at query time
`persona_group_members.permissions` has flags the orchestrator must check
before exposing each member's brief or calendar:
- `can_see_brief` — does the asker permit OTHER members to ask their
  persona about their brief inside this group?
- `can_query_calendar` — same for calendar availability.

These are per-member, not per-group, so each persona enforces them on
its own answer pipeline. UI for toggling these lives in the settings
page (TBD — phase 2 work).

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
