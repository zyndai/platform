# ZYND MCP: consolidate self-info to 1 read + 1 write tool

## Goal

The `zynd` MCP server (`services/memory/app/mcp_http.py`, ~90 tools) today exposes
7 overlapping self-info reads and 2 fact-save tools, and only `get_my_system_prompt`
ever returns the user's name. Collapse the self-info surface to **one read tool +
one write tool (+3 narrow special-purpose tools)**, make the name always present,
and rewrite the server instructions so the LLM calls the right thing without
guessing. Supersedes the unimplemented plan `1791965820835-mcp-self-info-tool-consolidation.md`.

## Decisions (confirmed with user)

1. **One read tool**: `get_my_context` returns all self-info sections in one bounded packet.
2. **One write tool**: `report_user_info` absorbs `remember` via a new free-text `text` param.
3. **Keep 3 special-purpose tools** (not "info about me"): `export_my_context`,
   `confirm_fact_tool`, `forget_fact_tool`.
4. **Keep existing names**, hard-remove the replaced tools server-side in one change.
5. **`zynd-cards` connector**: leave its code as-is (out of scope).
6. Integrate all downstream surfaces (HTTP endpoint, ChatGPT Action schema, scopes,
   skills, tests, docs) in the same change.

## Tools removed (hard-delete)

| Removed | Reason |
|---|---|
| `get_my_card` | folded into `get_my_context.card` |
| `get_my_socials` | folded into `get_my_context.socials` |
| `read_my_brief` | folded into `get_my_context.brief` |
| `get_my_system_prompt` (+ `_format_system_prompt`) | folded into `get_my_context` |
| `get_card_status` | folded into `get_my_context.status` |
| `get_card_activity` | folded into `get_my_context.activity` |
| `remember` | folded into `report_user_info(text=...)` |

Kept unchanged: `append_to_my_brief`, `replace_my_brief`, `clear_my_brief`,
`add_todo`, `set_social_links`, `export_my_context`, `confirm_fact_tool`,
`forget_fact_tool`, all people/network/publish/integration tools.

## Target contracts

Revalidated against the checkout on 2026-10-14. This revision is planning only;
implementation and deployment are separate steps. The consolidation applies to
the memory MCP server, not independently named Persona tools or HTTP operations.

### 1. `get_my_context(topic: str|None = None, k: int = 20) -> dict`

Single structured packet:

```jsonc
{
  "identity": {
    "name": "…",   // ALWAYS non-empty (resolution chain below)
    "email": "…"   // users.email, may be null
  },
  "profile": {     // persona.get_status(supabase_user_id), best-effort; null if unavailable
    "name": "", "title": "", "organization": "", "location": "",
    "capabilities": [], "interests": [], "description": "", "socials": {}
  },
  "socials": { "linkedin": "", "github": "", "x": "", "instagram": "", "website": "" },
  "brief": "…",           // read_my_brief; null if unset
  "facts": [ … ],         // active_context, or context_slice when topic given
  "card": [ … ],          // findability.get_card (public, user-approved)
  "status": { … },        // card_status.get_owner_status data — ONLY if token has cards:read or user scope
  "activity": { … },      // existing 7-day metrics dict; same scope gate, otherwise omitted
  "present": ["identity", "facts", "card", …]  // non-empty sections, so the LLM can answer "is there any info?"
}
```

Implementation: put shared identity/profile lookup in
`app/services/self_context.py`, not `mcp_http.py`, so the HTTP endpoint does not
import the MCP server, auth setup, skills provider, or process-lifetime pools.
Keep packet assembly inside the MCP tool unless a second caller needs it.
Reuses existing service functions; no schema change.

- Fetch the memory user row once, including `display_name`, `email`,
  `supabase_user_id`, and `socials`. Fetch persona status at most once per packet,
  even when a display name already exists (the profile is still needed).
- Normalize MCP `profile` from the actual nested persona response: name,
  description, and capabilities are top-level; title, organization, location,
  interests, and social URLs live under its `profile`. HTTP `profile` remains
  the existing raw persona-status object, not this normalized MCP shape.
- `socials` uses persona links first, with stored `users.socials` as fallback per
  key; normalize `twitter` to `x`. Only non-blank values count toward `present`.
- Brief lookup uses the linked Supabase uid (or memory uid when unlinked), as
  `_suid` and the old system-prompt tool do. The current HTTP endpoint incorrectly
  uses memory uid; correct this lookup without renaming response fields.
  The brief service uses synchronous Supabase I/O: run its read off the event
  loop using the existing async runtime's thread support; do not rewrite all
  brief tools as part of this task.
- Preserve `topic.strip()` behavior and the MCP `k` clamp of 1..50 for facts.
  Topic filters facts only, not identity/profile/card/brief. This is a bounded
  context snapshot, not an exhaustive graph export.
- Inject `token: AccessToken = CurrentAccessToken()` alongside `uid`; never make
  scopes or uid model-supplied inputs. Inspect actual token scopes, not visibility
  registration lists. Only `cards:read` or legacy `user` permits owner calls;
  `cards:approve` alone does not.
- Make one `get_owner_status(pool, uid)` call only when authorized. On success,
  `status` is its `data` dict and `activity` is `data.activity` (a dict, not an
  array); status already includes activity, so do not fetch it twice.
- Unauthorized tokens omit both owner keys and make no owner upstream call.
  Authorized upstream failure/disabled feature returns both keys as null.
  Optional persona/brief failure must not prevent returning local facts/card
  and identity; null is not evidence that no information exists. Do not convert
  local database failures into successful empty-memory responses.
- Always include the base keys `identity`, `profile`, `socials`, `brief`, `facts`,
  `card`, and `present`. `present` lists only sections with substantive content;
  identity is always listed, but identity alone does not mean stored facts exist.

### 2. `report_user_info(..., text: str | None = None)`

- Existing typed params unchanged (`role`, `skills`, `languages`, `frameworks`,
  `tools`, `projects`, `goals`, `notes`).
- New `text` param: when non-empty and supplied alone, route through the current `remember` path
  (`clean_text` → `ingest_turns(..., min_chars=_REMEMBER_MIN_CHARS)`); return the
  remember-style `{saved, reason/note}` shape. When `text` empty, behave exactly
  as today. Treat whitespace-only text as empty. Do not clip deliberate free-text
  input through `_clip`, which would change the old remember behavior.
- Reject non-blank `text` combined with any non-empty existing input (including
  role/notes/goals) before any database write or enqueue, returning
  `{saved: false, reason: "Use text alone or typed fields, not both"}`. No input
  may be silently discarded. Document the mutually exclusive modes in the
  tool description and memory skill.
- Preserve free-text source_system `claude`, duplicate handling, minimum length,
  and asynchronous extraction. Preserve the typed path's feature gates, caps,
  source_system `cards_mcp`, and return shape. Consolidation does not introduce
  a new policy/cap for text-only saves.
- Merged docstring: "save durable facts — typed fields at milestones, `text` for a
  single free-text fact; never secrets/casual chatter".

### 3. Name resolution (the actual bug)

Shared resolver in `app/services/self_context.py`:

1. `SELECT display_name, email, supabase_user_id, socials FROM users WHERE id = $1`
2. Fetch persona status best-effort when linked; if the trimmed display name is
   empty, take its trimmed `name`. Reuse that response for profile and socials.
3. Fallback: trimmed email local-part, then `"ZYND user"` when no usable name/email
   exists. A missing user row must fail rather than manufacture an account.
4. Self-heal: if resolved from persona and `display_name` is empty →
   `UPDATE users SET display_name = $2 WHERE id = $1 AND
   (display_name IS NULL OR btrim(display_name) = '')`. The condition must be in
   SQL, not just Python, so a concurrent explicit name change cannot be overwritten.
   Self-heal is best-effort: a failed update must not discard resolved context.

This guarantees `identity.name` is non-empty even with persona API down.
This is a display label, not a verified real name; do not imply otherwise for
email/generic fallbacks. Do not expose internal linkage ids in the identity packet.
Self-healing mutates the existing memory users row on read: document it and make
the MCP `readOnlyHint` truthful (`False` while this behavior is retained).

## Instructions rewrite (`_ZYND_INSTRUCTIONS`, the "very good" system prompt)

Replace the current ~25 free-text tool blurbs with a short, purpose-first block:

- **What ZYND is** (2 sentences) + two-way flow.
- **READ — exactly one tool**: `get_my_context` at conversation start; returns
  name/email/profile/socials/brief/facts/card in one packet. Pass `topic` for a
  focused question. "There is no other self-info tool — do not look for one."
  Address the user by `identity.name`.
- **WRITE — exactly one tool**: `report_user_info` (typed fields at milestones;
  `text` for a single free-text fact). Batching rule; never on every keystroke.
- **CORRECT**: `confirm_fact_tool` / `forget_fact_tool` (exact predicate+object
  from `get_my_context.facts`; never claim success on a false result).
- **EXPORT**: `export_my_context` only for explicit backup/download/export.
- **PEOPLE / NETWORK / PUBLISH**: one-line groups (find_*, connect_with,
  my_connections, send_persona_message, book_meeting, publish_page, list_my_pages).
- **CARD OWNER** (only with granted scopes): list_pending_facts, approve_fact,
  dismiss_fact, set_looking_for, update_headline, list_intros.
- **INTEGRATIONS**: one grouped line for Google (calendar/docs/drive/gmail/sheets),
  Twitter/X, LinkedIn, Notion — use only on explicit request.
- **Privacy / consent boundary**: facts stay private until the user approves them
  on their card; say so when saving; never save secrets/credentials; ask before
   sensitive topics; never invent tool results.

"One write" means one durable-fact save tool, not the removal of brief/social,
correction, or card-owner writes. Instructions must use only tools visible in
the client's actual tool list; retained `export_my_context`, brief, and social
tools remain legacy-`user`-only under the existing scope mapping. Do not expand
default scope access just to match the instructions. Only `card` is evidence of
public approved facts; `facts`, `profile`, and `brief` are private context.

Remove every mention of deleted tools from active memory MCP instructions and
tool descriptions, including the preferred-flow block. Retain the internal
`brief_tools.read_my_brief` service function; delete only its MCP wrapper.

## Files to change

**Core:**
- `services/memory/app/mcp_http.py`
  - import shared resolver and assemble the MCP packet
  - rewrite `get_my_context` (new packet, topic/k preserved, scope-gated status/activity)
  - add `text` param + remember branch to `report_user_info`; delete `remember` tool
  - delete `get_my_card`, `get_my_socials`, `read_my_brief`, `get_my_system_prompt`,
    `_format_system_prompt`, `get_card_status`, `get_card_activity` and now-unused imports
  - rewrite `_ZYND_INSTRUCTIONS`
- `services/memory/app/services/self_context.py` (new, narrowly shared service)
  - user-row/profile lookup, identity resolution, conditional name self-heal
- `services/memory/app/services/mcp_scopes.py`
  - `MEMORY_TOOLS` → `{report_user_info, get_my_context, confirm_fact_tool, forget_fact_tool}`
  - `CARDS_READ_TOOLS` → remove `get_card_status`, `get_card_activity`
- `services/memory/app/main.py`
   - `GET /me/context`: add `identity` (same resolver), fix linked brief uid.
     Preserve `assertions`, raw `profile`, and `brief` keys/types. **Additive contract** — consumers
    `services/persona-api/agent/memory_client.py` and `zynd-bridge/src/memory-client.ts`
    (separate repo, must stay version-compatible) read existing keys and are unaffected.
- `services/memory/app/action_schema.py`
   - `ContextPacket` schema += required `identity` with required non-empty `name`
     and nullable email (OpenAPI 3.1 types); update `getContextWithProfile` at
     `/me/context` to describe the HTTP packet, not the larger MCP packet.
     `getMyContext` is `/me/graph` and remains a facts array; preserve its operation
     ID and schema. The word "remember" there is natural language, not a tool call.
- `services/memory/app/mcp_owner.py` — remove stale owner-read tool comment

**Skills / prompts:**
- `services/memory/skills/zynd-context/SKILL.md` — one-read flow, packet fields
- `services/memory/skills/zynd-memory/SKILL.md` — one-write flow (`text` vs typed)
- `services/memory/skills/zynd-card/SKILL.md` — status/activity now in `get_my_context`
- `services/memory/mcp-test-prompts.txt`

Skills must distinguish identity-only packets from useful stored context and
null/unavailable sections from empty sections. Card visibility guidance must
refer exclusively to `get_my_context.card`, and correction guidance to `.facts`.

**Tests:**
- `services/memory/tests/test_mcp_tools.py` — tool-name sets; removed-tool assertions
- `services/memory/tests/test_mcp_http.py` — `list_tools` reduced set
- `services/memory/tests/test_user_journeys.py` — replace `get_my_system_prompt` /
  `get_my_socials` / `read_my_brief` / `get_my_context` journeys with packet assertions;
   add `identity.name` non-empty cases (incl. persona-down fallback); migrate
   direct `remember` calls to `report_user_info(text=...)` retaining saved,
   too-short, and duplicate coverage
- Packet-level tests (in `test_mcp_tools.py`/`test_user_journeys.py`): nested-profile
  normalization, socials precedence/aliases, linked brief uid, optional failures,
  single persona/owner fetch, `present`, topic and k, and caller isolation across
  every section. Update existing direct `get_my_socials` tests too.
- Scope cases: memory-only, memory+cards-read, memory+cards-approve without read,
  and legacy user. Assert unauthorized owner keys are omitted and upstream is
  never called. Keep existing lower-level `test_concurrency_and_isolation.py`
  and `test_card_status.py` coverage; they do not currently test these MCP tools.
- Resolver tests: trimmed display name/persona/email/generic fallbacks; persona
  down; missing row; failed self-heal; conditional SQL does not overwrite a
  concurrent name change
- Write tests: text-only, typed-only, blank text, all-empty input, mixed-input
  rejection before side effects, and existing caps/feature flags unchanged
- `services/memory/tests/test_bridge_contract.py` — assert identity plus unchanged
  `assertions/profile/brief` and correct linked brief lookup, not only route existence
- `services/memory/tests/test_s09.py` — exact scoped membership and removed names;
  test transport-level discovery/calls and dependency injection, not only direct
  Python calls. Verify injected token/uid absent from the exposed input schema.
- Action schema tests — operation/path mapping and HTTP identity schema
- `services/memory/tests/test_ingest_and_recall.py` — update stale tool-path description
- `services/persona-api/tests/test_memory_me_context.py` — additive identity fixture
  proves assertion ranking/filtering/caps unchanged (no consumer implementation edit)

**Docs:**
- `docs/S10_OWNER_HOME.md` (line 32) and `docs/S10_MANUAL_TESTING.md` (line 376) —
  reword `get_card_status`/`get_card_activity` mentions to `get_my_context.status/activity`.
- Repo-wide grep sweep for the seven removed tool names; classify matches before
  editing. Persona has its own retained `read_my_brief` tool and the frontend
  has an actual label mapping for it; leave both intact. Preserve historical
  plans, cards HTTP handlers, the excluded connector, and public-card MCP.
  Update maintained memory-server docs only, including the "two authenticated
  MCP read tools" text in `S10_OWNER_HOME.md`.

## Validation

1. Before starting and after: `cd services/memory && uv run pytest -q -m "not integration"`
    Capture the actual pre-change failure names, not just the documented count
    of 9; compare post-change failures against that observed baseline. This
    plan-only revision requires no service test run.
2. `list_tools` on `/mcp` returns the reduced set; default `memory:write` grant shows
   exactly one self-info read and one save tool.
3. Local/test-fixture smoke only: use a token for a user with empty `display_name` + mocked/live local persona →
   `get_my_context` returns non-empty `identity.name`; repeat with persona URL
   unreachable (name still resolves via email local-part); confirm self-heal UPDATE.
4. `GET /me/context` returns `identity` alongside `assertions/profile/brief`
    (persona-api + zynd-bridge consumers unchanged).
5. Run focused tests for packet assembly, scope gate, free-text/typed modes,
   Action schema, and persona `test_memory_me_context.py`. If its fixture changes,
   capture persona's relevant pre/post baseline too. Do not edit or run commands
   in the separate zynd-bridge repo.
6. The scope mapping/access changes require explicit human approval before
   implementation under AGENTS.md section 6. Do not mint prod tokens, run prod
   SQL for the name self-heal smoke, or deploy without separate approval.

## Out of scope (flag, do not touch)

- `zynd-cards` connector and its code (user: leave as-is).
- `cards_public_mcp.py` (public cards MCP — finding *others*).
- Pre-existing tool overlaps: `my_connections` vs `list_my_connections`,
  `find_similar_users` vs `find_linkedin_people_for_me`, `propose_meeting` vs
  `book_meeting`, `zynd_network`/`zynd_services` agent-channel tools.
- No DB schema change; no change to cards-api.

## Risks

- MCP clients cache tool lists; removed calls receive unknown-tool errors until
  the client re-syncs (not necessarily HTTP 404).
- `/me/context` must stay additive (zynd-bridge ships independently).
- `get_my_context` scope gating must use the token's scopes, not registration lists,
   or `status/activity` would leak to `memory:write`-only tokens.
- Memory-only tokens gain profile/socials/brief via consolidation where granular
  tokens previously could not call those dedicated reads. This is an intentional
  access-surface expansion and must be included in the approval/review.
- Self-heal is a memory DB data write, not a migration; preserve existing names
  under races and account for truthful read-only annotations.
- Optional upstream latency now affects the primary startup read (persona timeout
  is 12s and owner timeout is 15s). Avoid duplicate calls and blocking Supabase
  I/O; verify graceful failure under timeout without adding new retry machinery.
- MCP `get_my_context` changes from an array to an object: this is a deliberate
  breaking change for MCP callers, even though `/me/context` stays additive.
- Deploy the memory service only with human approval, after confirming its actual
  serving checkout; this monorepo does not guarantee memory auto-deploy. Clients
  pick up the new tool list on next sync. No dashboard/connector edits or database
  schema migration are part of this task.
