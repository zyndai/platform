# ZYND People Search, Suggestions & Recommendations Plan

> **Status:** proposed 2026-10-26. **Phase 0 is implemented on `dev`** (see "Phase 0 as built" below), enabled
> with no flag (AGENTS.md §9: no new env vars). **Phase 1 is implemented** (see "Phase 1 as built"). **Phase 2 is
> implemented** (see "Phase 2 as built"; `cards/0031` applied to aafo by a maintainer; a `db:migrate` dry run then showed nothing pending). **Phase 3 is implemented** (see "Phase 3 as built";
> persona dropped: it is a discarded project). What is still unapplied or unchecked is collected in §11 "Left for
> the end".
>
> **Builds on** [`ZYND_MEMORY_QUALITY_PLAN.md`](./ZYND_MEMORY_QUALITY_PLAN.md) Part B (F1–F9, A1–A8), which
> shipped behind flags (see its §17). This plan does not redo that work. It fixes what Part B left broken
> (one of them, R1 below, was introduced by F3) and covers the parts Part B never touched: suggestions,
> score calibration, name lookup, and QuickEnrich quality.
>
> **Scope:** `services/memory` (`find_people`, the people pipeline, the public Cards MCP),
> `services/cards-api` (search scoring, suggested people, digest), `services/persona-api` (discovery and
> suggestions, only to point them at the shared pipeline). Small display changes in `apps/cards-web`.
>
> **Needs a human (AGENTS.md §6):** the prod flag flips in §8, the two `cards` tables in Phase 2 (a
> `packages/db` migration), and turning `FEATURE_FACT_MATCHING` on in prod.
>
> All files and line numbers below are as of `cb9abed` on `dev`.

---

## 1. The problem in plain words

People search is Zynd's main job, and the results are poor across every entry point:

1. **Searching for a named person fails.** "Can you send a request to Chandan from Zynd?" came back with
   "no one named Chandan, and the cards index is unavailable", in both ChatGPT and Claude. Chandan
   Kumar has a claimed, published Card.
2. **Role searches return the wrong people.** "Seed-stage investor who backs AI dev tools in India"
   returns product managers and students from Zynd. From LinkedIn (QuickEnrich) it returns "Investor
   Grievance" officers and an investor-relations PR manager.
3. **Suggestions don't help.** The weekly digest and owner home suggest people who want the *same*
   things as you, not people you'd want to meet. They show the same two people every week, can include
   people you're already connected to, and give many cards nothing at all.
4. **Every surface works differently.** Four entry points run four different pipelines, so a fix in one
   doesn't reach the others.

## 2. Evidence (live, 2026-10-26)

Read-only calls against prod: the Zynd MCP `find_people` tool, and the public Cards API
`https://cards.api.zynd.ai/v1/agents/search`.

| Query | What came back | Why (section 3) |
|---|---|---|
| `find_people("chandan")` | 5 unrelated Zynd members, score ≈ 0.25, `why: "Matches their Zynd profile"`. Chandan Kumar missing. | R1, R3, R7 |
| Cards API `q=chandan` | **Chandan Kumar (`chandan-kumar-2en8`) first, 0.389** | Cards handles names on its own |
| Cards API `q=chandan&skills=chandan` (what memory sends) | **0 results** | R1 |
| Cards API, investor query **with** memory's `role`/`location`/`skills` | **0 results** | R1, R2 |
| Cards API, investor query with `q` only | 5 non-investors scored **0.78–0.81** (a co-founder, a software developer, an AI engineer, a PM, a student) | R5 |
| `find_people(investor query, sources="quickenrich")` | "Investor at DRS Financial Service", "Investor Grievance at Dayco Securities", "Investor Grievances / Compliance Officer at KIIFB", "Investor Communications and PR at MedGenome", one real angel. 3 of 5 have no LinkedIn URL; none has a location. | R8, R9, R10 |
| Before the env fix | every call warned `quickenrich_not_configured` | config, fixed 2026-10-26 |
| After the env fix, `find_people("chandan")` | warning `quickenrich_query_too_vague` | R3 |

## 3. Root causes

Each cause has an ID that the phases in section 6 refer to.

### A. The query is turned into the wrong filters

**R1. Topics are sent to Cards as required skills.**
`memory/app/services/people_discovery.py:156-157` sends `query.topics` as Cards' `skills` parameter.
Cards treats `skills` as a filter that every result must pass (`cards-api/services/search_constraints.py:63`),
and filtered searches page the whole corpus and drop anything that fails (`search.py:145-150, 169`). So:

- a name ("chandan") becomes a required skill → nobody matches;
- an LLM-invented topic ("technology innovation") becomes a required skill → nobody matches;
- "from zynd" becomes the topic "zynd" → nobody matches.

This came from Part B's F3 ("pass the parsed filters"). Parsed topics are guesses and must be soft.

**R2. Role and location are also required, with no fallback.**
`location="India"` requires the word "india" in the card's location (`search_constraints.py:65`), so a
card that says "Gurgaon" is dropped. Nothing loosens the filters when the strict search returns zero.
The Cards scorer also infers a location from the free text ("in India", `search.py:138-140`), so even a
`q`-only call is filtered by location.

**R3. There is no idea of "this is a name".**
Every query goes through role/topic/location parsing (`people_query.parse_target`). A name gets parsed as
a topic, and the QuickEnrich step answers `quickenrich_query_too_vague` (`people_discovery.py:101-102`)
because a name gives it no title or company.

**R4. The LLM parser adds topics the user never said.**
`people_query._merge_llm` (`people_query.py:333-357`) replaces the heuristic topics with whatever the
model returns. The model's output for the investor query included "technology innovation" and
"software innovation", although the prompt says "never invent anything". Nothing checks that a topic
comes from the query text.

### B. Scores can't be compared, so "strong" means nothing

**R5. The Cards score adds up bonuses.** `search.py:178-264` adds similarity×0.5, term coverage 0.25,
location 0.3, facts 0.2, freshness, skills 0.25, industry 0.2, two-way 0.15… and caps the sum at 1.0.
A requested role that's missing costs nothing when the role isn't a filter. Being in India adds a flat
0.3, so a non-investor in India with average similarity scores 0.8. The only floor is 0.2
(`search.py:285-286`).

**R6. Memory sorts three different scales together.** `people_results.py`: Cards uses its added-up
`match_score`, Zynd uses vector similarity (≈ 0.25–0.6), and LinkedIn people get a fixed
`0.3 − 0.01 × index` (`EXTERNAL_BASE`). `STRONG_MATCH = 0.5`, the threshold that decides whether to
call QuickEnrich (`people_search.py:174-176`), compares all three against one number. Being found by
both Cards and Zynd adds `ZYND_BONUS = 0.1`, even when both scores are weak.

**R7. Zynd results have no floor, and prod uses the blurry matcher.** `FEATURE_FACT_MATCHING` is on in
dev (`infra/single-box/docker-compose.dev.yml:36`) and off in prod (`memory/app/config.py:74`). So prod
compares the query with one averaged vector per person (`matching.py:253-266`) and gets similar scores
for everyone in tech. There's no minimum, so the 5 nearest members always come back, and the reason
shown is the generic "Matches their Zynd profile" (`people_results.py:83-84`) because `matched_on` only
exists in the per-fact path.

### C. QuickEnrich requests and results are crude

**R8. The request is too loose.** `quickenrich_body` (`people_discovery.py:87-107`):
- `title include ["Investor", "Venture Partner", "General Partner"]` matches any title containing
  "Investor", including Grievance, Relations and Communications. There's no `exclude`.
- The funding stage ("seed") is parsed but never sent.
- Company keywords are split into single words (`company_keywords`, lines 72-84): "AI dev tools"
  becomes `["AI", "dev"]` and "AI development" becomes `["AI", "development"]`.

**R9. The result shaping drops data.** `search_quickenrich` (`people_discovery.py:257-279`) keeps
name, title, company and LinkedIn URL only, and throws away city, locality and country. That's why
every result has `location: ""`. The URL goes through `_public_url` (lines 35-49), which returns ""
unless the value starts with `http(s)://`. QuickEnrich probably returns some URLs without a scheme
(persona's client keeps them raw, `persona-api/mcp/tools/quickenrich.py:153`). Confirm with one raw
response before fixing.

**R10. LinkedIn results are never re-ranked.** They keep the provider's order with a fixed score.
Title fit, location and company are available but unused. Memory's client also has no cache, unlike
persona's `enriched_contacts`, and its 12s timeout sits on the request path after Cards and Zynd have
finished.

### D. Suggestions find people like you, and repeat

**R11. Cards suggestions match the same wants, not complementary ones.**
`cards-api/services/suggested_people.py:278-281` intersects each field with the same field, including
`connect_with ∩ connect_with`. Two people who both want to meet investors are suggested to each other.
The complementary logic already exists in `two_way.py` (`kinds_of` vs `wanted_kinds`) but isn't used.

**R12. Only a fixed word list counts.** `KEYWORDS` has 18 labels per field plus a few `_ALIASES`
(`suggested_people.py:17-79`). Any free-text card value that isn't on the list is dropped, so a card
whose fields are all free text gets `people: []` (line 259-260).

**R13. Same people every week, including ones you already know.** The score is the number of shared
labels and ties sort by handle (`suggested_people.py:287`), so the top 2 rarely change. Nothing
excludes connected or pending people, people the owner hid (`match_prefs`), or unclaimed cards: it
reads `list_published_rows` with no owner filter (line 266). Each call scans every published card, and
the digest calls it once per card, so the weekly run is quadratic in the number of cards.

**R14. Dead code in the digest and too little outside search.** `digest.py:148` sorts suggestions by
`p.get("two_way")`, but `get_suggested_people` never sets that field. The outside (LinkedIn) search
keeps one person per request (`break` at `suggested_people.py:232`), and its titles (`_TITLE_FOR`:
"Investor", "Mentor", "Healthcare") have the same loose matching as R8.

**R15. Persona suggestions are LinkedIn-only lookalikes.** `persona-api/services/people_suggestions.py`
runs "same role / same company / near you / shared interests" recipes against QuickEnrich only. That
gives people *like* the user whom they can't connect with on Zynd. The score adds `has_email` +0.5 and
`has_phone` +0.25 (lines 431-435), which measures whether someone can be reached, not whether they're
relevant. Persona is paused (the code comments say so, as does the memory quality plan Part B), so this
is lower priority.

### E. Split pipelines

**R16. Four entry points, four logics.**

| Surface | Code | Sources | Ranking | QuickEnrich |
|---|---|---|---|---|
| Owner MCP `find_people` (ChatGPT, Claude) | `memory/app/mcp_http.py:559` → `people_search.find` | Cards + Zynd + QE fallback | memory merge (R6) | yes, fallback only |
| Public Cards MCP `search_people` | `memory/app/cards_public_mcp.py:383` | Cards only (`/ask` or `/v1/agents/search`) | Cards scorer | **no** |
| Persona `discover_people` | `persona-api/mcp/tools/people_discovery.py:124` | personas + Cards + QE, in separate groups | none (three lists) | yes, own client |
| cards-web `/search`, `/directory`, `/ask` | `cards-api/api/agents.py`, `api/ask.py` | Cards | Cards scorer | no |

Plus two suggestion systems (R11–R15) and two QuickEnrich clients (memory's async one, persona's sync
one with enum lookups and caching).

### F. Nothing measures quality

**R17.** Cards has a golden set (`cards-api/tests/fixtures/search_golden.json`: 52 queries, 41
synthetic cards) that tests `search_agents` with **hand-written** filters. It never tests the
parameters memory actually sends, which is how R1 shipped. It has no name queries and no
city-vs-country cases. Memory's mapping has unit tests but no end-to-end golden test. Online, the
`search` event records result handles (`cards-api/api/agents.py:26-38`), but nothing links a result
to the connection request or acceptance that followed.

---

## 4. Decisions this plan proposes

| # | Decision | Why |
|---|---|---|
| D1 | **Guesses are soft; only explicit asks are filters.** Parsed topics are never required. Skills are required only when the user asked for them ("knows Rust", or a UI filter). Role and location are required at first, then loosened step by step when results run short. | R1, R2 |
| D2 | **Search knows three intents:** `name`, `target`, `like_me`. | R3 |
| D3 | **One scorer, scaled 0–1 and calibrated,** shared by every source after retrieval. "Strong match" means meeting the requested role plus a topic or the location, not a number. | R5, R6, R10 |
| D4 | **Every result has a specific reason,** and every empty result says why. | R7, UX |
| D5 | **Suggestions are a search** run on the owner's own "who I want to meet", through the same pipeline, complementary by construction. | R11–R14 |
| D6 | **Memory owns the pipeline;** Cards owns the index and its scorer. Every surface calls memory, either in-process or through one service endpoint. | R16 |
| D7 | **No scoring change ships without the golden set,** and the golden set tests what memory actually sends. | R17 |

## 5. Target design

```
target ─► intent ─┬─ name ─────► Cards name lookup ─► (company given?) QE company search + name match
                  │
                  ├─ target ───► parse (heuristic + grounded LLM)
                  │                │
                  │                ├─► Cards hybrid search (soft topics, strict role/location, loosened on shortage)
                  │                ├─► Zynd per-fact match (with a floor)
                  │                └─► QuickEnrich (when too few strong matches; per-role include/exclude)
                  │
                  └─ like_me ──► own profile text ─► same as target
                                   │
                                   ▼
                     normalize each source ─► one re-rank (role/topic/location fit, two-way,
                     verified, freshness) ─► filters (self, hidden, connected for suggestions,
                     floor) ─► specific "why" + match_quality ─► response with warnings and notes
```

Response additions (backward compatible: new keys only):

```json
{
  "intent": "name | target | like_me",
  "note": "No investors in India matched exactly; showing the closest.",
  "people": [{
    "...existing fields...": "",
    "match_quality": "exact | close | loose",
    "relaxed": ["location"],
    "location": "Bengaluru, India"
  }]
}
```

---

## 6. Implementation plan

Each step lists the change, files, tests and how to know it worked. Phase 0 is code-only and fixes both
cases users hit. Phases 1–3 are larger.

### Phase 0: Stop the bleeding (code only, no schema, ~4 days)

**0.1 Topics become soft (R1, D1).**
- Cards: add a `topics` query parameter to `GET /v1/agents/search` (`api/agents.py`) and
  `search.search_agents`. Topics are scored (term coverage over card text and approved facts, the same
  way `q_terms` are, `search.py:192-222`) and **never** filter. Unknown query parameters are already
  ignored, so old callers are unaffected.
- Memory: `cards_search_params` (`people_discovery.py:142-158`) sends `topics=` instead of `skills=`.
  `skills=` is only sent for explicit skill asks. Reuse the explicit-skill rule Cards already has
  (`search_constraints.explicit_query_constraints`: "knows X", "X developer" for known languages) by
  porting it into `people_query` as `query.required_skills`.
- `group_search` (`people_search.py:97-99`) gets the same change.
- Tests: memory `test_people_discovery.py`, where the params for "chandan" and the investor query must
  contain no `skills`. Cards `test_search*.py`, where `topics` never removes a card.
- Done when the Cards API given memory's exact params for "chandan" returns `chandan-kumar-2en8`.

**0.2 Loosen filters step by step instead of returning zero (R2, D1).**
- Cards: `search_agents(..., relax=False)`. With `relax=True` and fewer than `limit` results, retry in
  this order, stopping as soon as there are enough:
  1. drop `skills`;
  2. widen `location` from a city to its country (needs 0.2b);
  3. drop `location`;
  4. drop `role`.

  Each result carries `relaxed: [...]` and a reason such as "Not in India (closest match)". Results
  from the stricter pass always rank above those from a looser one.
- 0.2b, a small geo table in Cards (`services/geo.py`): city → country code for the cities memory
  already knows (`people_query.CITIES`), plus country names. Location "India" then matches a card in
  "Gurgaon". A copy, to start with; it moves to `packages/contracts` once that exists.
- The cards-web `/search` page keeps `relax=False`: UI filters are explicit.
- Memory sends `relax=true`.
- Tests: golden-set cases "investors in India" with a card in "Gurgaon", and "biotech investor in Pune"
  expecting either nobody or results marked `relaxed`.

**0.3 Name lookup (R3, D2).**
- Memory, `people_query.detect_intent(target) -> ("name", name, company) | ("target", ...) | ("like_me", ...)`.
  A query is a name when, after removing verbs like "send a request to", "connect me with" or "find":
  - it's `@handle`, or "named X" / "called X"; or
  - it's 1–3 words with no role, topic, location or known-skill words. "X from Y" and "X at Y" set
    `company=Y`.
  Ambiguous queries stay `target` (precision first).
- Cards: add `GET /v1/agents/lookup?name=&limit=&include_unclaimed=`, a public search of published Cards
  by name or handle (`ilike`). This reuses the query and ranking in `network.suggest_people`
  (`network.py:226-286`) without the auth and the connection join. Exact full-name match first, then
  prefix, then contains.
- QuickEnrich: its contact-finder has no name filter. The known filters are title, company_name,
  company_url, city, locality, bio_li, industry_linkedin, number_of_employees, revenue, country_code
  and services (`persona-api/mcp/tools/quickenrich.py:38-50`).
  - With a company: run `company_name include [Y]`, then keep records whose first or last name matches.
  - Without one: no external lookup, and the warning `name_needs_company` lets the assistant ask
    "which company?".
- `find_people` docstring (`mcp_http.py:566-590`) and the server instructions: "To find one specific
  person, pass their name, and their company if known."
- Response: `intent: "name"`; exact matches marked `match_quality: "exact"`. For more than one match, a
  `note` that tells them apart by headline and location.
- Tests: memory unit tests for `detect_intent` ("chandan", "Chandan Kumar", "send request to chandan
  from zynd", "@chandan-kumar-2en8", "rust engineer" stays target, "AI" stays target). Golden name cases
  in 0.10.
- Done when "chandan", "Chandan Kumar" and "chandan from zynd" all return `chandan-kumar-2en8` first in
  dev.

**0.4 Keep the LLM's topics grounded (R4).**
- `_merge_llm`: keep an LLM topic only if one of its words (stemmed) appears in the raw query. If every
  LLM topic is dropped, keep the heuristic topics.
- Tests: the investor query keeps "AI dev tools"-style topics and drops "technology innovation".

**0.5 A floor for Zynd results (R7).**
- Drop Zynd-only results below `ZYND_MIN_SCORE` (setting; start at 0.35 for per-fact scores and 0.45
  for averaged-vector scores, then tune in 3.5). Keep a weaker Zynd hit when Cards found the same
  person.
- Never send "Matches their Zynd profile" as the only reason; leave `why` empty and let 1.4 fill it.
- **Human step:** turn on `FEATURE_FACT_MATCHING` in prod after checking dev. The memory quality plan
  §16 makes it depend on Part A Phase 2 (`FEATURE_FACT_FAMILIES`); check that's on first.

**0.6 Better QuickEnrich requests (R8).**
- First, check how QuickEnrich matches with three manual calls: is `include` OR or AND within a field,
  and is `title` a substring or whole-word match? The table below assumes OR and substring, which is
  what the live results suggest.
- A per-role table in `people_query.py` (next to `ROLES`) replaces the bare title tuple:

  | Role | `title.include` | `title.exclude` | Extra |
  |---|---|---|---|
  | investor | Investor, Angel Investor, Venture Partner, General Partner, Managing Partner, Principal, Venture Capitalist | Grievance, Relations, Communications, Compliance, Services, Relationship, Officer | `bio_li` += "venture" or "capital" when there are no topics |
  | founder | Founder, Co-Founder, CEO | Assistant, Executive Assistant | |
  | engineer | Software Engineer, Developer, Engineer | Sales Engineer, Support | |
  | recruiter | Recruiter, Talent | | |
  | … | (one row per `ROLES` key) | | |

- Stage: send "seed", "pre-seed" or "Series A" as an extra `bio_li` word for investors.
- Keep topic phrases whole in `bio_li` ("developer tools", not "developer" and "tools"). Drop words of
  one or two letters only when the phrase has a longer word.
- Tests: `quickenrich_body` for each role, as dict equality.

**0.7 Better QuickEnrich results (R9, R10).**
- `search_quickenrich` keeps `city`, `locality` and `country_code` and builds
  `location: "City, Country"`.
- LinkedIn URLs: add `https://` to scheme-less `linkedin.com/...` values before `_public_url`, after
  confirming the raw format (R9).
- Local re-rank:
  - `title_fit`: 1 when the title contains an include word and no exclude word, 0.5 otherwise.
  - `location_fit`: 1 when the city or country matches the target.
  - `company_fit`: 1 when a topic word appears in the company name.

  The score is `0.30 + 0.25 × mean(fits)`, so LinkedIn people stay below exact Card matches until
  Phase 1 replaces this. Drop records with no name and no URL.
- Tests: shaping and ordering from a fixture of raw QuickEnrich records, including "N/A", a URL without
  a scheme, and a Grievance title.

**0.8 Cache and run in parallel (R10).**
- Cache contact-finder responses in memory's Redis, keyed by `sha256(json body)`, for 7 days. Results
  hold no contact values, only flags.
- When the query is a `target` with a role and `company_hint` (the case where Cards most often comes up
  short), start QuickEnrich alongside Cards and Zynd. Discard its results if there are enough strong
  matches. Other queries keep the current sequential fallback.

**0.9 Digest dead code (R14).**
- Set `two_way: bool` on each suggested person, using `two_way.two_way_match(kinds_of(requester),
  candidate)`, so `digest.py:148` works. This is the stop-gap; Phase 2 replaces it.

**0.10 Golden set covers what memory sends (R17, D7).**
- `cards-api/tests/fixtures/search_golden.json`:
  - add a Chandan-like card and the queries "chandan", "Chandan Kumar" and "chandan from zynd";
  - add cards with a city-only location ("Gurgaon");
  - add a no-match role, and the exact params memory sent for the investor query (topics as `topics`).
- New memory test `tests/test_people_golden.py` runs `parse_target_heuristic` → `cards_search_params`
  → the Cards scorer (imported, or a recorded HTTP fixture), so the mapping is tested end to end.
- Baseline today's precision@5 and recall@5 first, and record it here.

**Phase 0 is done when:**
- Live in dev, "chandan" / "Chandan Kumar" / "chandan from zynd" → `chandan-kumar-2en8` is first.
- The investor query: no Grievance, Relations or Communications titles; at least 90% of LinkedIn
  results have a URL and a location; Cards results are investors, or are marked `relaxed`.
- Golden set precision@5 is no lower than the recorded baseline, and the name cases pass.

#### Phase 0 as built (2026-10-26)

All of 0.1–0.10 is in. What differs from the text above, and what is still open:

- **Baseline (0.10).** Golden set before any change: 52 queries, precision@k and recall@5 both **0.754**.
  The 52 existing queries still send topics as `skills` (the bug's shape) and are left as the baseline.
  After adding 2 cards and 9 queries (names, Gurgaon, relaxation, memory's real parameters): 61 queries,
  **0.790**. The CI floor in `search_golden.json` was 0.0 and is now 0.75. Tests: memory 693 → 774 passing,
  cards-api 680 → 694 passing; the only failures are the 2 known `test_x_bot.py` ones.
- **End-to-end test (0.10).** `services/memory/tests/fixtures/people_golden.json` is shared: memory's
  `test_people_golden.py` checks the parameters it sends, cards-api's `test_search_golden.py` runs those exact
  parameters through the scorer. With the old parameters (topics as `skills`) both "chandan" and the investor
  query return nothing; with the new ones they find `chandan_kumar` and `inv_seed_ai_in`.
- **No flag.** Phase 0 ships enabled; there is no `FEATURE_PEOPLE_SEARCH_V2` and no new env var (AGENTS.md §9).
  The Zynd floors and the 7-day QuickEnrich cache TTL are constants in code. **Deploy cards-api first**: it
  ignores `topics` and `relax` until it has them, so memory first would drop the topics. Rollback is a revert.
- **Name lookup (0.3).** If nobody is found by the name, the search continues as a normal target search with a
  `note`, so a word wrongly read as a name still gets results. The QuickEnrich name search reads two pages
  of 10 people at the company. `/v1/agents/lookup` is rate-limited in-process (30 per minute per client IP;
  per worker, which stops a script but is not a global limit).
- **Relaxing (0.2).** Group search takes `topics` and `relax` too (memory sends both). The final step (drop the
  role) can fill the list with loose matches when memory asks for its pool of `2 × k`; they are marked
  `relaxed` and rank last, and Phase 1's single scorer is where they should be cut.
- **Investor title exclusions (0.6)** also list Engineer, Software and Teacher, because `Principal` is in the
  include list. Short words like "AI" are kept in `bio_li` phrases (the plan's "drop one- or two-letter words"
  rule would have dropped the signal).
- **Still open, needs a human or live access:**
  - Q1 and Q2 are **not answered**: they need three manual QuickEnrich calls and one raw record, and this
    session had no QuickEnrich credentials. The code assumes OR and substring matching and a scheme-less
    LinkedIn URL; `_linkedin_with_scheme` and the exclude lists are harmless if wrong, but confirm.
  - Turning on `FEATURE_FACT_MATCHING` in prod (§8). The Zynd floors (`ZYND_MIN_SCORE_FACT` 0.35,
    `ZYND_MIN_SCORE_AVG` 0.45, constants in `people_search.py`) are starting values to tune on dev.
  - The Phase 0 "done when" checks are unit-tested but not yet checked against live dev.

### Phase 1: One calibrated scorer (~1–2 weeks)

**1.1 Restructure the Cards score (R5, D3).** Replace the sum in `search.py:178-264` with
`score = relevance × fit × quality`:
- `relevance = 0.6 × sem + 0.4 × lex`
  - `sem = clamp((cosine − 0.20) / 0.40, 0, 1)`; take the real cosine range for text-embedding-3-small
    from a prod sample.
  - `lex` = the best of query-term coverage over the card text and the best approved-fact cover (today's
    `best_cover`).
- `fit` = the product over requested constraints only:

  | Constraint | Met | Partly | Missing |
  |---|---|---|---|
  | role | 1.0 (headline) | 0.9 (elsewhere on the card) | 0.5 |
  | location | 1.0 | 0.85 (same country) | 0.6 |
  | skill | 1.0 | | 0.7 |

  A location inferred from the free text counts as requested.
- `quality = 0.85 + 0.05 × claimed + 0.05 × verified + 0.05 × fresh fact`, then × 1.15 for a two-way
  match and × 0.7 for "less like this".
- Keep `match_reasons`; floor at 0.25 after calibration. Write the weights and the reasoning in the
  module docstring.
- Tune against the golden set. A weight change ships only if precision@5 and recall@5 don't drop.

**1.2 One re-rank in memory (R6, R10, D3).** In `people_results.py`, every person gets features:
- `role_fit`, `topic_fit`, `location_fit`, computed from headline, skills, why and location the same
  way for every source;
- `source_relevance`: rank-percentile within its source × a source prior (Cards 1.0, Zynd 0.9,
  LinkedIn 0.8);
- `two_way`, `verified`, `claimed`.

`score = source_relevance × fit(role, topic, location) × quality`, using the same fit table as 1.1.
Remove `ZYND_BONUS`; being found by two sources raises `source_relevance` to the better of the two
plus 0.05. A LinkedIn person who fits the target can now beat a weak Card.

**1.3 "Strong match" by meaning (R6, D3).** `strong_count` counts people with `role_fit ≥ 0.9` (when
a role was asked) and (`topic_fit > 0` or `location_fit ≥ 0.85`). It drives the QuickEnrich fallback.
`STRONG_MATCH = 0.5` goes away.

**1.4 Specific reasons (D4).** Build `why` from the features, at most 3, most specific first:
- "Investor (headline)"
- "Backs developer tools (approved fact, this week)"
- "Bengaluru, India"
- "Wants to meet founders like you"
- "Not in India (closest match)"

No generic reasons.

**1.5 Labels on quality.** Each person gets `match_quality`:
- `exact`: every requested constraint met, plus a topic or name;
- `close`: one constraint loosened;
- `loose`: the rest.

The response `note` explains any loosening. Update the `find_people` docstring so assistants say
"closest matches" when nothing is exact.

**1.6 Speed.** Filtered searches load every published card and compute cosine in Python
(`search.py:145-150, 184-186`). Move the filter step into SQL in a new RPC (role and location `ILIKE`
on the indexed card JSON, then vector top-N over the survivors), or cache parsed cards in-process with
a 60s TTL. Measure p95 before and after on prod-size data; the target is under 800ms for Cards search.

**Phase 1 is done when** golden precision@5 is ≥ 10 points above the Phase 0 baseline, no
non-investor scores above any investor on the investor golden queries, and p95 hasn't regressed.

#### Phase 1 as built (2026-10-27)

- **1.1 Cards scorer.** `relevance × fit × quality` in `cards-api/services/search.py` (constants and reasoning
  in its comment block). Fit is judged against what the caller asked for, so a relaxed result that missed a
  dropped requirement scores lower. Words answered by a met constraint count as found, and a met constraint gives
  relevance a floor (`MET_RELEVANCE` 0.4). The 0.25 floor applies to relevance×quality, except a result that is not
  the asked role must clear it with the role penalty counted. `verified` is applied in memory's re-rank, not Cards.
  `SEM_FLOOR/SEM_SPAN` are the plan's 0.20/0.40, **not yet fitted** on real cosines (run `scripts/bench_search.py`).
- **Golden set.** 29 old-shape queries moved from `skills` to `topics` + `relax` (what memory sends). Precision@5 and
  recall@5: 0.790 (Phase 0) → 0.993; CI floor 0.95. The harness rescales the hash embedder's cosines
  (`HASH_SEM_*`). New: investor-ordering gate, monotonicity, filter-superset tests.
- **Saved-search alerts** use `STRONG_MATCH = 0.6` on the new scale (chosen from the golden distribution; check on real data).
- **1.2–1.5 Memory re-rank.** `people_results`: Zynd scores are the rescaled cosine × 0.9, LinkedIn 0.8 × provider
  order; both × the fit factor (`features`/`rescore`) for role, topics and place. `ZYND_BONUS` and `STRONG_MATCH` are
  gone: two sources add 0.05; `is_strong` = a Card that passed every filter with score ≥ 0.5, or anyone meeting the
  role and a topic or the place. Every person gets `match_quality`; the response gets a `note` when none is exact.
  `why` (1.4) is rebuilt by `specific_why`: at most 3 reasons, role, then the approved fact or topic, then what was loosened, then the place; generic reasons are dropped.
- **1.6 Speed.** Migration `cards/0030_filter_cards.sql` (`cards.filter_cards`, a superset pre-filter; cards-api
  applies the exact rules and falls back to the full scan if the function is missing). **Not applied to aafo: a human
  must apply it** (README steps), then compare p95 with `scripts/bench_search.py`.
- **Deploy order:** apply 0030 (optional, falls back), cards-api, then memory.

### Phase 2: Suggestions on the same pipeline (~1–2 weeks; schema needs a human)

**2.1 Targets from the owner's card (R11, R12, D5).** A new `cards-api/services/suggest_targets.py`
builds up to 3 targets:
- **who to look for:** `connect_with` labels, approved `is_seeking` facts (`two_way._SEEKING_KINDS`),
  and `set_looking_for` text;
- **what about:** `working_on`, `love_talking_about`, top skills;
- **where:** the card's location, used as a soft preference, never a filter.

Mapping: the existing `_TITLE_FOR` / `_KEYWORD_FOR` tables first. Free-text values that match no label
are matched to the nearest label by embedding (cards already store embeddings), with no hard vocabulary
cut-off. Example: wants Investors + working on "Building with AI" → target "investor who backs AI",
role investor, topics [AI].

**2.2 Run each target through Cards search** with `as_handle = owner`, so the two-way boost applies,
and `relax=True` without dropping the role. Merge per person and keep the best target as that person's
reason ("Investor · backs AI · wants to meet founders like you").

**2.3 Who can be suggested (R13).** Leave out:
- unclaimed cards (they can't accept);
- the owner themselves;
- connected people, and pending requests in either direction (`connections`);
- blocked or reported people;
- people hidden in `match_prefs`;
- anyone shown in the last 3 digests, unless their score went up by more than 0.15.

Spread across kinds and companies: at most 2 per target, at most 1 per company.

**2.4 Precompute nightly (R13).** New `cards` tables, via a `packages/db` migration (expand-only;
**human OK**; review per `packages/db/OWNERS.md`):

```
cards.card_suggestions(
  card_id uuid, candidate_card_id uuid, target text, score real, why jsonb,
  two_way boolean, computed_at timestamptz, primary key (card_id, candidate_card_id))
cards.card_suggestion_impressions(
  card_id uuid, candidate_card_id uuid, surface text,      -- digest | owner_home | mcp
  shown_at timestamptz, action text null)                   -- null | viewed | connect | hide | not_relevant
```

A nightly job (`POST /internal/suggestions/refresh`, `CRON_SECRET`, like the existing internal
routes) writes the top 20 per card. The cost is one search per target per card, not N². Owner home
and the digest read the table, and compute live (Phase 0 code) when it's empty.

**2.5 Outside people.** Only when there are fewer than 2 Zynd suggestions. Use the Phase 0.6 request
builder (per-role include and exclude), up to 2 per target (remove the `break` at
`suggested_people.py:232`). Label "Not on Zynd yet", with an `invite_ref` when A2
(`FEATURE_A2_INVITE_TO_CLAIM`) is on.

**2.6 Feedback.** "Not relevant" and "Hide" on owner home and in digest links (signed links, like
unsubscribe). They write to the existing match preferences (`hide_person`, `less_like_this`; Part B
A8, `FEATURE_NETWORK_CONTROLS`) and to `card_suggestion_impressions.action`.

**2.7 Digest (R14).** Two-way people first (now real), one reason line per person, and only people not
shown in the previous 2 digests. Remove the Phase 0.9 stop-gap.

**2.8 Persona suggestions (R15).** Persona is paused, so freeze it and make one fix: drop
`has_email` and `has_phone` from the score (`people_suggestions.py:431-435`). Confirm with the persona
owner whether `/dashboard/people` is still in use. If it is, switch it to the Phase 3.1 endpoint later;
if not, leave it.

**Phase 2 is done when** no suggestion is already connected, pending or hidden; at least 60% of
suggestions change week to week for an unchanged card; and at least 1 two-way suggestion appears when
the corpus has one. Check with a script over a prod snapshot, read-only.

#### Phase 2 as built (2026-10-26)

What reading the code changed in the text above:

- **The digest is daily**, not weekly (`digest.run_digest`, 07:00 local). "Not shown in the last 3 digests"
  became a **14-day cooldown on digest impressions** (`COOLDOWN_DAYS`), unless the person's score rose by more
  than `RESHOW_GAIN` 0.15. Owner home is not cooled down (it would change on every page load).
- **Owner home had no suggestions.** It now has a "People to meet" section (`apps/cards-web/.../home/people-to-meet.tsx`)
  with View, Not relevant and Hide; `GET /cards/mine/status` returns `suggestions: {people, outside}`.
- **No embedding label mapping (2.1).** A free-text `connect_with` value is matched to a kind by its words
  (`two_way.kind_from_text`: "angel investors" → Investors); one that names no kind is searched as written (≤ 4
  words), and Cards scores it semantically anyway. Same effect, no label-embedding table, no extra OpenAI calls.
- **`set_looking_for` free text is private** (memory `intends_to`), so Cards can't read it. Targets use the public
  `is_seeking` fact and the card's **active beacon**, which is its own first target.
- **0.9 was already in place**; the digest's `_mark_people` now only adds `verified` (two-way comes with the suggestion).
- **Outside people lost the per-role excludes**: memory's `query_from_filters` set titles but no role. It now
  infers the role from the title, so `{"titles": ["Investor"]}` gets the investor include/exclude row.
- **Invites (2.5)**: a browser can't create an A2 invite (only Memory's service token can), so outside people carry
  `invitable` and owner home says "ask your assistant to invite them".
- **"developer tools" is not a developer.** The suggestions golden set showed "Seed investor backing AI developer
  tools" passing as an engineer (and as the Engineers kind in two-way). `search_text.role_tokens` drops
  "developer/dev tool(s)/tooling" before role checks in search and in `two_way.kinds_of`. The search golden set
  is unchanged (0.993).

How it works:

- `services/suggest_targets.py`: up to 3 targets per card (beacon, `is_seeking` kinds, `connect_with` kinds, free
  text; or "works on X" when nobody is named), topics from `working_on` / `love_talking_about` / top skills.
  `KIND_SEARCH` maps each kind to a search role (Customers has none and is skipped).
- `services/suggestions.py`: each target runs through `search_agents(relax=True, keep_role=True, searcher=owner)`
  (`keep_role` is new: never drop the role). Best result per person, `NEAR_CITY` ×1.05 / `NEAR_COUNTRY` ×1.03,
  two-way first, `why` ≤ 3 specific reasons. Exclusions: self, unclaimed, any `connections` row in any status,
  open reports, `hide_person`, and impressions marked hide / not relevant; `less_like_this` ranks down.
  Diversity: ≤ 2 per target, ≤ 1 per company (`work_experience[0].company`, now on each search result with
  `avatar_url` and the `two_way` kinds).
- Stored: `cards.card_suggestions` (top 20 per claimed card, `POST /internal/suggestions/refresh`, cron job
  on the box at 23:30 UTC, `infra/single-box/crontab`) and `cards.card_suggestion_impressions` (digest, owner home, api;
  actions viewed / connect / hide / not_relevant). A list older than 36 h, or a missing table, means a live
  compute and nothing recorded, so **cards-api can deploy before `cards/0031` is applied**.
- Feedback: owner home `POST /cards/mine/suggestions/{handle}/feedback`; digest links
  `/cards/suggestions/feedback/{unsubscribe_token}/{handle}/{action}` (GET asks, POST acts, like unsubscribe; the
  owner's existing token, no new secret). Mirrored into match preferences when `FEATURE_NETWORK_CONTROLS` is on.
  A connection request to a suggested person marks the impression `connect`.
- Persona (2.8): `has_email` / `has_phone` no longer add to the score. Q7 is still open.
- Tests: cards-api 711 → 758 passing (new `test_suggest_targets`, `test_suggestions`, `test_suggestions_golden` with
  5 golden owners over the search corpus), memory 777 → 778, persona 366 → 367, `packages/db` SQL tests on a local
  Postgres (migration count 32). Only the 2 known `test_x_bot.py` failures remain.
- Check script: `services/cards-api/scripts/check_suggestions.py` (read-only; V11 below).
- **Deploy order:** cards-api, memory, cards-web. 0031 is applied (an earlier note here said so before it was; a maintainer's `db:migrate` run applied it, and the next dry run showed `pending: none`).
- Known cost: until the first nightly refresh has run, each owner-home refresh (every 60 s while open) computes
  live, up to 3 searches.

### Phase 3: One pipeline everywhere, and measurement (~1 week, then ongoing)

> **Rewritten 2026-10-26 after reading the code; built the same day, see "Phase 3 as built" below for where it
> differs.** Decisions taken with the owner:
> - **Persona is out of scope.** It is a discarded project, so 3.3 is dropped and the plan touches only
>   Cards: cards-api, cards-web, and memory, which hosts `find_people` and the public Cards MCP.
> - cards-web `/search` shows a **label, not a percentage** (3.4).
> - Connects are linked to the search they came from because **memory remembers each user's last search**
>   for 24 hours (3.5).
>
> What reading the code changed in the original text:
> - **No `/v1/service/people-search`.** Its only caller outside memory would have been persona.
> - `outside-people` keeps its structured body and shares the pipeline's steps, rather than wrapping a
>   text endpoint (turning filters into text and parsing them back would lose detail).
> - A fifth entry point exists: the GPT Action route `GET /me/find-people`. It stays as it is (3.1).
> - cards-web never shows `relaxed`: `/search` is strict and `/directory` calls `/ask` without loosening.
>
> Line numbers are as of `8c7e051`.

**3.0 `find` works without a user (memory; no behaviour change for owners).**
`people_search.find` (`people_search.py:166`) assumes a signed-in user: it reads their match controls
(`_preferences`), their own handle (`_own_handle`) and signs invite refs (`with_invites`). The public MCP
and `outside-people` have no user.
- Add a `Searcher` dataclass in `people_search.py`: `uid: str | None`, `own_handle`, `prefs`,
  `include_unclaimed: bool`, `invites: bool`. Build it once with `searcher_for(pool, uid)` (one
  `cards_for_users` call, which also removes the second `_own_handle` call `find` makes today), or
  `ANONYMOUS`.
- With no user:
  - the Zynd source is never searched (it needs a uid and the caller is anonymous);
  - there are no preferences and no invites (`next_action` stays `view_profile`/`connect`);
  - QuickEnrich runs only when the caller names it (`outside-people`), never as the fallback.
- `search_cards` and `lookup_cards` (`people_discovery.py:182, 207`) take `include_unclaimed` instead of
  always sending `"true"`. Owners keep `true`; the public MCP passes the caller's choice.
- Split the body of `find` into `_retrieve` (the source calls), `_rank` (rescore, merge, preferences,
  floor, own-card filter), `_fallback_quickenrich` and `_finish` (why, `match_quality`, note, invites), so
  3.1 and 3.2 call the same steps instead of copying them.
- Tests: `test_people_search.py`, `test_people_finding.py` and `test_people_rerank.py` pass unchanged. New:
  an anonymous search never calls Zynd, preferences or QuickEnrich; `include_unclaimed=False` reaches
  Cards' params.

**3.1 `outside-people` uses the pipeline (R16, D6).**
- `POST /v1/service/outside-people` (`memory/app/main.py:368`) keeps its request body
  (`titles`, `keywords`, `location`, `limit`), so Cards does not change.
- Inside: `query_from_filters` → `search_quickenrich` → `people_results.person_from_external` →
  `rescore` → `specific_why` → `label_quality`, with no user. These are the same calls `find` makes for
  LinkedIn results.
- Each person gains `location`, `why`, `score` and `match_quality`, and the list is ordered by fit instead
  of by the provider's order. Cards' `_shape_outside` (`suggested_people.py:162`) ignores extra keys
  today; it starts keeping `location` and `why`, so the digest and owner home can show
  "Investor · Bengaluru".
- `GET /me/find-people` (the ChatGPT GPT Action, `main.py:623`, schema in `action_schema.py:118`) **stays
  as it is**:
  - it returns Zynd members by `user_id` for `/me/connect`, a different way to connect from Cards;
  - routing it through the pipeline would break the GPT's connect step;
  - it is recorded here as the one known exception to D6.
- Tests: `test_outside_people.py` covers the new order (an investor title above a "Grievance" one, a
  matching location first) and the new fields, and checks that the 401 path is unchanged. cards-api:
  `_shape_outside` keeps `location` and `why`.

**3.2 Public Cards MCP on the pipeline (R16, Q4).**
- `cards_public_mcp.search_people_impl` (`cards_public_mcp.py:210`) stops calling `/ask` and
  `/v1/agents/search` directly. It calls the 3.0 steps in-process with `Searcher=ANONYMOUS`,
  `wanted={"cards"}` and the caller's `include_unclaimed`.
- Name lookup, grounding, loosening, the re-rank and `why` all apply. A name query with no match falls
  back to a target search with a `note`, as for owners.
- The tool's explicit arguments:
  - `role`, `location` and `skills` are strict. They override what parsing found and go into the
    `TargetQuery` as the role, the location and `required_skills`.
  - `industry`, `availability` and `experience_min` have no `TargetQuery` field. `cards_search_params`
    gets an `extra: dict` passed to Cards unchanged.
- **No QuickEnrich, ever** (Q4: cost and scraping). No Zynd source.
- The response keeps every current key: `query`, `include_unclaimed`, `results`, `numberOfItems`, and
  each hit's `match_score`, `match_reasons`, `claimed`, `fresh_as_of`, `url`, `cite_as`. It adds
  `intent`, `note`, and per hit `why`, `match_quality` and `relaxed`. `match_reasons` is filled from `why`
  so older clients still get text. `_strip_contact` still runs on unclaimed hits.
- The rate limit (`RateLimitMiddleware`) and `_emit_agent_fetch` stay. `/v1/agents/lookup` keeps its own
  per-IP limit.
- `_INSTRUCTIONS` and the tool docstring: "To find one specific person, pass their name or @handle";
  "when `note` says nothing matched exactly, call them the closest matches".
- Tests: update `test_cards_public_mcp.py`. Its current `/ask` and `/v1/agents/search` mocks become mocks
  of `people_discovery`. Cases: a name ("chandan" → lookup first); an explicit `location` is strict;
  `include_unclaimed` defaults to false; unclaimed hits have no contact keys; no QuickEnrich call even when
  results are few; the old keys are still present.

**3.3 Persona: dropped.** Persona is a discarded project (decision 2026-10-26). `discover_people`,
`search_zynd_cards` and persona's QuickEnrich client are left untouched. Q7 is closed with it.

**3.4 cards-web: scores as labels.**
- `/search` (`apps/cards-web/src/app/(site)/search/page.tsx:187-191`) shows `match_score` as a
  percentage, but the Phase 1 score is calibrated, not a probability. Replace it with a label:
  - **Strong match** at ≥ 0.6, the same `STRONG_MATCH` as saved-search alerts;
  - **Good match** at ≥ 0.4;
  - nothing below that.
  The thresholds are constants in one helper in `src/lib/cards.ts`, next to `formatMatchReason`.
- `/search` stays strict (`relax=False`): UI filters are explicit, so `relaxed` never appears there.
  `/directory` (via `/ask`) **does** show a score, a percentage ring: it gets the same label (corrected while
  building; the plan first said it needed no change).
- Profile links from `/search` and `/directory` carry `?sid=<search_id>&r=<rank>` for 3.5. `ProfileView`
  (`src/components/ProfileView.tsx:20`) adds them to its `view` event's meta, and the URL is cleaned
  with `history.replaceState` so a shared link carries no search id.
- Check: `npm run lint && npx tsc --noEmit && npm run build`; V8 on dev.

**3.5 Measurement (R17, D7).**

*Offline:*
- Grow `search_golden.json` from 61 to about 80 queries:
  - more names, including two people with the same first name and a handle;
  - city vs country in both directions;
  - a role that exists only after loosening;
  - "developer tools" vs developer;
  - each new query labelled over the whole corpus, as the `_about` says.
- Grow `people_golden.json` from 8 cases to about 15. Add a memory-side fixture of raw QuickEnrich records
  (Grievance, N/A fields, a URL with no scheme, a city-only location) with the expected order after
  `rescore`, for the new `test_people_rerank` case.
- Grow `suggestions_golden.json` from 5 owners to about 10: a free-text-only card, a card with nothing in
  `connect_with`, and a card whose two-way match is the only good one.
- **CI gate.** Each golden file records `baseline` (the metric when it was last changed) next to its
  floor. The test fails below `baseline − 0.05`, the plan's "drop of more than 5 points". A change that
  raises the metric updates `baseline` in the same commit. CI already runs both golden tests (`ci.yml`
  python matrix), so no workflow change is needed.

*Online:*
- **Search ids.**
  - `GET /v1/agents/search` and `/v1/agents/lookup` accept an optional `search_id` (a UUID; anything
    else is ignored) and make one when absent.
  - They return it in the response and record it in the `search` event's meta with
    `via: web | memory | mcp`. The `via` value comes from a small allow-list parameter memory sends;
    unknown or absent means web.
  - Memory makes one `search_id` per `find` call, sends it to every Cards call in that search, and
    returns it in `find_people`'s result.
- **New server event `search_result_action`**, added to `SERVER_EVENTS` in
  `cards-api/services/events.py:42` so the unauthenticated `POST /events` can't forge it.
  - Meta: `{search_id, rank, source: card | zynd | linkedin, action: connect | invite, connection_id? | invite_id?}`
    (the names memory already uses for a person's sources).
  - No query text and no user id. `connection_id` lets acceptance be joined from `cards.connections`.
- **connect.**
  - After each owner search, memory stores in Redis, for 24 hours under `people_search:last:<uid>`,
    `{search_id, handles: {handle: [rank, source]}}`. It holds handles only, never the query, and is
    overwritten by the next search.
  - `cards_network.request_connection` looks the target handle up and, when found, adds
    `from_search: {search_id, rank, source}` to the `/connections` body.
  - cards-api's `ConnectionCreate` (`api/network.py`, `extra="forbid"`) gains the optional field. After
    the connection row is created, it emits the event with the new `connection_id`, next to
    `suggestions.mark_connected` (`services/network.py:195`).
- **invite.** `invite_to_claim` does the same lookup by `linkedin_url`. cards-api's `/invites` body
  gains the same optional field and emits `action: invite`.
- **view.** The existing client `view` event carries `meta.search_id` and `meta.rank` from 3.4's link
  parameters. Views were already client-sent, so this adds no new trust.
- **Funnel.** `docs/cards/s04-funnel.sql` gets:
  - the share of searches with no results, by `via`;
  - connects per search;
  - acceptance by source (`search_result_action` joined to `cards.connections` on `connection_id`);
  - views per search;
  - the suggestion connect rate from `card_suggestion_impressions` (shown → connect, by surface).
  Each query is checked against a local Postgres before it goes in.

*Memory log:*
- `find` logs one line per search on `zynd.find_people`:
  `intent, sources searched, results per source, kept, strong, quickenrich_called, warnings, ms, search_id`.
- No query text and no name. The public MCP logs the same line with `anonymous=true`.

**Deploy order:**
1. cards-api: `search_id`, `via`, the new event, and `from_search` on `/connections` and `/invites`. It
   must go first, because memory sending `from_search` to an old cards-api gets a 422 from
   `extra="forbid"`.
2. memory.
3. cards-web.

No migration: `card_events.meta` is jsonb. Rollback is a revert per service, in the reverse order.

**Phase 3 is done when:**
- The public MCP returns `chandan-kumar-2en8` first for "chandan" and never calls QuickEnrich.
- `outside-people` results carry a location and are ordered by fit.
- The three golden sets are at 80, 16 and 10 cases, with the baseline − 5 gate (search set).
- A connection request made from a `find_people` result on dev produces a `search_result_action` row with
  its `connection_id`.
- The new funnel queries run.

#### Phase 3 as built (2026-10-26)

Commits `437551d`, `d631bb0`, `8232270`, `02f8782`, `9de6f1e`, `21b0d93`, `d0d9a10`, `a853e44` on
`feature/people-search`, not pushed (§11 E1). Tests: memory 778 → 832 passing, cards-api 758 → 770 (only the 2
known `test_x_bot.py` failures), cards-web lint 0 errors / `tsc` / `next build` clean, `packages/db` funnel SQL test
against a throwaway local Postgres. Persona was not touched.

What differs from the text above:

- **3.0** `people_search.search(pool, Searcher, target, ...)` is the one search; `find` is the owner wrapper. A
  `Searcher` with no user has no Zynd source, no preferences, no invites, **no model call** (heuristic parsing only: an
  anonymous caller must not cost a model call per request) and gets LinkedIn only when it names it. The *early*
  LinkedIn start is gated the same way (the first version of this started a paid lookup for an anonymous search and
  then cancelled it).
- **3.1** `outside-people` returns each person ordered by fit with `location`, `why`, `score` and `match_quality`, and
  **drops** wrong-role titles (the provider's exclude matching is unconfirmed, Q1). Cards keeps `location` and `why`;
  the digest and owner home show the location.
- **Role fit for LinkedIn people** is read from the *title* with the request's include/exclude words, not the role noun
  in the whole headline. Before, a LinkedIn "Venture Partner" (retrieved as an investor) scored as not-an-investor
  and "Sales Manager at Investor Relations Inc" scored as one. The reason says "(title)" when the headline does not
  name the role.
- **3.2** The public MCP runs `search` anonymously (`sources=cards`, `include_unclaimed` as asked). Explicit `role`,
  `location`, `skills` are **pinned**: the only ones sent, nothing relaxed, and the free text only contributes topics.
  Such a search is never read as a name. `industries`, `availability` and `fresh_as_of` come from the Card, so every key
  the tool returned is still there; it adds `intent`, `match_quality`, `relaxed`, `note`, `warnings`. A Cards outage is
  still an error, not an empty answer.
- **3.4** `/search` and the directory show "Strong match" / "Good match" (`matchLabel`, `STRONG_MATCH_SCORE` 0.6 and
  `GOOD_MATCH_SCORE` 0.4 in `src/lib/match-reason.ts`) and link profiles with `?sid=&r=`; `ProfileView` counts the view
  with them and removes them from the address.
- **3.5 online.**
  - cards-api: `search_id` and `via` (`web`, `memory`, `mcp`, `ask`) on `/v1/agents/search`, `/lookup` and `/ask`; `/ask`
    is now counted as a search (`via=ask` unless the caller says otherwise). `search_result_action` is a server event.
    `from_search` on `/network/connections` and `/network/invites` is honoured **only for the service token**.
  - memory: `search_trail` keeps the last search of each user for 24 h in Redis (`people_search:last:<uid>`: handles,
    ranks, sources; no query). `request_card_connection` and `invite_to_claim` send `from_search`; if Cards answers 422
    (deployed in the wrong order) the request is sent again without it. One log line per search on `zynd.find_people`
    (`search_id`, who, intent, sources, counts, strong, warnings, ms; no query text and no name).
  - `docs/cards/s04-funnel.sql` has five named queries (empty share by via, connects per search, acceptance by source,
    views per search, suggestion connect rate); `packages/db/test/cards-search-funnel-sql.test.ts` runs them against the
    real cards migrations and seeded events (skipped without `CARDS_TEST_DATABASE_URL`).
- **3.5 offline.** `search_golden` 61 → 80 queries (+2 cards), `people_golden` 8 → 16, `suggestions_golden` 5 → 10 owners
  (+ `kinds_in_first`), a raw-QuickEnrich fixture. The fixed 0.95 floor is replaced by `baseline` and `max_drop`: precision@k
  and recall@5 may not fall more than 5 points below the recorded baseline (0.9888 / 0.995, so the gates are 0.939 and 0.945:
  about a point looser than the old 0.95), and a rise of more than 0.01 must raise the baseline in the same commit.

Found while building and **fixed** (each has a test): a lone tool name ("Kubernetes", "Figma") was read as a person's name;
the same LinkedIn person spelled with and without `www.` counted twice in `outside-people`; a company of "N/A" showed as
"Investor at N/A"; the early LinkedIn start for anonymous callers (above).

Found and **not fixed** (each is a decision for a person):

- **A "who I want to meet" longer than 4 words is dropped** by the suggestions (`MAX_FREE_TEXT_WORDS`), so "a startup
  lawyer who knows fundraising" gets no suggestions. The golden owner uses a 4-word phrase.
- **"Former founder" satisfies the role "founder".** On "founders in the USA" an angel investor whose headline is "Angel
  investor and former founder" outranks a real founder (the one golden miss; its label is kept as written).
- A free-text suggestion has no role filter, so after the right person it can list a weak match (about 0.34).
- `GET /me/find-people` (the ChatGPT GPT Action) is still its own Zynd-only path (the one exception to D6, by design).
- The `SEM_FLOOR`/`SEM_SPAN` constants are still unfitted (V3): the gates above test the hashed stand-in embedder.

**Deploy order:** cards-api, then memory, then cards-web. No migration.

#### Deploy test (2026-10-26)

Run read-only against dev and prod after deploy: cards-api, memory (anonymous MCP and a signed-in `find_people`) and
cards-web are all on the new code on both. What it found:

- **Relaxed searches timed out on prod** (3 of 3: `cards_unavailable`, LinkedIn-only answers; 5 s on dev, 6-12 s on prod,
  against memory's 8 s). Fixed in `e7c91df`: a timed-out relaxed search is retried once without loosening and flagged
  `cards_slow`. The relaxed search itself is still slow; Cards now logs where a slow search spent its time.
- **Contradictory reasons on closest matches**: "Investor (on their profile)" next to "Not a investor", "Role match" next
  to it, and the loosening reason missing for anyone with several approved facts. Fixed: the loosening reason no longer counts
  as evidence of the role, reasons are kept whole (8) until the best three are chosen, "Role match" is never shown, "an investor".
- **The company question for callers that cannot use it**: the public tool and a Cards-only search no longer say
  `name_needs_company`.
- Not fixed: LinkedIn results for the investor query are flat-scored and include consulting and healthcare "partners";
  the provider's places are sometimes doubled ("Bengaluru, India, India") or wrong ("Palo Alto, India"); the corpus has no
  investors. Not testable from outside: V14 and V15 (database), the browser behaviour of V16, V11/V12/E3 (secrets).

---

## 7. Testing

Run each service's tests before and after, against the AGENTS.md §5 baselines.

| Phase | memory | cards-api | other |
|---|---|---|---|
| 0 | `test_people_discovery`, `test_people_query` (intent, grounding, QE body), `test_people_search` (floor, fallback), new `test_people_golden` | `test_search*.py` (topics soft, loosening, `/lookup`), golden set + new cases | — |
| 1 | `test_people_results` (features, re-rank, strong_count) | golden set; score monotonicity tests (meeting a constraint never lowers the score) | p95 timing script |
| 2 | — | `suggest_targets`, exclusions, impressions, digest | `packages/db` tests (migration count, as in `cf0e6a2`) |
| 3 | anonymous `find`, `test_outside_people` (order, fields), `test_cards_public_mcp` (pipeline, no QE), last-search Redis + `from_search` | `search_id`/`via`, `search_result_action` emit on `/connections` and `/invites`, `_shape_outside`, golden sets at ~80/~10 with the baseline − 5 gate | cards-web lint/tsc/build; funnel SQL on a local Postgres |

## 8. Rollout and flags

| Flag | Service | Covers | Dev | Prod |
|---|---|---|---|---|
| `FEATURE_FACT_MATCHING` | memory | existing | on | **human OK** (after `FEATURE_FACT_FAMILIES`) |

> **Superseded by AGENTS.md §9:** this plan first proposed `FEATURE_SCORER_V2` and `FEATURE_SUGGESTIONS_V2`.
> There are no new flags: Phases 1 and 2 ship enabled, gated by tests and the golden set, and Phase 2 by the
> human-applied migration. If a risky phase needs a staged rollout, a human decides how.

- **Deploy order:** Cards first, then memory. Cards ignores unknown parameters, so if memory deploys
  first, `topics` is dropped silently and searches get *worse* (no topics at all).
- **Dev shares prod's databases** (`infra/single-box/README.md`). Phase 2's tables are applied to
  aafo by a person, never by a deploy.
- **Before each prod flip:** run the golden set, plus a fixed list of 20 real queries against dev, and
  compare with prod by hand. Include "chandan from zynd", the investor query, and "people like me" for
  three test accounts.

## 9. Risks and open questions

| # | Item | Plan |
|---|---|---|
| Q1 | QuickEnrich `include` matching (OR/AND; substring/whole word) is unknown | **Answered 2026-10-26** (direct calls, see `ZYND_PEOPLE_SEARCH_QUALITY_PLAN.md` §2): `include` is OR; matching is by whole word or phrase, case-insensitive, not substring ("Invest" finds "Invest India", not "Investor"; `exclude` "Relations" misses "Relation"); `bio_li` matches phrases ("seed stage"); `locality` matches a country word |
| Q2 | Raw `employee_linkedin` format (scheme or not) | **Answered 2026-10-26**: `https://www.linkedin.com/in/...`, or the string `"N/A"`. Also: `locality` is the person's place with the country, `city` an office address, `country_code` the company's country |
| Q3 | Name lookup makes it easier to page through people | Public Card data only (same as `/ask`), no contact fields, rate-limit `/v1/agents/lookup` per IP and per user, unclaimed only when `include_unclaimed` |
| Q4 | Anonymous public MCP triggering QuickEnrich | Not allowed (3.2) |
| Q5 | Score weights tuned on 41 synthetic cards may not fit prod | Calibrate `sem` on a prod sample; check the 20 real queries before each flip |
| Q6 | `FEATURE_FACT_MATCHING` depends on fact families (memory quality plan §16) | Check Part A rollout state before turning it on |
| Q7 | Is persona's `/dashboard/people` still used? | Closed 2026-10-26: persona is a discarded project; nothing more is done there |
| Q8 | A geo table copied into Cards can drift from memory's | Move both to `packages/contracts` when it exists |
| Q9 | Two-way and suggestions depend on cards filling in `connect_with` | Phase 2.1's embedding mapping covers free text; nudging owners to fill it in is a separate cards-web task |

## 10. Order at a glance

| Step | What | Effort | Human gate |
|---|---|---|---|
| 1 | 0.10 golden baseline, then 0.1 soft topics + 0.3 name lookup | 2 days | — |
| 2 | 0.2 loosening + geo, 0.4 grounding, 0.5 floor | 1 day | prod flag |
| 3 | 0.6–0.8 QuickEnrich request, results, cache | 1–2 days | — |
| 4 | 0.9 digest stop-gap | ½ day | — |
| 5 | Phase 1 scorer + re-rank + reasons | 1–2 weeks | prod flags |
| 6 | Phase 2 suggestions | 1–2 weeks | migration, prod flag |
| 7 | Phase 3: anonymous `find`, `outside-people` and public MCP on the pipeline, score labels, measurement | ~1 week | — |
| — | `FEATURE_FACT_MATCHING` in prod | flip only | yes |

---

## 11. Verification still to do (needs prod data or a human)

Code for Phases 0–2 is finished and unit-tested. These checks need live data or credentials a
coding session does not have. Run them in this order, and record each result here.

| # | Check | How | Pass when | Result |
|---|---|---|---|---|
| V1 | Migration 0030 applied | `db:migrate --project cards --yes` | applied 2026-10-27, `cards.filter_cards` exists | ✅ done |
| V2 | Speed before and after | `cd services/cards-api && python scripts/bench_search.py` (read-only; needs SUPABASE_* and an OpenAI key). Run on the old deploy, then the new | p95 of filtered searches under 800 ms, and not worse than before | **measured from outside, not met**: a basic search is about 2.6-2.9 s on dev (3-5 s prod), a relaxed one about 5 s (6-12 s prod), against a 0.6 s round trip. Server-side profiling still open; Cards now logs a `slow search` line (over 3 s) with each pass's rows and time |
| V3 | Fit the semantic constants | The same script prints the top and 50th-ranked scores. Take the real cosine of related and unrelated query/card pairs, and set `SEM_FLOOR`/`SEM_SPAN` in `cards-api/services/search.py` and `ZYND_SEM_*` in `people_results.py` so related text is about 1.0 and unrelated about 0. Re-run the golden set | golden precision@5 and recall@5 still ≥ 0.95 | open |
| V4 | Saved-search alert threshold | Run `saved_searches._strong` read-only for every active saved search with the old (0.5, old scorer) and new (0.6, new scorer) rules, and compare how many alerts each would send. Adjust `STRONG_MATCH` in `saved_searches.py` until the volume is about the same and each alert is a person you would call a good match | alert count within ±20% of the old one, spot-checked by a person | open |
| V5 | The "done when" checks of Phase 0 against live dev | "chandan", "Chandan Kumar", "chandan from zynd" return `chandan-kumar-2en8` first; the investor query has no Grievance/Relations/Communications titles, at least 90% of LinkedIn results have a URL and a location | all hold | **partly verified 2026-10-26, dev and prod**: the three names return `chandan-kumar-2en8` first; no Grievance/Relations titles; but 4 of 5 LinkedIn results had a URL (80%, the bar is 90%) and the corpus has no investors, so the query only returns closest matches |
| V6 | The 20 real queries | Run a fixed list of 20 real queries on dev (include the Chandan and investor ones and "people like me" for three test accounts), compare with prod by hand, using the new `note`, `match_quality` and `why` | no result worse than prod; every `why` is specific | open |
| V7 | `FEATURE_FACT_MATCHING` in prod | Human decision (section 8), after `FEATURE_FACT_FAMILIES` is on | flipped after V5 and V6 | open |
| V8 | cards-web | Open `/search` and `/directory` on dev: scores display sensibly on the new scale, `relaxed` shows | looks right | open |
| V9 | QuickEnrich questions Q1 and Q2 | Three manual calls (OR/AND and substring/whole word for `include`) and one raw record (is the LinkedIn URL scheme-less?) | answers written into section 9 | ✅ done 2026-10-26 (Q1, Q2 above) |
| V10 | Migration 0031 applied | `db:migrate --project cards --yes` | applied by a maintainer (first run: `applied: 0030; pending: 0031`, then applied; second dry run: `applied: 0031; pending: none`); `cards.card_suggestions` and `cards.card_suggestion_impressions` exist | ✅ done (first refresh: see "Left for the end") |
| V11 | Phase 2 "done when" | `cd services/cards-api && python scripts/check_suggestions.py` (read-only; embeds each target) | 0 exclusion violations; digest rotation ≥ 60%; every card that could get a two-way suggestion gets one | open |
| V12 | Owner home and digest on dev | Open `/home` on dev: "People to meet" shows, Hide / Not relevant remove a person and they stay gone after reload; a digest preview (`?dry_run=true&handle=`) shows reasons and the feedback links | looks right | open |
| V13 | Public MCP on dev | `search_people("chandan")`, a name with a company, an explicit `location`, and a long free-text query on `/cards-public-mcp`; then the memory log | "chandan" first; `intent` is `name`; no LinkedIn call (log line says `who=anonymous` and `quickenrich=no`); the explicit location is strict | **verified 2026-10-26 on dev and prod** (anonymous): "chandan" first and read as a name, old keys kept plus `match_quality`, strict explicit filter, claimed-only default, "Kubernetes" a topic. The `who=anonymous quickenrich=no` log line needs a server read (the log now reaches the logs) |
| V14 | A connection from a search is recorded | On dev, `find_people`, then `request_card_connection` to a result; read `cards.card_events` | one `search_result_action` row with the `search_id`, `rank`, `source` and `connection_id`; `people_search:last:<uid>` exists in Redis with a 24 h TTL | open |
| V15 | The funnel queries on aafo | Run the five named queries in `docs/cards/s04-funnel.sql` (read-only) after a day of traffic | rows for `memory`, `web` and `mcp`; no error | open |
| V16 | cards-web labels and links | `/search` and `/directory` on dev: "Strong match" / "Good match" show, the mobile pill does not cover the name, and after opening a profile the address no longer holds `sid` and `r` | looks right | **partly verified 2026-10-26, dev and prod**: labels and `sid`/`r` links on `/search` and `/directory` (HTML), no percentage, profile renders with a good or garbage `sid`, the cleanup code is in the deployed JS. The address cleanup and the mobile label still need a browser |
| V17 | `outside-people` on dev | The digest preview and owner home for an owner who wants Investors: outside people carry a location and none has a "Grievance" or "Relations" title | all hold | open |

Deploy order for everything above: cards-api, then memory.

### Left for the end

Everything below is written and tested in code but not yet live or not yet checked. Do it once, at the end,
in this order.

| # | What | How | Status |
|---|---|---|---|
| E1 | Push `feature/people-search` and merge to `dev` | PR to `dev` (never `main` directly). Phases 1 and 2 are on the branch, not pushed | open |
| E2 | Deploy cards-api, then memory, then cards-web | Cards and memory still run from their old checkouts (AGENTS.md §3, §7): deploy on the box by hand; cards-web: build, then `pm2 restart cards-web` | open |
| E3 | First suggestions refresh | `curl -X POST "$CARDS_API/internal/suggestions/refresh" -H "Authorization: Bearer $CRON_SECRET"`; expect `written > 0`, `errors: 0`. If it times out behind the proxy, run it per handle or move it to a background job | open |
| E4 | Nightly schedule | Runs from cron on the box (`infra/single-box/crontab`, 23:30 UTC), no longer a GitHub workflow: GitHub dropped most scheduled runs. Until the crontab is installed, E3 by hand | done |
| E5 | V11 and V12 | `scripts/check_suggestions.py` on live data; owner home and a digest dry run on dev | open |
| E6 | V2–V9 | Phase 0–1 checks above (speed, `SEM_*` fit, saved-search threshold, live Chandan/investor checks, 20 real queries, `FEATURE_FACT_MATCHING`, cards-web scores, QuickEnrich Q1/Q2) | open |
| E7 | Q7 | Persona is discarded (2026-10-26); nothing to ask | ✅ closed |
| E8 | Phase 3 checks | V13–V17 above, after deploying cards-api, memory and cards-web in that order | open |
| E9 | Decisions from Phase 3 | The 4-word cap on free-text wants, "former founder" matching the role founder, and whether to tighten the golden gate back to 0.95 (see "Phase 3 as built") | open |

Applied to aafo (confirmed by a `db:migrate` dry run: `[cards] applied: 0031_card_suggestions; pending: none`): `cards/0030_filter_cards`, `cards/0031_card_suggestions`. Phase 3 adds no migration.
