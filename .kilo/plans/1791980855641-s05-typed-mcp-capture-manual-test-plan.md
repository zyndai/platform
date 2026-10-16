# S05 Typed MCP Capture and Inbox Quality

## Current state and decision

The checked-out tree already contains most of S05: quality scoring, observe/flag mode, typed review declarations, `dismissed_at`, memory service routes, cards-api passthrough, and the grouped review UI. The implementation currently maps `tools` to `uses_tool`; the agreed target for this plan is `tools -> has_skill`, matching the acceptance criterion and scope. The implementation and tests must be updated to that contract before validation.

No database migration should be introduced beyond the additive `assertions.dismissed_at` column already present in `services/memory/sql/schema.sql`. No cards database change is required.

## Implementation sequence

1. **Quality and entity identity**
   - Keep pure quality helpers in `services/memory/app/services/quality.py` for canonicalization, repo/path and internal-jargon detection, tool-as-project retyping, labels, groups, and surface dedupe.
   - Update typed field mapping in `services/memory/app/mcp_http.py`: `tools`, `languages`, `frameworks`, and `skills` all declare `has_skill`; `projects` declares `is_building`; `goals` remains `intends_to`. Preserve role/notes through free-text extraction.
   - Enforce the 40-new-facts UTC daily cap across the complete typed batch, including goals, rather than checking once before writing. Per-field limit is four and total typed limit is twelve; goals must not bypass the total limit. Serialize writes per user for concurrency. Duplicates and dismissed re-reports must not consume new-write allowance. Observe mode logs without direct typed declarations; free text retains its independent extraction path.
   - Follow the ticket's exact canonical-name identity rule: trim/collapse whitespace and compare case-insensitively within one memory user, irrespective of entity type. Reuse an existing entity deterministically, preserve its type and aliases, and leave semantic/embedding merges type-scoped. Update the test that currently requires identical names in different types to remain separate. Do not destructively merge existing rows; surface dedupe handles legacy duplicates.

2. **Review lifecycle and API contracts**
   - Confirm `dismissed_at` is idempotently added and all suggestion queries exclude dismissed rows.
   - Keep `dismiss()` idempotent and suppress equivalent legacy duplicate rows and subsequent typed/inferred re-reports within the same user/public predicate family. A dismissal timestamp on one entity ID alone is insufficient.
   - Keep `approve(..., as_predicate=...)` optional; return the rendered public fact and expose the default remap through `public_label`/`suggested_predicate` rather than silently changing meaning.
   - Validate memory routes with service-token authentication: suggestions, approve, dismiss, revoke, and forget. The cards-api routes must pass through groups, labels, suggested predicates, `as_predicate`, and fresh snapshots. “Keep private” must use dismiss, never revoke.

3. **MCP guidance and UI**
   - Rewrite the MCP instruction text to say milestone-based reporting, batch durable facts, avoid repository names/paths, tools-as-projects, one-off tasks, internal jargon, and secrets, and ask before saving sensitive facts.
   - Preserve the review section in `apps/cards-web/src/app/(site)/p/[handle]/edit/edit-client.tsx`.
   - Review UI requirements: three groups (`Looks right`, `Needs a look`, `Probably noise`), collapsed noise, per-item `Shows as`, retype dropdown, publish/dismiss actions, bulk publish/dismiss, permanent dismissal copy, empty state, and mobile wrapping. Use the current cards API connector and do not add a second review data path.

4. **Tests to update/add**
   - Memory pure tests: canonicalization, repo/path and “worker trees” noise, tool-as-project retyping, labels, surface dedupe, caps, and observe mode in `tests/test_quality.py` and context/MCP tests.
   - Memory integration tests: typed tools produce `has_skill`; approval renders the selected predicate; dismissal is permanent; duplicate `Stocks` collapses in suggestions and public card; entity resolution behavior is covered in `tests/test_entities.py`.
   - Cards-api tests: passthrough of group/label/suggested predicate, `as_predicate`, and `/cards/mcp/dismiss` routing.
   - Web Playwright coverage: authenticated review page renders all groups; shows-as text is visible; retype then publish sends `as_predicate`; bulk publish/dismiss removes items; dismissed items remain absent after reload; noise collapse and mobile layout work.

## Manual test procedure

### 1. Start local dependencies and services

Use the repository’s local setup documented for the memory service. Start Postgres/pgvector and Redis, apply `services/memory/sql/schema.sql`, then run the memory API and worker with `MOCK_LLM=true`, `FEATURE_S01_PRIVATE_DEFAULT=true`, `MEMORY_SERVICE_TOKEN` set, and initially:

```text
FEATURE_S05_TYPED_CAPTURE=false
FEATURE_S05_OBSERVE=true
```

Start cards-api with the same memory URL/token and start cards-web with its normal local Supabase/API environment. Use a test account that can sign in to cards-web and has a linked ZYND memory user.

### 2. Verify observe/flag-only mode

Connect an MCP client using a memory token with `memory:write`, then call:

```json
{"tools":["Claude Code","SendPilot"],"projects":["acme/zynd-platform","worker trees","Docker"],"notes":"I am evaluating a durable workflow"}
```

Expected:

- The call uses the legacy extraction path for typed fields because typed capture is off.
- No direct typed declarations are created.
- Logs contain S05 observe decisions for repo/path, internal jargon, and tool-as-project candidates.
- The call does not save secrets or short empty values.

### 3. Verify typed capture and direct predicates

Restart or reload memory with:

```text
FEATURE_S05_TYPED_CAPTURE=true
```

Call `report_user_info` with:

```json
{"tools":["Claude Code","SendPilot"],"languages":["Python"],"frameworks":["React"],"skills":["Distributed systems"],"projects":["SendPilot"],"goals":"Ship SendPilot; learn Rust","role":"Founder","notes":"Milestone: first beta shipped"}
```

Expected:

- Tools, languages, frameworks, and skills create private review assertions with `predicate=has_skill` and no LLM extraction turn for those values.
- `SendPilot` from projects is `is_building`.
- Goals are split into durable goal declarations using `intends_to`.
- Role and notes use the text/extraction path.
- The response reports saved/skipped counts and says facts remain private pending review.
- Calling the same payload again does not create duplicate entities/assertions.

### 4. Verify quality triage and caps

Report these values in separate typed calls:

```json
{"projects":["acme/zynd-platform","./apps/cards-web","worker trees","Docker"]}
```

Expected in the inbox:

- Repository/path and `worker trees` appear in `Probably noise` unless hard-dropped by the configured rule.
- `Docker` appears in `Needs a look` with suggested predicate `uses_tool` because it was supplied as a project.
- Report `{"projects":["SendPilot"]}` separately; it appears as a project/building candidate. A fifth list value is beyond the per-field limit.
- A large payload beyond the per-field and total limits is capped; values beyond the cap are reported as skipped.
- On a fresh account, report unique names in batches of four until 36 facts are stored, then three to reach 39. Another batch of four must save at most one, leaving the count at 40; the next call must return the cap reason. Repeat with concurrent calls and semicolon-separated goals. Current code checks once before a batch and does not cap the goals loop; treat these as gaps to test, not presumed passing behavior.

### 5. Verify service/API payloads

With a valid cards-web Supabase session, inspect:

```text
GET  /cards/mcp/suggestions
POST /cards/mcp/approve
POST /cards/mcp/dismiss
```

Expected:

- Suggestion JSON contains `predicate`, `object`, `group`, `suggested_predicate`, `public_label`, and `confidence`.
- Approve accepts optional `as_predicate` and returns the rendered public fact plus a refreshed `zynd_memory` snapshot.
- Dismiss returns success and refreshed snapshot; invalid/missing facts return a clear 404.
- Requests without the cards session or with missing memory service configuration fail with the documented 401/503 behavior.

### 6. Verify review UI

Open `/p/<your-handle>/edit` and navigate to the retained memory review section. Keep DevTools Network open, filter for `mcp`, and reload after capture calls: the component currently fetches on mount rather than polling.

Expected:

- Items are grouped under `Looks right`, `Needs a look`, and collapsed `Probably noise`.
- Each item shows `Shows as:` before publishing.
- Change `SendPilot` from the default to `is_building`, publish it, and confirm the public card contains exactly the selected meaning.
- Publish a `has_skill` item without retyping and confirm the card uses the configured default public mapping/label.
- Use `Publish all` for `Looks right`; use `Dismiss all` for noise.
- Dismiss one item, refresh the page, and confirm it does not reappear.
- Confirm “Keep private” never calls revoke and does not produce a 404 for an unpublished fact.
- Confirm the empty state appears after all items are resolved.
- Test at a narrow mobile viewport: controls wrap, labels remain readable, and no row or button overlaps.

### 7. Verify dedupe and public card consistency

Create/report `Stocks` once through typed capture and once through an inferred or alternate entity type. Approve one occurrence, then inspect:

- `get_my_context` response's `card` field and `GET /cards/mcp/card-facts` (the old `get_my_card` tool no longer exists)
- the review queue before approval
- the edit page memory list

Expected: one visible `Stocks` item per public predicate family, with no duplicate entity presentation caused solely by entity-type variants.

Also seed legacy duplicate assertions with separate entity IDs in a local fixture, dismiss the visible item, and reload. Neither duplicate may reappear. Re-report using different casing/whitespace and then free-text extraction; it must stay absent. Current dismissal updates only one matching assertion, so this is an important regression check.

### 8. Rollback check

Set `FEATURE_S05_TYPED_CAPTURE=false` while leaving observe enabled. Re-run a typed report.

Expected: no direct typed declarations; the legacy text/extraction path is used, and quality decisions are only logged. Re-enabling the flag restores typed capture without a schema rollback.

This is capture rollback only: dismissal, suggestion enrichment, and UI are currently not gated by this flag. Do not describe flag-off as rolling back all of S05.

### 9. Guidance and privacy

Reconnect the MCP client to obtain fresh initialization instructions. Confirm milestone-based reporting and consent before saving sensitive facts. With synthetic data, ask the assistant to fix a one-off task in `acme/repo` and inspect its actual tool calls: repo/task/internal jargon should not be saved as durable facts. Then explicitly request a benign milestone be saved and inspect the typed arguments. Do not use real secrets. S09 routing golden tests alone do not verify this guidance; add behavioral cases separately.

## Validation commands

Run the relevant baseline before and after implementation changes. These commands were not run during this planning session; integration tests require local dependencies:

```bash
cd services/memory && uv run pytest -q -m "not integration"
cd services/memory && uv run pytest -q tests/test_quality.py tests/test_entities.py tests/test_findability.py tests/test_context_packet.py tests/test_mcp_http.py
cd services/cards-api && pytest -q tests/test_mcp_connector.py
cd apps/cards-web && npm run lint && npx tsc --noEmit
cd apps/cards-web && npx playwright test
```

Report only failures newly introduced by S05; the repository baseline documents environment-dependent failures for the memory service.

## Risks and rollback

- Over-filtering is mitigated by retaining noise in a collapsed group; only empty/clearly invalid values are hard-dropped.
- Predicate remapping must remain explicit through `suggested_predicate`, `public_label`, and optional `as_predicate`.
- Dismissal is intentionally permanent for the inbox and must not delete private memory.
- Rollback is the feature flag: disable `FEATURE_S05_TYPED_CAPTURE`; do not undo the additive schema column.
- Use a disposable local account and database for every mutation and cap fixture. Verify hosted revisions and feature settings explicitly: repo presence does not prove deployment. Production SQL/deployment requires human approval. No source changes, database writes, or tests were performed while preparing this plan.
