# S05: understand it and test it on production

S05 improves the facts your coding assistant sends to your Zynd Memory account
and the inbox where you decide which facts become public.

This is a testing plan, not a record of production tests already run. It follows
local `dev` commit **`4f6a533`** (2026-10-14). Confirm the deployed commit and flags
separately. The original scope is
[S05 typed capture and inbox quality](../conventions/S05-typed-mcp-capture-and-inbox-quality.md).

## 1. What is S05, in simple terms?

Imagine you tell your assistant:

> I use Docker and Claude Code. I am building a study planner.

Those are two different kinds of information: **tools you use** and **a project
you are building**. S05 preserves that distinction so the system does not turn
Docker into a project you supposedly created.

It then helps you review the suggestions:

| Part of S05 | Everyday example |
| --- | --- |
| Structured capture | Docker goes into the tool/skill category; the planner goes into the project category. |
| Inbox grouping | Useful suggestions appear under **Looks right**; questionable ones can need review; paths and jargon belong under **Probably noise**. |
| Publication preview | **Shows as** tells you the public wording before you publish. |
| Retyping | Change a suggested skill to **Learning** if calling yourself an expert would be wrong. |
| Dismissal | Hide an unwanted suggestion while retaining it privately in Memory. |
| Deduplication | Repeated versions of the same fact should not fill the inbox with duplicate rows. |

**Reporting does not mean publishing.** A structured report should stay private
until you choose to publish it. The group **Looks right** is a quality hint, not
proof that the fact is true or permission to publish it automatically.

The public vocabulary currently maps ordinary `has_skill` suggestions to
`has_expertise_in`: **Shows as: Expert in: Docker**. That does not establish
expertise. Read the preview and select **Learning** if that better describes you.

How the related features fit together: S01 supplies private-by-default handling;
S05 improves capture and review; S02 updates the public card after your decision.
S04 counts activity but is not required for the S05 workflow to function.

## 2. Prepare your production test

| Person/session | Purpose |
| --- | --- |
| Alice | Your designated production test account, with a claimed card and linked Memory account. |
| Alice's coding assistant | Connected to her authenticated Zynd MCP with `report_user_info` available. |
| Bob | A separate account/assistant for checking user isolation. |
| Incognito browser | Checks what an anonymous visitor can see. |

Use these production origins, confirmed against the actual deployment:

| Surface | URL |
| --- | --- |
| Alice's review inbox | `https://cards.zynd.ai/p/alice-dev/edit#inbox` |
| Cards API | `https://cards.api.zynd.ai` |
| Authenticated Memory MCP | `https://api.zynd.ai/mcp` |

Replace `alice-dev` with the test card that you own. The public
`/cards-public-mcp` endpoint is for discovery; it does not report private owner
facts. The old standalone Cards MCP described in the conventions has been
replaced by the shared authenticated MCP.

### Confirm these prerequisites

| Prerequisite | Expected state |
| --- | --- |
| Memory MCP capture flag | `FEATURE_S05_TYPED_CAPTURE=true` in the running Memory MCP process. Default is false. |
| Private defaults | Maintainer confirms the deployed private-default behavior, including `FEATURE_S01_PRIVATE_DEFAULT=true` for extracted facts. |
| Memory schema | Deployed Memory schema includes `assertions.dismissed_at` and the existing assertion/entity fields. |
| Cards-to-Memory bridge | `MEMORY_LAYER_URL` reaches the intended Memory service and the existing `MEMORY_SERVICE_TOKEN` matches. |
| Web origins | Deployed `NEXT_PUBLIC_API_URL=https://cards.api.zynd.ai` and `NEXT_PUBLIC_ZYND_API_URL=https://api.zynd.ai`. |
| Accounts | Alice's web sign-in and MCP connection resolve to the same Memory owner. |
| Free-text branch | Memory extraction worker/Redis and its provider are functioning if you test role/notes. |

There is no separate S05 web flag in this implementation. The grouped review
component is part of the deployed editor. S10's flag adds owner home/autosave;
it is not a prerequisite for the inbox at `/edit#inbox`.

On the checked-in single-box setup, Memory's production settings come from
`services/memory/.env.prod`, loaded into the Memory API and MCP containers:

```dotenv
# Values for the maintainer to verify, not instructions to edit production.
FEATURE_S05_TYPED_CAPTURE=true
FEATURE_S05_OBSERVE=true
FEATURE_S01_PRIVATE_DEFAULT=true
```

`FEATURE_S05_OBSERVE=true` with typed capture **false** only logs what the filter
would do; structured fields still take the legacy text-extraction path. Seeing
groups in the inbox alone does not prove typed capture is enabled.

Missing settings/schema are **Blocked** findings. Production deployment,
schema changes, and SQL require human approval under [AGENTS.md](../AGENTS.md).
Memory has its own database; its assertions do not live in the shared Cards
Supabase schema. Do not patch tables to manufacture test outcomes.

Use a small number of fresh values on your own test account. Reporting adds
production Memory records; Publish makes selected values public; Dismiss has no
undo control in this inbox. Do not include credentials, personal secrets, or
facts that you do not intend to retain. Bulk, cap, replay-of-approved-fact, and
backend outage tests belong in an isolated environment by default.

## 3. Manual scenarios

### A. The assistant reports tools and a project separately

1. Record Alice's current inbox and public fact list.
2. Ask her connected assistant to call **`report_user_info`** with this JSON,
   replacing the example values with appropriate fresh test values:

   ```json
   {
     "tools": ["Claude Code", "Docker"],
     "languages": ["Rust"],
     "projects": ["S05 Demo Planner"]
   }
   ```

3. Inspect the actual tool name and arguments. A natural-language promise from
   the assistant does not prove the tool ran.
4. Inspect the returned `saved`, `items_saved`, and `items_skipped` values.
5. Reload `/p/alice-dev/edit#inbox`. Inspect the authenticated
   `GET /cards/mcp/suggestions` response in DevTools if needed.
6. Check Alice's public card in incognito and call her MCP **`get_my_card`**.

**Expected:** With typed capture on, tools/languages are private `has_skill`
suggestions, while the planner is a private `is_building` suggestion. No typed
list has to wait for free-text extraction. New values should appear in the
review inbox and should not appear in the public card/get_my_card before approval.

Frameworks and skills use the same private `has_skill` mapping. `items_saved`
counts accepted writes/ingested turns, not necessarily new inbox rows or public
facts. Existing values can affect the result; do not require four new rows on
an account that already remembers Docker or Rust.

### B. Repeated private reports do not multiply the inbox

Perform this before publishing the relevant suggestion.

1. Report a fresh tool value twice within one list, varying capitalization and
   spacing, e.g. `"Claude Code"`, `"claude   code"`.
2. Reload the inbox and count matching rows.
3. Repeat the same private report once, then reload again.
4. Compare the private suggestions and the public list separately.

**Expected:** List normalization trims/collapses spacing and deduplicates case
variants. Re-reporting the same private assertion should not create another
visible copy. A response can still report a saved update even when no new row
is visible. Deduplication is by name and public predicate family, not a promise
that every similar word or every database entity is merged.

**Production limit:** Do not re-report an already-approved project just to test
this. `declare_for_review` updates an existing matching assertion to private;
replay after publication needs isolated regression testing.

### C. Paths and internal jargon are triaged as noise

1. On the test account, submit a small synthetic report such as:

   ```json
   {
     "projects": ["example/s05-demo", "worker trees"],
     "skills": ["ai"]
   }
   ```

2. Reload the review inbox. Find **Probably noise**, which starts collapsed.
3. Click **Expand** and inspect the values and their **Shows as** previews.
4. Collapse it again. Do not publish these synthetic noise values.

**Expected:** Repo/path-like names, internal jargon, and generic tokens are
kept private and classified `noise`. Most noise is intentionally visible for
review rather than dropped. Empty strings are skipped; a small set of obviously
junk code-shaped strings can be dropped. Noise is not automatically deleted.

The heading appears only if the group has rows; an absent empty group is normal.

### D. A tool reported as a project is corrected

Use a fresh, not-already-public value from the maintained tool list, e.g. Docker.
If your test account already has that fact, use an isolated fixture instead of
changing an approved assertion.

1. Report `{"projects":["Docker"]}`.
2. Inspect the suggestion's stored predicate and **Shows as** preview.
3. Check that Docker is not being offered as a project Alice created.

**Expected current behavior:** The typed reporter suggests `has_skill` and saves
the corrected private fact. Its preview normally uses **Expert in: Docker**.
The owner should still decide whether that public label accurately describes her.

**Difference from the conventions:** The pure filter labels this input
`look`/tool-as-project, but the inbox rebuilds quality without the original
field context. The corrected value can appear under **Looks right**, and other
field-dependent **Needs a look** classifications can be lost too. Record this
as a triage requirement gap; do not require a visible **Needs a look** row from
this report or fabricate one in production SQL.

### E. Alice changes the public meaning before publishing

Use one fresh skill suggestion that Alice wants to publish as something she is
learning. For example, Rust can be appropriate for a designated learning fixture.

1. Inspect the original **Shows as: Expert in: Rust** preview.
2. Use **Retype before publish** and select **Learning**.
3. Verify the preview changes to **Learning: Rust** before taking action.
4. Click **Publish**. Inspect the normal authenticated POST to
   `/cards/mcp/approve` in DevTools; it should include `as_predicate="is_learning"`.
5. Reload the inbox, public card, and Alice's MCP `get_my_card`.

**Expected:** The approval result identifies `is_learning`, the suggestion leaves
the pending inbox, and the public fact is Learning rather than Expert in. The
Cards API approval response includes a refreshed `zynd_memory` snapshot through
S02. Public propagation depends on the deployed sync/cache path; record a stale
page separately from a successful approval.

Retyping updates the proposed public category; it does not let you silently edit
the suggestion's text. Never use **Publish all** before inspecting each preview.

### F. Dismiss keeps an unwanted fact private and out of the inbox

1. Pick one synthetic private noise suggestion from C.
2. Click **Dismiss** and inspect `POST /cards/mcp/dismiss`.
3. Reload the inbox and open the same owner inbox in another browser tab.
4. Re-report that same typed value once, with the same field/predicate.
5. Reload again and check that the fact is absent from public `get_my_card` too.

**Expected:** Dismissal uses `/dismiss`, not `/revoke` or `/forget`. The matching
suggestion stays hidden after reload and re-report, and remains private Memory.
The reporter can return `saved=false` with skipped items for the dismissed fact.

Dismissal persistence is scoped to the matching stored assertion. It is not a
global learned blacklist: a different predicate/entity spelling or a free-text
extraction path needs separate verification. Explicit later declarations can
also change the fact's state. There is no inbox undo button; use expendable
suggestions for this test.

### G. Bulk review applies each owner's decision

**Not run on prod by default.** Use isolated fixtures, or explicitly selected
production test suggestions whose previews you intend to publish/dismiss.

1. Prepare two eligible facts in **Looks right**, inspect both previews, and
   choose **Publish all** for that group.
2. Prepare two noise suggestions and choose **Dismiss all** in **Probably noise**.
3. Reload and inspect each individual result.

**Expected:** Actions apply to that group's visible items; they do not approve
every private fact in the account. **Probably noise** has Dismiss all and
individual Publish after expansion, but no group Publish all button.

Bulk operations run sequential individual requests, not one transaction. A
partial failure can leave some items completed and others pending; inspect each
row/status rather than assuming all-or-nothing behavior. A last successful item
can clear the displayed error from an earlier failed item, so retain Network
evidence in failure testing.

### H. Failed review requests preserve the pending suggestion

1. In your own browser's DevTools, block only the intended request path, e.g.
   `*/cards/mcp/approve`.
2. Click Publish on one test suggestion.
3. Confirm an error appears and the row stays pending.
4. Remove the block and retry only if you still want that fact public.
5. Repeat for `/cards/mcp/dismiss` with an expendable suggestion.

**Expected:** The UI removes an item only after a successful response. It retains
the item on a failed request and provides an error message. Reloading suggestions
resolves the actual state if an operation succeeded but its response was lost.

If loading suggestions fails, the component can display both its empty-state
text and an error. **Nothing to review** alongside an error is not proof that the
account has no pending facts. Do not disconnect the production Memory service to
simulate this; blocking your own browser request is sufficient.

### I. Other accounts cannot review Alice's facts

1. Open the inbox signed out; it should require the normal signed-in owner flow.
2. Sign in as Bob and inspect Bob's own review queue.
3. With a developer using normal test-user sessions, check that requests to the
   Cards review API derive the owner from the session rather than a supplied email.

**Expected:** Bob sees only Bob's suggestions. Unauthenticated review requests
return `401`; no production auth settings or ownership fields are changed.
Memory `/v1/service/*` endpoints are backend-to-backend routes, not URLs to call
from the browser with a shared service secret.

If testing assistant-driven approval separately, S09's scoped approval tools
require `cards:approve` and explicit confirmation. Having `report_user_info`
available alone does not authorize public approval.

### J. Free text, reporting guidance, and the daily cap

**Free text:** The tool's `role` and `notes` fields, and `remember`, still use
extraction. Report one harmless durable sentence and wait for the extraction
worker. Confirm that any resulting suggestion remains private. Do not require
the same deterministic predicate or immediate timing as the structured lists.

**Guidance:** Inspect the connected server/tool instructions. They should call
for reporting at milestones, batching durable professional facts, avoiding repo
paths/tools-as-projects, and never sending secrets. This is guidance to the
assistant, not automatic rejection of every sensitive string.

**Cap check: Not run on prod.** In isolated fixtures, the helper can prepare 40
active `cards_mcp` assertions counted in the current UTC day and submit another
report. Expect `saved=false` and **daily report cap reached — try again tomorrow**.

The default cap is **40 counted assertions**, not 40 HTTP requests or a hard
40-item batch limit. It is checked once before the report; a report starting
below the cap can cross it. Dismissed/repeated/previously-created assertions
affect the count differently because the query uses `extracted_at` and
`source_system`. Do not promise an exact daily counter or reset by the browser's
local midnight. A strict per-item or concurrent limit is not implemented here.

### K. Inbox presentation works on desktop and mobile

1. Inspect the inbox at desktop width and at approximately 390 px wide.
2. Expand/collapse noise and change a retype dropdown without publishing.
3. Check long fact text, readable previews, reachable actions, and group counts.
4. If a real group is empty, confirm it is omitted. An entirely empty successful
   response should show **Nothing to review right now**.

**Expected:** Each visible row has its suggestion, Shows as preview, category
selector, Publish, and Dismiss controls. Buttons are disabled during a pending
review operation. Noise is collapsed initially. Meaning is shown before approval;
it does not change silently after the owner reviewed the selected preview.

## 4. Implementation limits to record

| Original expectation | Current implementation/evidence limit |
| --- | --- |
| All three triage groups survive capture | Original field context is not retained when rebuilding the inbox; Needs a look cases can become Looks right. |
| Dismiss teaches a general filter | The matching assertion's dismissal sticks; there is no generalized learned filter in this code. |
| One entity across type variants | UI/card surfaces dedupe public predicate families. Entity resolution itself deliberately keeps different entity types separate. |
| Hard daily protection against every excessive batch | Soft pre-report assertion cap; no per-item or concurrent enforcement. |
| Re-reporting approved facts is harmless | Matching assertions can be made private by `declare_for_review`; verify lifecycle replay in isolation. |
| Bulk review is atomic | Sequential requests; partial completion and error-display limits need inspection. |
| Old `test_cards_mcp.py` / standalone MCP files | Capture now lives in `app/mcp_http.py`; the old filenames in the conventions are stale. |

These differences are open findings, not reasons to claim that the original
acceptance criteria have all passed. Record intended behavior and actual behavior
separately when they differ.

## 5. Developer verification outside production

The useful existing checks include:

```bash
cd services/memory
uv run pytest -q tests/test_quality.py tests/test_mcp_http.py
uv run pytest -q tests/test_findability.py tests/test_entities.py
```

The first command checks pure quality helpers and MCP wiring. The second uses
dedicated local Postgres/Redis integration fixtures and mock LLMs; it can skip
without the local dependencies. Do not point these tests at a production database.
They do not cover every `report_user_info` lifecycle/cap case described above.

For the Cards review proxy:

```bash
cd services/cards-api
.venv/bin/python -m pytest -q tests/test_mcp_connector.py
```

Run the normal Memory non-integration suite and Cards API suite before/after
implementation changes. Compare against the actual baseline rather than treating
existing failures or skipped integration tests as new regressions. Mocked tests
do not prove deployed credentials, private persistence, or public-card sync.

## 6. Record results

| Scenario | Result | Notes |
| --- | --- | --- |
| A. Tools vs projects and private capture | Not run | |
| B. Repeated private reports | Not run | Before publication only on prod. |
| C. Noise grouping | Not run | |
| D. Tool-as-project correction | Not run | Needs a look context can be lost. |
| E. Preview, retype, and publish | Not run | |
| F. Persistent dismissal | Not run | Matching assertion only. |
| G. Bulk actions | Not run on prod | Isolated or explicitly selected expendable fixtures. |
| H. Review failure and retry | Not run | Browser-only failure simulation. |
| I. Owner isolation | Not run | |
| J. Text/guidance/cap | Not run | Guidance/text on prod; cap exercise deferred. |
| K. Desktop/mobile/empty state | Not run | |

Use Pass, Fail, Blocked, Not run, or Not run on prod. Record deployed commit,
capture flag, test owner/handle, tool arguments, selected public label, request
status, expected result, and actual result. Screenshots must exclude tokens and
real private data. A tool's `saved=true` and a successful HTTP response are not
substitutes for inspecting the pending and public fact sets.
