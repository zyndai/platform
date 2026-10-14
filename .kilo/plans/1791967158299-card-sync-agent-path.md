# Fix: single-fact publish freshness + review-inbox over-reporting

## Observed behavior (from the user)

1. Clicking the individual **Publish** button publishes the fact and Save works, but the
   card "takes time to update"; **Publish all** reflects the change immediately.
2. Telling the MCP agent "working on this project" fills the review inbox with
   "JavaScript" and other inferred/random facts.

## Root-cause analysis (verified against code)

### Issue 1 — single-fact publish updates slower than publish all

- Both buttons call the **identical** `approve(fact)` (`SuggestedFactsReview.tsx:118`),
  which on success calls `onChanged(snapshot)` → `applyMemorySnapshot`
  (`edit-client.tsx:250`) → `setMemoryFacts` + `setDraft(zynd_memory)`. There is no
  per-button logic difference; the difference is in how the *served snapshot / cache*
  converges for one fact vs. a batch.
- The public page and `data.json` are Next.js ISR routes cached with
  `next: { revalidate: 60 }` (`lib/cards.ts:222/234/246`; the public page prefers
  `cardView.facts` from `/cards/by-handle/{handle}/view`). They are purged on demand
  only by `ping_revalidate` (`services/zynd_memory.py:58-84`), which **silently
  no-ops when `WEB_REVALIDATE_URL` or `WEB_REVALIDATE_SECRET` are unset**
  (`config.py:81-82`). If the cards-api deploy lacks those env vars, a single approve
  leaves the public card stale for up to 60 s — exactly "takes time to update".
  Publish all *appears* instant because the edit-page tile updates from the last
  snapshot in the loop and the user's subsequent save/navigation re-fetches.
- Secondary contributors to verify in the diagnostic:
  - `approveSuggestedFact` returns `null` when the response lacks `zynd_memory`
    (`mcp-connector.ts:195-198`); `applyMemorySnapshot(null)` falls back to a
    fire-and-forget `void syncMemory()` (`edit-client.tsx:251-254`) — the tile can
    lag or miss the update entirely if that fetch is slow/fails.
  - The memory-side approve awaits `recompute_user_embeddings`
    (`findability.py:231/329`), an embedding call that can add seconds to the
    `/cards/mcp/approve` response itself (the "Publishing…" wait), which makes a
    single publish *feel* slower than a batch whose final state lands all at once.

### Issue 2 — "JavaScript and other random info" in the review inbox

- The MCP system prompt and `report_user_info` tool contract tell agents to enumerate
  typed `skills`, `languages`, `frameworks`, `tools`, `projects`
  (`mcp_http.py:84-101`, `:379-419`). From "working on this project" the agent infers
  the whole stack (JavaScript, etc.) and reports it.
- `declare_for_review` (`findability.py:364`) stores every passed value into the
  review queue; `assess` (`quality.py:120-172`) only hard-drops empty/very-short
  junk (`drop` = `empty` or short `code_shaped`). Everything else is soft-triaged to
  right/look/noise and **shown in the inbox**. So inferred stack guesses accumulate.

## Plan tasks

1. **Diagnostic (do first, ~10 min)**
   - Confirm which surface is slow: edit-page tile vs public page/`data.json`.
   - Check the cards-api environment for `WEB_REVALIDATE_URL`/`WEB_REVALIDATE_SECRET`
     (`services/cards-api/.env` / deploy env).
   - Browser console on the edit page: capture the `/cards/mcp/approve` response —
     does `zynd_memory` contain the just-approved fact? Capture its duration (isolate
     `recompute_user_embeddings` latency).
   - Record findings in the PR.

2. **Make single-fact publish converge immediately**
   - Ensure `WEB_REVALIDATE_URL` + `WEB_REVALIDATE_SECRET` are set on cards-api and
     cards-web (same value), and that `apps/cards-web/src/app/api/revalidate/route.ts`
     is deployed; verify it purges `/p/{handle}`, `data.json`, and the view route.
     (This is the direct fix for "takes time to update" on the public card.)
   - Harden `applyMemorySnapshot`: make the null-snapshot path **await** a re-sync
     (return a promise from `syncMemory` and await it) instead of `void syncMemory()`
     (`edit-client.tsx:250-254`), so the tile always converges.
   - In `approve` (`SuggestedFactsReview.tsx:118`): if the returned snapshot is
     `null`, explicitly re-sync and show the server state; otherwise apply it.
   - Publish all: collect per-fact failures and surface them (currently each item's
     catch swallows the error at `:133-135`), so a partially-failed publish-all does
     not masquerade as a full success and the user can see which facts failed.

3. **Fix review-inbox over-reporting (issue 2)**
   - Tighten `report_user_info`'s docstring + `_ZYND_INSTRUCTIONS`
     (`mcp_http.py:84-101`, `:390-396`): report skills/languages/frameworks/tools
     only when the user **explicitly stated** them; never infer a stack from a single
     "working on X" mention; ask before saving inferred stack facts.
   - Push inferred-adjacent guesses harder toward the `noise` group in `assess`
     (`quality.py:120-172`), keeping them dismissable but collapsed by default in the
     UI (the noise group is already collapsed behind "Expand").
   - Consider lowering `DEFAULT_DAILY_CAP` (`quality.py`) so one verbose agent session
     cannot flood the inbox.

4. **Latency (only if the diagnostic shows the approve response itself is slow)**
   - Move `recompute_user_embeddings` after approve/revoke/forget
     (`findability.py:231/273/329`, `control.py`) into the background (arq job or
     `asyncio.create_task`) so `/cards/mcp/approve` returns fast; matching stays
     eventually consistent. Rollback = re-add the await.

## Validation

- Manual: publish a single fact → edit tile updates immediately and the public page /
  `data.json` reflect it within ~10 s; publish all → same; a failing fact shows its
  server error instead of being silently swallowed.
- Memory: `cd services/memory && uv run pytest -q -m "not integration"` — baseline 8
  pre-existing failures (DB/env), report only new ones.
- Cards-web: `cd apps/cards-web && npm run lint && npx tsc --noEmit`.

## Out of scope

- Redesigning the review UI (S05). Search/embedding changes (S06). New MCP scopes.
- Changing the memory layer's public-card read shape (bridge contract).