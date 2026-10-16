# People Discovery and Profile Links

## Goal and Decisions

Fix recommendation requests such as “suggest some people I can connect to via Zynd” so they check Zynd discovery and QuickEnrich in the same turn and return useful profile links, not names alone.

- Search both sources even when Zynd has strong results. “Via Zynd” names the product; only explicit restrictions such as “Zynd members only” suppress external discovery.
- Distinguish published Zynd Cards, messageable Zynd Network personas, and external prospects. A card does not prove a messageable persona exists.
- Link card results to their canonical Cards pages; link external results to returned LinkedIn profiles or other verified public profile URLs. Never invent links or associate identities by name.
- For generic requests, derive targeting from relevant known goals, interests, and profile context and briefly explain that basis. Ask one focused question only when no defensible targeting criteria exist.
- Discovery does not reveal paid email/phone details or initiate outreach.

## Findings

- `services/persona-api/agent/orchestrator.py:2306` instructs the model to stop after any hit, contradicting thin-results broadening at lines 2405–2417. Formatting asks for bold names without links.
- `mcp/tools/zynd_network.py` returns persona IDs and operational webhooks, not public card handles. `mcp/tools/a2a_network.py::find_best_intro_for_me` is another network-only recommendation path.
- `mcp/tools/quickenrich.py::search_people_database` returns LinkedIn URLs and requires at least one usable targeting filter. Its current error and normalization behavior must remain intact.
- Cards exposes public `GET /v1/agents/search` through cards-api. Search returns published cards and includes `handle` and `claimed`. No existing persona Cards search client or verified persona-to-card mapping exists.
- Cards/persona database cutover is not safe to assume. No direct database integration or schema change is needed.

## Implementation

1. Establish a baseline with `pytest -q` in `services/persona-api`; record actual failures rather than assuming the documented five environment failures. Read service-local instructions before editing. Use mocked external services throughout validation, not live discovery or paid enrichment calls.

2. Add a small read-only Cards HTTP search integration within persona-api, following existing HTTP client/configuration conventions. Use configurable API base URL, defaulting to `https://api.zynd.ai`, and call `/v1/agents/search` with bounded `q`, `limit`, and `include_unclaimed=false`. Require `claimed is True` client-side as well, since the server feature flag can admit unclaimed results. Validate result shape and handles; construct `https://cards.zynd.ai/p/{validated-handle}` rather than trusting the API `url`, whose configured default can still use `zynd.ai`. Keep API origin separate from the canonical public Cards origin. Bound timeouts and classify timeout, bad response, and unavailable-service outcomes independently of empty results. Do not add credentials, auth changes, owner-data access, or cross-database queries.

3. Add one canonical composite people-discovery MCP tool, registered in `mcp/server.py`, reusing existing Zynd persona and QuickEnrich implementations plus the Cards client. Accept a contextual search query, explicit source scope, and structured QuickEnrich filters using the existing supported dimensions; inject `user_id` by the existing mechanism. For ordinary recommendations call Zynd persona search, Cards search, and QuickEnrich once each, regardless of prior results. Keep work bounded and isolate source failures. Explicit Zynd-only scope still searches applicable Zynd sources but not QuickEnrich; preserve distinctions between cards and persona membership. Do not recursively invoke the orchestrator.

4. Return structured source groups with status, count, results, and source-specific errors/unresolved filters. Each candidate retains a source-scoped identifier, role/headline, relevance reason, verified public URL if present, and explicit connection eligibility. A Cards `agent_id` is a card ID, not a persona connection target. Preserve network personas without card links honestly; never expose webhooks as profile links. Deduplicate only on authoritative identifiers within a source; do not merge people across sources by names or inferred matches. External records remain external even if a similar card exists.

5. Consolidate orchestration instructions and tool descriptions so recommendation discovery uses the composite tool in both normal and streaming chat. Remove the conflicting stop-after-any-hit policy for cross-source discovery; prevent duplicate individual source calls after the composite search. Use already-loaded principal context to build filters, not arbitrary defaults. If context is insufficient, ask the targeting question before searching. Cached `get_suggested_people` may inform context but must not substitute for the fresh QuickEnrich check requested here. Preserve explicit single-source searches and unrelated task behavior. Keep LinkedIn scraping outside the mandatory workflow; no new automatic metered scrape requirement.

6. Resolve the introduction-route bypass: broad “who should I connect with / who can introduce me” discovery must use the composite search before final recommendations. Retain `find_best_intro_for_me` where network-specific relationship/intro scoring is needed, but do not let it replace required source discovery. Actual connection, messaging, and intro actions remain unchanged and require a valid persona target; this task does not expand authorization or outreach capabilities.

7. Update final-answer instructions to use compact linked names with a relevance reason, grouped or clearly labelled as “Zynd Cards”, “Zynd Network”, and “External prospects”. Use canonical Cards links for card candidates and returned LinkedIn/public-profile links for external candidates. Retain a small shortlist, normally three total, without sacrificing relevance merely to fill a source quota; disclose when checked sources returned no useful matches. State that cards alone and external prospects are not necessarily messageable through Zynd. When a network persona lacks a public card URL, do not invent one. Distinguish unavailable sources and unresolved filters from “no matches”, and do not claim any source was checked unless it actually was.

## Failure Handling

- Strong Zynd matches must not skip QuickEnrich for ordinary discovery.
- QuickEnrich missing configuration, unresolved filters, or API failures must leave available Zynd results usable and report the limitation. Never drop requested filters silently.
- Cards outages must leave persona and external discovery usable; missing or malformed handles never generate guessed links.
- A missing public URL does not exclude an otherwise relevant candidate; show the available truthful details.
- A partial failure must not trigger paid reveals, repeated unbounded searches, or unsolicited outreach.

## Validation

- Add mocked unit tests for the Cards client: request parameters, claimed/published-result contract, valid canonical links, malformed payload/handle, noncanonical returned `url`, timeout, and HTTP failure.
- Add composite-tool tests proving QuickEnrich runs despite strong/nonempty Zynd results, plus empty results, explicit network-only scope, source failures, unresolved filters, bounded calls, correct source-scoped IDs, and absence of paid enrichment calls.
- Use the fake-provider pattern in `tests/test_action_summary.py` for normal and streaming orchestration regressions: the reported wording, a structured prospect query, known-context targeting, insufficient-context clarification, broad intro recommendations, and unrelated requests that perform no discovery.
- Verify tool-output URLs reach final model context intact and response instructions require linked names and accurate labels. Use a controlled manual dev conversation to inspect actual tool traces and rendered Markdown links, since mocked model text alone cannot establish real model compliance.
- Retain and run `tests/test_quickenrich_tools.py`, `tests/test_persona_match_scoring.py`, `tests/test_public_search.py`, and `tests/test_people_suggestions.py`, then the full persona-api suite. Report only new failures relative to the baseline.

## Rollout and Boundaries

- Backend-only additive integration; no frontend changes expected if existing Markdown links render correctly. Check that assumption during the dev smoke test.
- Confirm the deployed Cards API exposes the documented public search contract before enabling the integration; do not assume monorepo changes are deployed to Cards. Configure the supported endpoint or report unavailability rather than modifying the live Cards service as a side effect.
- Ship through the normal reviewed dev workflow. No production deployment, live SQL, auth changes, schema migrations, identity unification, or paid contact enrichment is authorized by this plan. Any deployment or permission changes require separate human approval.
- No source changes or tests have been performed during planning.
