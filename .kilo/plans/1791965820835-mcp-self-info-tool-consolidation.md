# MCP self-info tool consolidation + name fix + instructions rewrite

## Goal

The ZYND memory MCP (`services/memory`) is the user's cross-AI "who am I / what
am I working on" layer. Today the connector exposes too many near-identical
"get my …" tools, which overloads the LLM and — worse — the three tools a user
naturally reaches for (`get_my_card`, `get_my_system_prompt`, `get_my_context`)
never return the user's **name**. Collapse the self-info reads to **3 tools**,
make identity always present, and rewrite the server instructions so the LLM
unambiguously knows when to call what.

## Root cause of "nothing returned my name"

- `get_my_card` → `findability.get_card()` returns only `{predicate, object,
  confidence, source, …}`. No identity.
- `get_my_context` → `export.active_context()` returns only assertion
  statements. No identity.
- `get_my_system_prompt` is the only tool that emits a name, via
  `persona.get_status(supabase_user_id)` (an HTTP call to persona) falling back
  to `users.display_name`, which can be empty. Either way it degrades to
  "the user".

So "get my card / prompt / context returned nothing with my name" is expected
behaviour for two of the three, and a fragile best-effort for the third.

## Current self-info reads on `/mcp` (the overload)

| Tool | What it returns | Fate |
|---|---|---|
| `get_my_context(topic, k)` | memory assertions | **kept, becomes unified** |
| `get_my_card()` | public findability facts | merged |
| `get_my_socials()` | persona social links | merged |
| `read_my_brief()` | brief content | merged |
| `get_my_system_prompt()` | identity + profile + facts + brief + instructions | merged (removed) |
| `get_card_status()` | owner dashboard (completeness/review/activity/actions) | **kept** |
| `get_card_activity()` | 7-day views/hits (subset of status) | merged into status |
| `export_my_context()` | full JSON-LD portable export | **kept** |

Resulting self-info surface = **3 tools**: `get_my_context`,
`get_card_status`, `export_my_context`.

## Target tool contract

### 1. `get_my_context(topic: str|None = None, k: int = 20) -> dict`

One structured packet. Replaces `get_my_card`, `get_my_socials`,
`read_my_brief`, and `get_my_system_prompt`. Response:

```jsonc
{
  "identity": {
    "name": "…",            // ALWAYS non-empty (see name resolution below)
    "email": "…"            // from users table
  },
  "profile": {              // best-effort persona; null if unavailable
    "title": "", "organization": "", "location": "",
    "capabilities": [], "interests": [], "description": "",
    "socials": {"linkedin": "", "github": "", "x": "", "instagram": "", "website": ""}
  },
  "brief": "…",             // best-effort, null if unset
  "facts": [ … ],           // active_context (topic-filtered via context_slice when topic given)
  "card": [ … ]             // findability.get_card (public, user-approved)
}
```

Implementation: a shared `_self_info(uid)` helper in `mcp_http.py` (or a small
`app/services/self_info.py`) that the tool wraps. `_self_info` reuses the
existing service functions — `export.active_context` / `context_slice`,
`findability.get_card`, `persona.get_status`, `brief_tools.read_my_brief` — no
schema change.

### 2. `get_card_status()`

Absorb `get_card_activity`: the activity payload becomes an `activity` field
(or a `section` param). Delete the separate `get_card_activity` tool. Keep the
`cards:read` scope gate.

### 3. `export_my_context()`

Unchanged (portable JSON-LD + HMAC signature; distinct "backup/export" action).

## Name resolution fix (the actual bug)

`identity.name` resolves, in order, with no external dependency for the base
name:

1. `users.display_name` (local Postgres — always available), else
2. persona profile `name` (best-effort), else
3. email local-part.

`email` comes from `users.email`. If `display_name` is empty and the persona
profile has a name, opportunistically persist it back to `users.display_name`
so the local table self-heals (single UPDATE, idempotent).

This guarantees `get_my_context` always returns the user's name, which is the
fix the user asked for. `main.py:/me/context` (and its `action_schema.py`
ChatGPT Action equivalent) should be updated to return the same `identity`
field for parity.

## Instructions rewrite — `_ZYND_INSTRUCTIONS`

The current block lists ~25 tools with free-text "use when" lines and is the
second source of overload. Rewrite it around the reduced tool set with a
strict purpose-first structure so tool selection is unambiguous:

- **READ (one tool):** `get_my_context` — who the user is + what they're
  working on. Call once at conversation start; pass `topic` for a focused
  question. Never call other get tools for self-info (they no longer exist).
- **WRITE:** `remember` (single free-text durable fact) vs `report_user_info`
  (batched, typed: role/skills/languages/frameworks/tools/projects/goals).
- **FACT EDIT:** `confirm_fact_tool`, `forget_fact_tool` (exact predicate +
  object from `get_my_context`).
- **PEOPLE:** `find_similar_users` (like me), `find_people` (a target type),
  `find_linkedin_people_for_me`, `search_linkedin_profiles` (only when the user
  asks about other people).
- **NETWORK:** `connect_with`, `my_connections`, `send_persona_message`,
  `book_meeting`.
- **PUBLISH:** `publish_page`, `list_my_pages`.
- **CARD OWNER (only if granted `cards:read`/`cards:approve`):**
  `get_card_status`, `list_pending_facts`, `approve_fact`, `dismiss_fact`,
  `set_looking_for`.
- **INTEGRATIONS:** grouped one-line mention of Google (calendar/docs/drive/
  gmail/sheets), Twitter/X, LinkedIn, Notion — with a pointer to only use them
  on explicit request.

### Memory → card flow (must be stated explicitly in the instructions)

1. FEED: `remember`/`report_user_info` → facts are **private** and land in the
   user's review inbox.
2. The user reviews on their card (`get_card_status` / `list_pending_facts`);
   only facts they approve (`approve_fact`) become public and discoverable via
   `find_people`/`find_similar_users`/matching.
3. State this consent boundary: "facts stay private until you approve them;
   say so when saving."

The instructions must not promise tools that were removed, and the skills
(`skills/*/SKILL.md`) must be updated to the same reduced names.

## Files to change

**Core (source):**
- `services/memory/app/mcp_http.py`
  - add `_self_info(uid)` helper + new unified `get_my_context`
  - delete `get_my_card`, `get_my_socials`, `read_my_brief`,
    `get_my_system_prompt` (and its now-unused `_format_system_prompt`), and
    `get_card_activity`; fold activity into `get_card_status`
  - rewrite `_ZYND_INSTRUCTIONS`
- `services/memory/app/services/mcp_scopes.py`
  - `MEMORY_TOOLS` → `{remember, report_user_info, get_my_context,
    confirm_fact_tool, forget_fact_tool}`
  - `CARDS_READ_TOOLS` → remove `get_card_activity`
- `services/memory/app/main.py`
  - enrich `/me/context` with `identity` (name resolution parity)
- `services/memory/app/action_schema.py` (secondary, ChatGPT Action surface)
  - update `ContextPacket` schema to include `identity`; optionally collapse
    `getMyContext`/`getContextWithProfile` to one operation

**Docs / prompts:**
- `services/memory/skills/zynd-context/SKILL.md`
- `services/memory/skills/zynd-memory/SKILL.md`
- `services/memory/skills/zynd-card/SKILL.md`
- `services/memory/mcp-test-prompts.txt`

**Tests:**
- `services/memory/tests/test_mcp_tools.py` (tool-name sets + removed-tool tests)
- `services/memory/tests/test_mcp_http.py` (tool list assertion)
- `services/memory/tests/test_user_journeys.py` (`get_my_system_prompt`,
  `get_my_socials`, `read_my_brief`, `get_my_context` journeys)
- `services/memory/tests/test_card_status.py` if `get_card_activity` is covered

## Validation

- `cd services/memory && uv run pytest -q -m "not integration"`
  (baseline: 9 known DB-dependent failures; report only **new** failures).
- Manual smoke: mint a token for a user with a persona + empty `display_name`;
  call `get_my_context` and assert `identity.name` is non-empty; repeat with
  persona API down (name still resolves from local DB).
- `list_tools` on `/mcp` returns the reduced set; the default `memory:write`
  grant shows exactly one self-info read.

## Out of scope (flag for follow-up, not part of this change)

- `my_connections` vs `list_my_connections` — two tools listing the same
  connections (one via persona HTTP, one via direct Supabase `dm_threads`).
- `find_similar_users` vs `find_linkedin_people_for_me` overlap.
- Public cards MCP (`cards_public_mcp.py`) `search_people`/`get_card`/`ask_card`
  — different surface (finding *others*), unchanged here.
- ChatGPT Action schema consolidation beyond adding `identity`.