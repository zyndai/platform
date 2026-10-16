# S06: understand it and test it on production

S06 makes approved public Memory facts useful when someone views your card,
searches for you, or asks your card's assistant a question.

This is a test plan, not a record of production tests already run. It follows
local `dev` commit **`4f6a533`** (2026-10-14). Confirm the deployed production
commit separately; pulling code does not update the running services or web
build. The original scope is
[S06 CardView and discovery](../conventions/S06-cardview-and-memory-in-discovery.md).

## 1. What is S06, in simple terms?

Imagine Alice's card says she is a Python engineer. Later, her assistant suggests:

> Alice is building a study planner called StudyPilot.

Alice reviews that suggestion and chooses to publish it. S06 should then help:

| Where someone looks | What the approved fact should help them learn |
| --- | --- |
| Alice's public card | Alice is building StudyPilot. |
| Search | A search for StudyPilot can find Alice and explain the fact that matched. |
| Public `data.json` | An AI client can read the fact, its source, approval date, and expiry. |
| Alice's card assistant | It can answer a question about StudyPilot using Alice's public information. |
| Full AI reference file | Alice's entry can include the approved project fact. |

The shared public representation is called **CardView**. Think of it as a
prepared version of the card containing public information and facts that are
still current. Each surface formats that information for its audience.

Some facts become outdated quickly. For example, “looking for a co-founder”
expires seven days after approval in this implementation. “Building StudyPilot”
lasts 60 days. Expiry hides the fact from the current public view; it does not
delete the original Memory record.

The related features do different jobs: **S05** improves how suggestions are
captured and reviewed; **S02** refreshes the public card after your decision;
**S06** uses those public facts in discovery and answers. **S04** counts visits
and actions. S04 analytics do not need to work for S06 facts to work.

The intended promise is consistency across surfaces. The pulled implementation
still has fallbacks and summaries that need separate checks below. An HTTP
`200` only proves a request succeeded; inspect its contents to test S06.

## 2. Prepare your production test

| Person/session | Purpose |
| --- | --- |
| Alice | Your test account with a claimed, public card and linked Memory account. |
| Alice's authenticated assistant | Supplies a suitable pending suggestion through Memory MCP, if needed. |
| Incognito browser | Checks exactly what an anonymous visitor can read. |
| Developer helper | Confirms deployed configuration, propagation, and existing backfill evidence. |

| Production surface | URL |
| --- | --- |
| Public card | `https://cards.zynd.ai/p/alice-dev` |
| Review inbox | `https://cards.zynd.ai/p/alice-dev/edit#inbox` |
| Canonical public API view | `https://cards.api.zynd.ai/cards/by-handle/alice-dev/view` |
| Public entity JSON | `https://cards.zynd.ai/p/alice-dev/data.json` |
| Search API | `https://cards.api.zynd.ai/ask` |
| Authenticated Memory MCP | `https://api.zynd.ai/mcp` |
| Optional public Cards MCP | `https://api.zynd.ai/cards-public-mcp` |

Replace `alice-dev` with your own designated production test handle. Confirm
these origins against the deployment. The checked-in
[single-box setup](../infra/single-box/README.md) also has dev services that share
production data; a dev hostname does not provide an isolated database.

### Confirm the existing prerequisites

| Setting/dependency | Expected state |
| --- | --- |
| Cards API | `FEATURE_S06_CARDVIEW=true`, and the intended Cards database/schema. The API flag defaults to true. |
| Cards web build | `NEXT_PUBLIC_FEATURE_S06_CARDVIEW=true`. The web env example defaults to false. |
| Web API origin | `NEXT_PUBLIC_API_URL=https://cards.api.zynd.ai`. |
| Public citations | API `SITE_BASE_URL=https://cards.zynd.ai` and web `NEXT_PUBLIC_SITE_URL=https://cards.zynd.ai`. The API default is still `https://zynd.ai`. |
| Public snapshot bridge | Working `MEMORY_LAYER_URL` and matching `MEMORY_SERVICE_TOKEN`; Alice's sign-in and Memory connection identify the same owner. |
| Snapshot refresh | Existing approve/revoke flow can refresh Alice's stored `zynd_memory` snapshot. |
| Cache invalidation | API `WEB_REVALIDATE_URL` reaches the web revalidation route; its configured `WEB_REVALIDATE_SECRET` matches the web setting. Do not copy the secret into notes. |
| Search embeddings | Existing embedding provider and database vector/search RPCs are available; helper confirms whether older cards were backfilled. |
| Optional chat | API `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_AI_KEY` configure the chat provider. |
| Optional public MCP | Running Memory MCP has `FEATURE_S11_PUBLIC_MCP=true` and can reach Cards API. |

These are values to verify, not instructions to change production configuration.
Web flags are baked into the build. S06 adds no dedicated migration in this
checkout; the existing Cards/Memory schema and relevant preceding migrations
still need to be ready. If the S10 snapshot-update path is enabled, its deployed
RPC/migrations must also be present.

Missing prerequisites are **Blocked** findings. Production deployments, SQL,
and schema changes require human approval under [AGENTS.md](../AGENTS.md).
This walkthrough does not deploy, migrate, run a global refresh, or re-embed
production cards.

Choose one small, harmless fact that Alice actually wants public. “StudyPilot”
is an example: use your own project or a designated disposable test fact.
Prefer a distinctive project name absent from the card's headline, summary,
skills, and existing projects, so you can tell a Memory match from a normal
profile match. Record the original card state and approval time in UTC.

Have one harmless pending suggestion remain unapproved for the privacy check.
Do not use secrets or real sensitive information as test markers. Reporting
creates production Memory records and Publish makes the selected fact public.
Use [S05 manual testing](S05_MANUAL_TESTING.md) if you need to create a suggestion.

Run A–G and existing-fixture checks in H–K. Backdated fixtures, flag changes,
backend failures, and embedding backfill execution belong in L's isolated test.
Your earlier S04 invalid-event `204` does not block these content checks; it
does block any separate claim that visits or chat events were recorded.

## 3. Manual scenarios

### A. Record the baseline and keep pending information private

1. Sign in as Alice and confirm the project suggestion is pending in her inbox.
2. In incognito, open her public card and the two JSON URLs below.
3. Search for the distinctive project name and record any existing result/reason.
4. Confirm the pending fact's text is absent from the public fact lists.

```bash
curl -i https://cards.api.zynd.ai/cards/by-handle/alice-dev/view
curl -i https://cards.zynd.ai/p/alice-dev/data.json
curl -sS --get 'https://cards.api.zynd.ai/ask' --data-urlencode 'q=StudyPilot'
```

**Expected:** A claimed public card returns `200` from `/view` with `claimed=true`
and a `facts` array. Pending suggestions are private. An existing search result
can be valid if other public information matches; its mere presence does not
prove that a pending fact leaked. Inspect the displayed match reason and content.

### B. Publish one fact and inspect the canonical view

1. In Alice's inbox, read **Shows as** and Publish the suitable project fact.
2. Record the approve request's status and UTC time in DevTools Network.
3. Fetch `/cards/by-handle/alice-dev/view` again and inspect `facts`.
4. Confirm the other unapproved suggestion remains absent.

**Expected:** The published project appears as a nonempty fact with `text`,
`type`, `source`, `approved_at`, `expires_at`, and `confidence` fields. For an
`is_building` fact with a valid approval timestamp, expiry is approval plus
60 days. Confidence can be null; it is not a guarantee that the fact is true.
`cite_as` points to Alice's production card, and `fresh_as_of` reflects the card
update timestamp.

An approval response alone does not prove propagation succeeded. Public reads
use the stored Cards snapshot, rather than fetching Memory on every request.
If the fact remains missing, record the delay and have the helper inspect the
snapshot-refresh response/logs. Do not edit the database to make the test pass.

Older facts can have missing metadata. Record that limitation rather than
inventing an approval date. `fresh_as_of` is not proof that every fact was
individually checked at that time.

### C. Compare the public page and `data.json`

1. Reload Alice's public card in incognito and find the approved project.
2. Fetch `/p/alice-dev/data.json` and inspect `zynd:facts`.
3. Compare the fact's text, type, approval date, expiry, and source with `/view`.
4. Check `zynd:cite_as` and `zynd:verified_at` at the JSON's top level.

**Expected:** The page shows the approved project in its public Memory section;
the JSON includes its provenance and expiry. Friendly page labels can differ
from the raw text, so compare meaning as well as spelling. Citation is a
top-level value, not a field repeated inside every fact.

The page can show **LIVE** or an **Xd left** chip. That chip is based on expiry;
it does not prove a new assistant connection or a fresh fetch from Memory.
Only the implemented public fact families appear in the page's grouped block.

Web API reads normally revalidate after 60 seconds unless the S10 web setting
uses `no-store`; `data.json` can also have shared-cache stale responses. Record
the response's cache headers and observed delay. The configured revalidation
hook should help approvals reach the page. Do not clear shared production caches
to force an outcome. If `/view` updates but the web stays stale, record a
propagation failure with the actual URLs/times.

### D. Check the page's structured data

**Prepare:** Use existing approved expertise/learning or affiliation facts. If
Alice only has a project fact, check the basic identity/citation and mark those
extra mappings Blocked; do not publish a fictional employer to fill the fixture.

1. Inspect the public page's `application/ld+json` script in DevTools or page source.
2. Find the `ProfilePage` object's `mainEntity` (`Person`).
3. Compare its name, job title, `knowsAbout`, and any `worksFor` with Alice's
   public profile and eligible facts.
4. Confirm the private pending marker is absent.

**Expected:** Headline supplies `jobTitle`; approved expertise/learning can add
to `knowsAbout`; an approved affiliation can add to `worksFor`. Structured data
contains selected mappings, not a full copy of every project fact. A project
need not appear as `worksFor` or a JSON-LD fact array.

Record that `data.json` also derives `worksFor` from current work experience,
while page JSON-LD currently derives that list from affiliation facts. Identical
JSON shapes are not a requirement; contradictory or private information is a
finding against the consistency/privacy requirement.

### E. Find Alice by the approved fact

1. Repeat A's exact search using the production Cards API.
2. Find Alice's result and inspect `match_reasons`.
3. Try the site's search interface and compare its displayed reason.

**Expected:** With the API S06 flag enabled, a matching fact can produce a reason
like `{"type":"memory","text":"StudyPilot"}`. The UI formats these reasons
alongside ordinary string reasons. Recent facts receive a modest freshness boost.

Do not require Alice to rank first. Search reasons use query-token matching,
not a semantic explanation of every word in the request. Candidate selection
depends on stored embeddings and deployed search RPCs. The generated full-text
column covers name, headline, summary, and skills; it does not independently
index the Memory array. A Memory-only match can therefore depend on a successful
embedding refresh/backfill. Capture an absent result as a discovery finding and
check the embedding path before concluding approval failed.

### F. Ask Alice's card assistant about the project

1. In a fresh incognito chat, ask **What is Alice building?** or a short question
   about the actual approved project.
2. Inspect the chat request and streamed response, not the seeded welcome demo.
3. Compare the answer with `/view` and Alice's public page.

**Expected:** The assistant can use the approved live project fact. It should
describe Alice accurately, avoid inventing details, and identify itself as an
assistant. It should not disclose pending/private facts. Answers need not repeat
every fact or use identical wording.

The prompt includes at most 12 live Memory facts. For a card with more facts,
check which facts are supplied before requiring an answer about a later item.
An answer is generated text, not a full snapshot-comparison test.

Missing provider/card prerequisites can produce `503`, `403`, or `404`; invalid
chat content can produce `400` and ordinary throttling `429`. Record the actual
failure. Do not burst requests or disable the production provider for this test.
Use a fresh chat after approval/revocation so old conversation messages do not
supply the previous fact. S04 chat-event recording is a separate check.

### G. Inspect the AI reference files

```bash
curl -sS https://cards.zynd.ai/llms.txt
curl -sS https://cards.zynd.ai/llms-full.txt
```

Find Alice's entry if she is included in the returned directory list.

**Expected:** Both files exclude unclaimed cards and provide public citations.
With the web S06 flag enabled and `/view` available, `llms-full.txt` includes
up to the first six live facts under **Approved facts**. A later fact need not
appear in that summary. Record listing limits if Alice is outside the returned
directory rather than assuming her card is missing from all public surfaces.

**Current limit:** `llms.txt` still uses the stored citation snippet/summary as
its blurb; it does not append the approved fact list. S06 supplies its citation,
but identical fact coverage across both files is not implemented. The files
also contain legacy `api.zynd.ai/ask` guidance; confirm those links separately
against live routing rather than treating them as the Cards API origin.

### H. Check expiry using an existing eligible fact

Use an already-approved test fact with a known UTC approval time. On production,
observe a naturally expired fact or return after its expiry. If none is
available, mark the live expiry check Blocked and use isolated regression evidence.
Do not backdate rows or change a server clock.

| Fact type | Canonical expiry |
| --- | --- |
| `is_seeking` | Approval + 7 days. |
| `is_working_on` | Approval + 14 days. |
| `is_building` | Approval + 60 days. |
| Other type with valid `half_life_days` metadata | Approval + that number of days. |
| No usable lifetime or approval timestamp | No computed expiry. |

**Expected requirement:** After expiry, the fact leaves `/view`, the page's
current facts, `data.json`, full reference facts, and a fresh chat's fact context.
Search should no longer explain a match using that expired Memory fact. Other
static profile information can still match, so card disappearance is not proof
of expiry and continued presence is not automatically a failure.

**Known consistency gap:** When CardView has an empty fact list, the page and
`data.json` fall back to raw `zynd_memory`. That fallback handles only the first
three lifetimes above and ignores other `half_life_days`. An expired learning
fact can therefore reappear if the canonical list becomes empty. Record this
as an open requirement gap; do not mark all expiry cases passed from seeking
alone. JSON-LD uses CardView facts and can disagree with that fallback.

Time passing does not itself trigger re-embedding. An old vector can still
retrieve/score the card even after current fact text/reasons drop the expired
item. Authenticated Memory `get_my_card` can also retain the approved record;
S06's canonical public view applies expiry to that stored snapshot.

### I. Check removal after an intentional public-fact revocation

**Optional on production:** Use only a disposable fact Alice intends to unpublish.
Otherwise inspect an existing removal or run this branch in isolation. Revocation
changes public content; do not revoke someone else's facts or real useful facts
just to exercise the feature.

1. Record the current public fact and intentionally revoke it through Alice's
   normal owner review controls.
2. Inspect `/view`, the page, `data.json`, and the full reference file again.
3. Repeat the same search and start a new chat.
4. If it was the last public fact, check the empty state explicitly.

**Expected:** The refreshed public snapshot drops the revoked fact. `/view`
has `facts=[]` when none remain; `data.json` omits `zynd:facts` when empty, rather
than emitting empty objects. The page has no current item for that fact and
search has no Memory reason containing it. Static summary/projects, older chat
messages, or other approved facts may still contain the same words; inspect
those separately before calling it a leak.

A connected account with zero public facts should clear the snapshot. A failed
Memory fetch preserves the previous snapshot instead. Record stale content
after a revocation as a propagation finding. The S10 snapshot-update path clears
the previous vector before recomputing; the legacy path can retain an old vector
if embedding fails. Neither a `200` revoke response nor a search result alone
establishes complete removal from every surface.

### J. Check public-access boundaries

1. Fetch `/view` for a handle that does not exist.
2. If there is an existing unclaimed test card, fetch its `/view` and `data.json`.
3. If there is an existing private test card, try its public URLs in incognito.
4. Check that Alice's pending suggestions remain private throughout A–I.

**Expected:** Missing/unpublished cards return `404` from the canonical view.
An unclaimed card returns `404` from `/view`; its web `data.json` returns `410`
with a minimal unclaimed marker rather than a public fact list. Private cards
must not expose their content through these public routes. Missing fixtures are
Blocked; use [S10 manual testing](S10_MANUAL_TESTING.md) for deliberate visibility
changes on a designated test card.

**Privacy boundary:** CardView trusts the stored public-only snapshot. Its
builder does not independently enforce per-fact `is_public`/approval flags.
Privacy therefore depends on the upstream S02/Memory selection being correct.
Do not insert a private marker directly into a production snapshot to test it.

### K. Optional: compare public MCP reads

If S11 is already enabled, connect a public MCP client to
`https://api.zynd.ai/cards-public-mcp`:

1. Call `get_card` with Alice's actual handle and compare its fact text/provenance
   with `/view`.
2. Call `search_people` using the distinctive approved project name.
3. If chat is configured, call `ask_card` with a short project question.

**Expected:** Public tools respect the same public facts and card eligibility.
`get_card` has a configured cache TTL (default 60 seconds); record that delay
when checking approval/removal. Do not require a cache hit to emit another S04
event. Tool availability and end-to-end MCP behavior are also covered by S11.

### L. Isolated-only: backfill, failures, and flag behavior

**Not run on production by default.** Use an isolated Cards/Memory database and
mocked providers or a separately approved embedding budget. A local server
pointing at production Supabase is not isolated.

1. Prepare two claimed published cards, including an older card whose distinctive
   approved fact is missing from its stored embedding.
2. Run `scripts/reembed_all.py --limit 2` as a dry run, inspect the selected
   handles, then run the same batch with `--apply` only in that isolated setup.
3. Compare search results; test continuation with `--after-handle` and inspect
   failures individually. This script changes vectors, not card ownership/content.
4. Use controlled test time/dated fixtures for expiry, including metadata-driven
   expiry with an empty CardView. Do not wait weeks or change shared clocks.
5. Simulate snapshot/embedding/revalidation failures separately and compare
   current facts, stale web output, and search reasons.
6. Turn S06 flags off/on in the disposable deployment and rebuild web when needed.

**Expected/current limits:** Dry run performs no embedding writes. `--apply`
processes published cards in handle order and supports offset/limit/after-handle.
An empty provider vector is skipped; track attempted and successful coverage,
not just process exit status. Resuming after the last success can skip earlier
failed handles, so inspect/retry failures explicitly. A reported resume point
does not establish that the backfill completed for every card.

| Flag state | Current implementation to verify in isolation |
| --- | --- |
| API `FEATURE_S06_CARDVIEW=false` | Search still uses live Memory text; its Memory reason becomes the string **Approved fact**, and the extra freshness boost stops. `/view` and chat's CardView facts remain available. |
| Web `NEXT_PUBLIC_FEATURE_S06_CARDVIEW=false` | Web stops requesting CardView. Page/JSON use the raw-snapshot fallback; full reference stops adding its CardView facts. |

Turning flags off is not a complete rollback of Memory discovery and does not
erase enriched embeddings. Production backfill, flag changes, and failure
injection need the maintainer's separate approval/process.

## 4. Record your results

Record deployment/commit, flags, handle, UTC run window, fact type/text, approval
and expiry timestamps, request status/body, cache headers, and the actual result.
Use **Pass**, **Fail**, **Blocked**, **Not run**, or **Not run on prod**. Keep
requirement gaps visible even when the current implementation is reproduced.

| Scenario | Result | Observation |
| --- | --- | --- |
| A. Baseline/private suggestions | Not run | |
| B. Approval and canonical facts | Not run | |
| C. Page and JSON parity | Not run | Cache and empty-fact fallback limits. |
| D. Structured-data mappings | Not run | Selected mappings, not every fact. |
| E. Memory search/reasons | Not run | Embedding refresh and candidate coverage. |
| F. Assistant uses live public facts | Not run | Provider required; first 12 facts in prompt. |
| G. AI reference files | Not run | Brief file has no fact list; full file uses first six. |
| H. Expiry | Not run | Existing production fixture only; metadata fallback gap. |
| I. Intentional removal | Not run | Own disposable fact or isolated fixture. |
| J. Public-access boundaries | Not run | |
| K. Public MCP parity | Not run | Optional S11/cache prerequisites. |
| L. Backfill/failure/flag tests | Not run on prod | Isolated regression and maintainer evidence. |

For a failure, record the steps, expected result, actual result, and which
surface first diverged. Keep tokens, secrets, and private inbox contents out of
shared screenshots. This guide does not establish production readiness by itself.

## 5. Developer checks and troubleshooting

Run mocked checks outside the production service environment, with production
credentials removed and external dependencies isolated. Follow
[local development](LOCAL_DEV.md) for the checkout's test setup.

```bash
cd services/cards-api
SUPABASE_DB_SCHEMA=cards .venv/bin/python -m pytest -q \
  tests/test_card_view.py tests/test_chat_cardview.py \
  tests/test_publish_and_search.py::test_search_memory_match_string_reason_when_flag_off \
  tests/test_publish_and_search.py::test_search_memory_match_typed_reason_when_flag_on
```

In Memory's separate isolated test environment:

```bash
cd services/memory
uv run pytest -q tests/test_bridge_contract.py tests/test_findability.py
```

Cards checks cover expiry filtering, provenance/contact shaping, embedding text,
chat context, and search reason formats. Memory checks cover the existing bridge
contract and private-to-public approval flow; database integration checks can
skip without local Postgres. These tests do not prove production propagation,
embedding backfill, browser/cache parity, or actual model answers. Compare full
suite failures before/after under the same isolated configuration; do not mistake
legacy-schema mock failures for a newly introduced problem.

| Symptom | Check first |
| --- | --- |
| `/view` is `404` | Handle, published status, and claimed ownership; a flag alone does not make an unclaimed card eligible. |
| Approval succeeds but `/view` lacks the fact | Owner-to-Memory link, public findability payload, snapshot refresh/logs. |
| `/view` is current but page/JSON is stale | Built web S06 flag, API origin, revalidation hook, and cache headers/time. |
| Citation points to `zynd.ai` | Running API `SITE_BASE_URL`; API citation currently takes precedence when a view exists. |
| Fact is public but search misses Alice | Embedding refresh/backfill and deployed RPC candidates; full-text indexing alone omits Memory. |
| Result remains after expiry/removal | Other static matches or stale vectors; inspect Memory reasons and public content separately. |
| Expired learning fact reappears on web | Empty-view fallback ignores metadata-driven lifetimes. |
| Assistant cannot mention the fact | Provider response, snapshot freshness, and the prompt's first-12-facts limit. |
| Brief reference omits the project | `llms.txt` currently shows a stored blurb, not the full fact list. |
| S04 rows remain absent | Separate collector/configuration issue; S06 content availability does not prove analytics persistence. |
