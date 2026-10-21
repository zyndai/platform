# Cards beta audit implementation

Based on the October 16, 2026 audit. Implemented against this monorepo, not
against the production account used by the auditor.

## Behavior

- Claiming a card no longer writes `love_talking_about` as `is_learning`.
- Extraction distinguishes explicit founding/history from learning. New
  `is_founder_of` and `has_experience_in` predicates have no confidence decay.
  Existing predicate storage is text, so this requires no database DDL.
- Skill/topic validation rejects placeholders and obvious narrative paragraphs.
  Both profile JSON-LD and `data.json` use the same topic normalization. An
  empty canonical CardView does not fall back to stale stored facts.
- Owner review offers historical categories. Invalid topic approvals fail
  before changing review state and return an actionable validation error.
- `list_intros` returns a successful empty list only for a successful empty
  upstream response. Missing linkage, configuration, timeouts and upstream
  failures have distinct codes. Existing UUID identity and MCP scope checks
  are preserved. This does not establish which production dependency caused
  the auditor's original failure; that still requires deployed configuration
  and logs to be inspected by the operator.
- Duplicate hints normalize LinkedIn/GitHub/X URLs, including Twitter aliases.
  A claimed card on another account is a review hint, never merge authority.
  Same-owner merges retain the existing archive, confirmation and redirects.
- Explicit search filters exclude mismatches. Common explicit city/language
  phrases are extracted conservatively; city aliases are normalized. Searches
  with hard constraints page the published corpus before filtering/ranking,
  instead of limiting vector candidates to 200 first. This trades additional
  reads for correctness; SQL filter pushdown is a future scaling optimization.
- Onboarding has a 60-second source deadline and 180-second pipeline deadline.
  Synthesis runs off the event loop. Source failures warn without discarding
  other imports. Browser polling is bounded to 210 seconds, handles missing
  jobs, and preserves the entered inputs.
- Beacons are owner-authored, expire at an explicit timestamp within seven
  days, and support publish/renew/dismiss. They use existing card JSON and an
  updated-at compare-and-swap, with the existing owner authorization. Public
  card/JSON/chat/MCP views exclude expired broadcasts. Search evaluates active
  broadcasts at read time rather than embedding transient requests permanently.
  The public MCP cache is bounded by the earliest fact/beacon expiry.
- Skills accept up to five public evidence links. Actual GitHub repository
  language metadata provides deterministic evidence for matching skills;
  missing evidence is not invented. Owners can add a public source in the
  editor. Public skill tiles open the evidence panel.
- Repository metadata supplies stars and separate live-demo URLs. Work-history
  descriptions render as achievement bullets. Experience years derive from
  supported date ranges, merging concurrent employment periods.
- Truncated post snippets carry an ellipsis. X source metadata records actual
  scrape availability. The booking card offers a click-to-load Calendly dialog
  and keeps direct provider links. Mobile chat placement accounts for safe areas.

The public MCP remains read-only. Existing authenticated Cards connection tools
remain the route for agent-assisted networking. No auth policy, payments, SQL
migration or production data was changed.

## Existing data and rollout

Fixing ingestion does not rewrite previously stored private facts. To prepare
owner-reviewed repairs without writing to any database or service:

```bash
cd services/memory
python scripts/audit_profile_facts.py /path/to/owner-context-export.json
```

The input may be a `get_my_context` packet or a portable context export. Output
contains proposals only. Correct/review facts through the existing owner tools,
then refresh card snapshots and embeddings. Do not bulk-merge claimed accounts
because they share a URL.

Before production release, verify the actual deployment checkouts, URLs, feature
flags and migration state. Deploy Memory API/MCP, Cards API and Cards web as a
coordinated release with explicit production approval. There is no new schema
migration to apply. Account merges and existing-data repairs are separate owner
actions; none were performed during implementation.

The audit's optional `source_repo`/`proof_url` arguments on `report_user_info`,
automatic organization links in narrative text, and language-display preferences
remain follow-ups. Public skill evidence is implemented without exposing private
trace excerpts or filesystem paths.

## Validation

Cards API and Memory suites are compared against pre-change runs using dummy
external credentials. The baseline has two X-bot failures in Cards and two
social-tool failures in Memory in the test environment. Database-dependent tests
are reported separately by pytest.

Regression coverage includes classification, topic sanitation, strict search
beyond the old candidate limit, duplicate hints, onboarding timeouts, concurrent
beacon edits, exact expiry, MCP cache expiry and source-backed evidence. Browser
checks exercise public metadata, evidence, booking, beacon lifecycle, mobile
layout, onboarding recovery and the existing smoke/editor/memory flows.

Verified results:

| Check | Result |
| --- | --- |
| Cards API | 527 passed, 23 skipped; the same two baseline X-bot failures |
| Memory (not integration) | 674 passed, 188 deselected; the same two baseline social-tool failures |
| Final targeted Cards checks | 130 passed |
| TypeScript helper tests | 19 passed |
| Browser regression/smoke/editor checks | 27 passed; four audit flows passed again after final visual/polling corrections |
| Web lint and TypeScript | Passed; 25 existing lint warnings remain |
| Production web build | Passed with service URLs pointed at the local fixture address |

The pre-existing chat-widget React immutability lint error was also corrected
while changing its mobile placement.
