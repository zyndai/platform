# ZYND People Search: Quality and Speed Follow-up Plan

> **Status:** written and implemented 2026-10-26 on `fix/people-search-quality` (see §10 "As built").
> Follows [`ZYND_PEOPLE_SEARCH_PLAN.md`](./ZYND_PEOPLE_SEARCH_PLAN.md) (Phases 0–3 shipped) and fixes what the
> live checks after #108 still found weak: speed, and high scores on loose matches.
>
> **Scope:** `services/cards-api` (scorer, search I/O), `services/memory` (re-rank, QuickEnrich mapping),
> one line in `apps/cards-web` (card creation). No schema change, no new env var or flag (AGENTS.md §9).
>
> **Needs a human (AGENTS.md §6):** the prod re-embed in step A3 (writes the `embedding` column of every
> published card), archiving two cards (F2), and the server log read in §7.
>
> Line numbers are as of `57d12b4`.

---

## 1. The problem in plain words

1. **Loose matches score like strong ones.** For "Seed-stage investor who backs AI dev tools in India",
   non-investors come back at 0.58–0.85 while labelled `match_quality: "loose"`.
2. **The right people are found and then hidden.** QuickEnrich returns real Indian seed investors
   (Together, PeerCapital, OTP Ventures, Grayscale Ventures, Eximius Ventures, GrowthCap Ventures), but
   they all score 0.374, so with `sources=all` none of them reaches the top 10.
3. **LinkedIn places are wrong or doubled** ("Bengaluru, Karnataka, India, India", "Palo Alto, India").
4. **Search is slow:** 2.4–3.5 s for a plain search, 6.4–9.1 s for a relaxed one, over only 58 cards.
5. **The corpus has no investors.** That alone limits Cards to closest matches for this query, but it is
   not why the results look bad: points 1–4 are code.

## 2. Evidence (live prod, 2026-10-26, read-only)

**Corpus** (union of 12 broad public searches, then `GET /cards/by-handle/{h}` for each):

| Fact | Value |
|---|---|
| Published cards | 58 (22 claimed) |
| Headlines that name an investor role | **0** |
| Cards whose `connect_with` includes "Investors" | 22 |
| Cards with approved facts (`zynd_memory`) | 15 of 58 |
| Data glitches | a card with handle `https:`; `atmegabuzz` and `atmegabuzz-hc6j` (second says "California, USA") |

**Scores for the investor query:**

| Call | Top results | Scores |
|---|---|---|
| Cards `/v1/agents/search`, memory's exact params | 6 developers/students, all with "Role match" **and** "Not an investor (closest match)" | 0.60–0.70 |
| `find_people`, `sources=all` | same people; card+zynd ones get +0.05 | 0.58–0.85, all `loose` |
| `find_people`, `sources=zynd` | developers | 0.14–0.36 |
| `find_people`, `sources=quickenrich` | 9 real VCs/partners + 1 healthcare CEO | **0.374 each**, all `close` |

**QuickEnrich raw (4 direct contact-finder calls, `credits_used: 0`, ~0.9 s each):**

| Request | Total | What came back |
|---|---|---|
| memory's exact body (titles + excludes + `bio_li` ["seed", "AI dev tools"] + IN) | 323 | 9 real fund partners, 1 "CEO & General Partner at SEED Healthcare" |
| same without `bio_li` | 46,064 | BDO, A.T. Kearney, Wipro, Salesforce, LTIMindtree, Grant Thornton "Principal"/"Managing Partner" |
| `title include ["Invest"]` | 46 | "Invest India", "Premji Invest": **word match, not substring** |
| `title include ["Angel Investor", "Venture Capitalist"]` | 193 | both kinds: **include is OR** |

Raw field shapes (this answers the old plan's Q1/Q2, V9):
- `employee_linkedin` has a scheme (`https://www.linkedin.com/in/...`) or is the literal `"N/A"`.
- `locality` is the person's place, already with the country ("Bengaluru, Karnataka, India",
  "Atherton, California, United States").
- `city` is address-level, probably the office ("Palo Alto", "Vihar Road", "G.K.V.K.", "Worli Naka").
- `country_code` is `IN` even for people whose `locality` is in the US: it echoes the filter or the
  company, **not the person**.

**Speed** (prod from outside; TLS round trip to `/health` is ~0.5 s):

| Call | Total (3 runs) | Server time, roughly |
|---|---|---|
| `/v1/agents/lookup?name=chandan` | 1.3–1.6 s | ~1 s |
| search, `q` only | 2.4–3.1 s | ~2 s |
| search, memory params, no relax | 2.2–2.8 s | ~2 s |
| search, memory params, `relax=true` | 6.4–9.1 s | ~6 s |

One of these calls returned an empty, non-JSON body once (status unknown) and worked on retry.

## 3. Root causes

### A. Wanting to meet a role reads as being that role

**Q1. The "looking to connect with …" fact describes the person.**
`apps/cards-web/src/app/(site)/create/page.tsx:261-264` appends
`"<name> — looking to connect with Founders, Investors, … — Zynd"` to `searchable_facts`.
`cards-api/services/embed.py:27` puts `searchable_facts` into `card_search_text`, which is used for:
- the role check: `search.py:470` `role_matches(role_tokens(search_text), want_role)` finds "investors"
  → "Role match", `FIT_ROLE_ELSEWHERE` 0.9 instead of `FIT_ROLE_MISSING` 0.5;
- word coverage: "investor" counts as a query term found on the card (`search.py:426-428`);
- the stored embedding (`cards.py:509, 719, 1209, 1230`), so the cosine to "investor who…" is high.

The same field is already stored on its own (`card.connect_with`), and that is what two-way matching
reads (`two_way.py`). So the fact adds nothing to two-way matching and corrupts the person's
description. The same thing bites suggestions: a Phase 2 target "investor who backs AI" will rank cards
that *want* investors.

**Q2. Generic topic words match every developer.** The parser turns "AI dev tools" into the topics
"AI development" and "developer tools". Cards scores topics word by word (`search.py:438-446`), so
"development" and "developer" hit nearly every card ("Mentions development, developer"). Memory's
`features` does the same with `topic_fit` (`people_results.py:221-222`), and because the Cards reason
"Mentions …" is in `why`, it also counts as topic evidence there.

### B. The re-rank cannot compare LinkedIn with Cards

**Q3. LinkedIn keeps the Phase 0 score.** `rank_quickenrich` (`people_discovery.py:398-424`) scores
`0.30 + 0.25 × mean(fits)`, so the most a LinkedIn person can get is 0.55. `person_from_external`
(`people_results.py:133-135`) keeps that score ("a re-ranked row carries its own score"), so the
Phase 1.2 scale (`LINKEDIN_PRIOR` 0.8 × order × fit) never applies. `rescore` then multiplies by
`FIT_TOPIC_MISSING` 0.8, because a LinkedIn record has no text to find a topic in.

**Q4. The fits are constant, so every LinkedIn person ties.** title_fit is 1 (the request already
filtered titles), location_fit is 1 (country_code always equals the filter, see §2), company_fit is 0
(a topic word is almost never in a company *name*). 0.467 × 0.8 = 0.374 for everyone.

**Q5. Sorting ignores match quality.** `merge_people` (`people_results.py:192`) and `_rank` sort by
score only; `label_quality` runs afterwards. A `close` investor ranks under a `loose` non-investor
whenever its score is lower, and the user sees the score contradict the label.

### C. QuickEnrich results are mapped wrong

**Q6. Places.** `_qe_location` (`people_discovery.py:342-346`) prefers `city` (the office) over
`locality` (the person), then appends the country from `country_code`, which is already inside
`locality` and is not the person's country. `rank_quickenrich` and `features` judge location from the
same fields, so a person in Los Altos counts as "in India".

**Q7. Broad titles without a fund signal.** "Principal" and "Managing Partner" are in the investor
include list (`people_query.ROLE_TITLE_FILTERS`). With `bio_li` they return funds; without it (any path
that sends titles only, such as the outside-people suggestions in Phase 2.5) they return consultancies.
The stage word "seed" in `bio_li` matches "SEED Healthcare".

### D. Every search pays for many sequential round trips

**Q8. I/O, not computation.** With 58 cards the scoring itself is milliseconds. From the code, one plain
search does, one after another:
1. a new OpenAI client and an embedding call (`config.get_openai_client()` builds a client per call,
   `embed.py:11`), with no cache for a repeated query;
2. `match_cards` RPC, `search_cards_fts` RPC, the beacon scan (`beacons.candidate_rows`, a third read of
   `agent_profile_cards`), in `_candidates` (`search.py:97-127`);
3. `get_card_by_handle` for `as_handle` (`api/agents.py:53`);
4. `claimed_by_handles` and `trust.verified_by_card_ids` (`api/agents.py:70-75`);
5. the `search` event insert, synchronous in the request (`events.emit` → `_insert_rows`).

A relaxed search runs step 2 again per pass (a `filter_cards` RPC, or `match_cards`+fts+beacons once
the role is dropped): three passes for the investor query. cards-api runs one uvicorn worker
(`Dockerfile:13`), so concurrent searches queue behind each other's sync calls, which fits "dev was
slower under load". Memory waits 8 s (`CARDS_TIMEOUT_SECONDS`), then retries without relaxing, so the
worst case is ~10 s.

This breakdown is read from the code and outside timings; §7 says how to confirm it on the server.

### E. The tests can't see any of this

**Q9. Fixtures don't look like prod.**
- `cards-api/tests/fixtures/search_golden.json`: 41 synthetic cards, none with a "looking to connect
  with" fact, so the golden set scores 0.993 while prod ranks would-be investors first.
- `memory/tests/fixtures/quickenrich_records.json` puts the place in `city` with `locality: null`, and
  uses scheme-less URLs. The real API is the other way round.

## 4. Decisions

| # | Decision | Why |
|---|---|---|
| E1 | **What someone wants is never evidence of what they are.** "Looking to connect with" text is excluded from role checks, word matching, topic matching and the embedding; it is used only for two-way matching, as `connect_with` already is. | Q1 |
| E2 | **A multi-word topic matches as a phrase.** "developer tools" needs "developer tool(s)" or "devtools"; single generic words never count alone. | Q2 |
| E3 | **Rank by match quality first, then by score; the score never contradicts the label.** `exact` above `close` above `loose`, and a `loose` score is capped below the strong-match line (see question 1 in §8). | Q5, user report 2 |
| E4 | **LinkedIn people use the same scale as everyone else**, with a title-strength term in place of the constant fits. A fund partner who meets role and place can beat a Card that is not the role. | Q3, Q4 |
| E5 | **QuickEnrich's `locality` is the person's place; `country_code` is not a person signal.** | Q6 |
| E6 | **A Cards search reads the database at most once per request**, from a short in-process cache; the event write leaves the request path. | Q8 |
| E7 | **Fixtures copy real shapes** (field layout, generated facts), with made-up names. | Q9 |

## 5. Implementation plan

Order: A and B fix the ranking (the visible bug), C fixes LinkedIn data, D fixes speed. Each phase is a
separate commit on `dev` and can ship alone. Golden sets gate every scoring change (old plan D7).

### Phase A: Wanting is not being (cards-api, cards-web)

**A1. Split the wants-to-meet text out of the person's text.**
- `services/cards-api/services/embed.py`: `card_search_text` skips any `searchable_facts` entry that
  matches `_WANTS_FACT = re.compile(r"\s—\s(?:looking to connect with|wants to meet)\s", re.I)`. Keep
  the entry in storage (public card display and `/ask` may read it; check both while implementing).
- `search.py` uses `card_search_text`, so the role check, word coverage and topic hits drop it at once,
  with no data change.
- Also check `zynd_memory` facts with an `is_seeking`-style predicate (`two_way._SEEKING_KINDS`):
  `card_search_text` adds `fact_object` + `fact_predicate` (`embed.py:34-39`), so an approved
  "seeking: investors" fact has the same effect. Exclude seeking predicates from the person's text in the
  same way.
- Tests (`tests/test_search*.py`): a developer card with the wants-to-meet fact gets `FIT_ROLE_MISSING`
  for role "investor" and no "Role match" reason; a real investor card still gets "Role match"; two-way
  matching still sees `connect_with`.

**A2. Stop writing the fact.** `apps/cards-web/src/app/(site)/create/page.tsx:261-264`: drop the
`looking to connect with` line (the `connect_with` answers are already saved on the card). Keep
"working on" and "loves talking about": those describe the person. `npm run lint && npx tsc --noEmit`.

**A3. Re-embed published cards (human step).** The stored embeddings still contain the text.
`cd services/cards-api && python scripts/reembed_all.py` (dry run), then `--apply`. 58 cards, a few
cents of OpenAI. Run it after A1 is deployed, or the old text is embedded again. Optionally run it on
the box: `docker compose -p zynd exec cards python scripts/reembed_all.py`.

**A4. Topics as phrases (Q2).**
- Cards `_search_pass`: a topic of 2+ words scores 1 only when its words appear next to each other
  (allowing a plural and "dev"/"developer", "devtools"), 0.5 when all its words appear apart, 0 otherwise.
  One-word topics in a small generic list (`development`, `developer`, `tools`, `software`, `technology`,
  reuse memory's `_GENERIC_TOPIC_WORDS`) never score alone. The reason becomes "Mentions developer
  tools", never "Mentions development, developer".
- Memory `features`: `topic_fit` uses the same phrase rule and stops reading Cards' "Mentions …" reasons
  as evidence; it reads headline, skills and approved facts.
- Memory `people_query._merge_llm`: when the LLM rewrites a heuristic phrase ("AI dev tools" →
  "AI development"), keep the heuristic phrase and add the LLM one only if all its content words are in
  the query. "AI development" fails ("development" is not in the query); "developer tools" passes via
  the dev→developer alias.

**A5. Golden set gains prod-shaped cards (Q9).** In `search_golden.json`:
- add the wants-to-meet fact to at least 15 of the 41 synthetic cards, including every developer;
- add 3 real-shaped investor cards ("General Partner at X Ventures", "Angel investor");
- new gates: for every investor query, no card without an investor role in its headline or approved
  facts scores above `MIN_SCORE` × 2 (0.5), and no such card ranks above an investor card.
- Re-baseline precision@5 and recall@5 before and after A1+A4 and write the numbers here.

**Phase A is done when** the live investor query returns no "Role match" on a non-investor, the
non-investor Cards score at most ~0.4, and the golden set holds its floor.

### Phase B: One order, honest scores (memory)

**B1. LinkedIn on the shared scale (Q3, Q4).** Replace `rank_quickenrich`'s score with:

`score = LINKEDIN_PRIOR (0.8) × title_strength × fit_factor(features)`

- `title_strength`: 1.0 when the title names the role or a strong title for it (investor: Investor,
  Angel Investor, General Partner, Venture Partner, Venture Capitalist; Managing Partner or Principal
  only when the company name looks like a fund: Ventures, Capital, Partners, Fund, Investments, VC);
  0.6 for the other include words; 0 for an excluded word (already dropped).
- `fit_factor` as today, except `topic_fit` is `None` for LinkedIn (a record has no text to judge
  topics from), so it costs nothing. When the request had topic phrases in `bio_li`, the reason says
  "Company matches AI dev tools (LinkedIn)" instead of claiming the person works on it.
- `person_from_external` keeps the row's score (already does); `rescore` no longer multiplies LinkedIn
  rows a second time (the factor is inside the score now).
- Ties break on: has a LinkedIn URL, then the provider's order.

Expected for the investor query: "General Partner at Grayscale Ventures, Bengaluru" → 0.8 × 1.0 × 1.0 =
0.80 `close`; "CEO & General Partner at SEED Healthcare, Miami" → 0.8 × 1.0 × 0.6 (not in India) = 0.48
`loose`.

**B2. Quality first (Q5, E3).**
- Move the `match_quality` computation into `_rank` (before the cut to `k`), out of `label_quality`,
  which then only writes the `note`.
- Sort by (`exact`, `close`, `loose`), then score, then claimed, then name.
- Cap scores per tier so a number never says more than the label: `loose` ≤ 0.45, `close` ≤ 0.79,
  `exact` uncapped (constants `LOOSE_CEILING`, `CLOSE_CEILING`). This is question 1 in §8.
- `STRONG_CARD` (0.5) stays: a capped `loose` result can never count as strong.
- Update the `find_people` docstring: "score is comparable across sources; results are ordered by
  match_quality, then score".

**B3. Pool size for LinkedIn.** The early QuickEnrich call asks for `limit` (k) records. Ask for 10 (the
provider's page) and two pages when the first has fewer than k with a LinkedIn URL (costs 0 credits),
so at least 90% of LinkedIn results have a URL (old V5 bar).

**B4. Tests.** `test_people_results.py`: tier order beats score; caps; title_strength for each
investor title; a LinkedIn fund partner in India outranks a relaxed non-investor Card.
`test_outside_people.py`: the same through `outside-people`. Grow `people_golden.json` with the
investor case expecting a LinkedIn investor first when Cards has none.

**Phase B is done when** the live `find_people` investor query (`sources=all`) shows real investors
first, labelled `close`, and every `loose` result scores ≤ 0.45.

### Phase C: QuickEnrich data (memory)

**C1. Places (Q6).** `_qe_location`: use `locality` when present (it already has the country); else
`city` + country name; never append a country that the string already contains (compare against
`COUNTRIES` names and codes). `row["city"]` becomes the first part of `locality`. `location_fit` for
LinkedIn uses that string, not `country_code`.

**C2. Ask for the person's country, if the API allows it.** One manual call: does
`locality: {"include": ["India"]}` match by word inside "Bengaluru, Karnataka, India"? If yes, send it
next to `country_code` for country-level targets; if no, keep `country_code` and rely on C1 to rank
non-residents down and label them "Not in India".

**C3. Fund signal for broad titles (Q7).** In `quickenrich_body` for investors: when there are no topic
phrases, `bio_li` is always ["venture capital", "venture", "investments", "fund"] (never titles alone);
drop "Principal" and "Managing Partner" from the include list when a request cannot carry `bio_li`. Send
the stage as "seed fund" / "pre-seed" instead of the bare word "seed" (one manual call to check that
`bio_li` matches phrases).

**C4. Fixture from real shapes (Q9).** Replace `tests/fixtures/quickenrich_records.json` with the
layout of the real response: `city` as an office street, `locality` as "City, State, Country", a
`country_code` that disagrees with `locality`, `"N/A"` URLs, a "SEED Healthcare" company. Made-up names.
Update `test_quickenrich_records.py` and `test_people_discovery.py` (`_linkedin_with_scheme` stays, it
is harmless).

**C5. Record the answers.** Write Q1/Q2 from §2 into the old plan's §9 and close V9.

**Phase C is done when** no LinkedIn place repeats its country or pairs a US city with India, and the
investor query has no consultancy or healthcare titles in the first 10.

### Phase D: Speed (cards-api, memory)

**D0. Measure first** (§7): get the server's `slow search` lines, or run `bench_search.py` on the box,
so each step below has a before/after number.

**D1. One in-process snapshot of published cards.** `services/cards-api/services/card_cache.py`:
`published_snapshot()` returns parsed rows `{id, handle, card (validated), embedding (list[float]),
claimed, has_beacon}` from one `list_published_rows` call, cached for `SNAPSHOT_TTL_SECONDS = 60`, and
cleared in-process on publish, update, archive and claim (cards-api is one worker, so this is exact for
its own writes; the TTL covers writes from other processes).
- `_candidates` and `_rows_for` read the snapshot instead of `match_cards`, `search_cards_fts`,
  `filter_cards` and the beacon scan, while the corpus is below `SNAPSHOT_MAX_CARDS = 5000`; above it,
  today's RPC path stays (the code is kept, not deleted).
- Cosine in Python over 58 cards is microseconds; at 5000 cards about 5 ms.
- Lexical candidates: today's FTS adds cards with no vector hit; with the snapshot every card is scored,
  so nothing is lost.
- `claimed_by_handles` reads `claimed` from the snapshot.
- Relaxed passes reuse the same snapshot, so a relaxed search costs the same I/O as a plain one.
- Tests: a search with the snapshot and the old RPC path return the same handles on the golden set; a
  publish invalidates it.

**D2. Embedding.** One module-level OpenAI client (`embed.py`), and an LRU of query embeddings
(`QUERY_EMBED_CACHE = 512` entries, 10 min). Memory's timeout retry and repeated assistant calls then cost
no second embedding.

**D3. Off the request path.** The `search` event insert runs in FastAPI `BackgroundTasks` (or a thread),
never awaited by the response. `verified_by_card_ids`: cache 60 s inside the snapshot.

**D4. Lookup.** `/v1/agents/lookup` matches names against the snapshot too (it takes ~1 s server-side
today for a single `ilike`).

**D5. Memory.** Keep the 8 s timeout and the retry as a guard, but log per-source milliseconds in the
`find_people` line (`cards_ms`, `zynd_ms`, `qe_ms`), so the next slow search says where it waited.
Cards' `slow search` line adds the embedding time and the post-search reads.

**Phase D is done when** server time for a relaxed search is under 800 ms p95 (`bench_search.py` on the
box) and the outside total is under ~1.5 s, about the same as a plain search.

### Phase F: Data (decided in §8)

- **F1. Investors in the corpus.** No data change; Phase B makes LinkedIn investors visible.
- **F2. Clean-up.** Archive the `https:` handle card (a bad import) and the duplicate `atmegabuzz-hc6j`:
  read both rows, show them to the owner, then set `status` to archived after their OK.

## 6. Testing

Before and after each phase (AGENTS.md §5):

| Service | Command | Known failures |
|---|---|---|
| cards-api | `cd services/cards-api && pytest -q` | 2 (`test_x_bot.py`) |
| memory | `cd services/memory && uv run pytest -q -m "not integration"` | 9 (DB-dependent) |
| cards-web | `npm run lint && npx tsc --noEmit` | — |

**Live checks after deploy** (the same calls as §2, so the numbers compare):

| # | Check | Pass when |
|---|---|---|
| L1 | Cards search, memory's investor params | no "Role match" on a non-investor; top score of a non-investor ≤ 0.45 |
| L2 | `find_people` investor query, `sources=all` | the first results are LinkedIn investors, `close`; no `loose` result > 0.45 |
| L3 | same, `sources=quickenrich` | distinct scores; no doubled country; no "Palo Alto, India"; ≥ 90% with a URL |
| L4 | "chandan", "Chandan Kumar", "chandan from zynd" | `chandan-kumar-2en8` still first |
| L5 | timings, 3 runs each | plain and relaxed both ≲ 1.5 s from outside |
| L6 | suggestions refresh for an owner who wants Investors | no suggested person whose only investor link is wanting investors |

## 7. What I need from the server (not blocking, but it confirms Phase D)

On the box, from the repo root:

```sh
# Cards: where slow searches spend time (one line per search over 3 s)
docker compose -p zynd logs --since 48h cards | grep "slow search" | tail -50
# Memory: one line per find_people (source counts, warnings, total ms)
docker compose -p zynd logs --since 48h mcp api | grep "find_people search_id" | tail -50
# Any 5xx or tracebacks around searches (the one empty response I saw)
docker compose -p zynd logs --since 48h cards | grep -iE "error|traceback|timeout" | tail -50
# Round trip from the box to Supabase and OpenAI (the cost of each sequential call)
docker compose -p zynd exec cards python - <<'EOF'
import time; from services import cards as c, embed
for i in range(3):
    t=time.monotonic(); c.claimed_by_handles(["chandan-kumar-2en8"]); a=time.monotonic()-t
    t=time.monotonic(); embed.embed_text("investor"); b=time.monotonic()-t
    print(f"supabase {a*1000:.0f} ms  openai {b*1000:.0f} ms")
EOF
# Calibrate SEM_FLOOR/SEM_SPAN and get p95 (read-only)
docker compose -p zynd exec cards python scripts/bench_search.py --runs 10
```

The dev stack is the same with `-p zynd-dev` and the `-dev` service names.

## 8. Decisions taken (owner, 2026-10-26)

1. **Score caps (B2):** sort by match quality **and** cap: `loose` ≤ 0.45, `close` ≤ 0.79.
2. **Re-embed (A3):** yes. Prepare and dry-run it, then ask the owner before `--apply` at deploy time.
3. **Investors in the corpus (F1):** leave the corpus as it is. With Phase B, LinkedIn investors show
   first as `close` matches. No invitations, no generated Cards.
4. **Clean-up (F2):** archive both the `https:` card and `atmegabuzz-hc6j`. This is a prod write: look at
   both rows first, and ask before the write (set `status` to archived; never delete).

## 9. Risks

- **Scores drop everywhere** after A1/A4: saved-search alerts use `STRONG_MATCH = 0.6` (cards-api) and the
  digest reads suggestion scores. Check both on the golden set; alerts may fire less (correctly).
- **Two-way boost** must keep working without the fact: it reads `connect_with` (verify in A1 tests).
- **Snapshot staleness** (D1): a card edited by another process shows its old text for up to 60 s.
- **QuickEnrich behaviour** (C2/C3) is inferred from four calls; confirm before relying on it.
- Deploy order: cards-api (A1, A4, D) → re-embed (A3) → memory (B, C). Memory alone is safe too: it
  only re-orders what Cards sends.

## 10. As built (2026-10-26)

Two commits on `fix/people-search-quality`. Tests: cards-api 797 passed (only the 2 known `test_x_bot.py`
failures), memory 858 passed; cards-web lint (0 errors) and `tsc --noEmit` clean.

**Phase A (cards-api, cards-web).**
- `embed.card_search_text` leaves out the wants-to-meet fact (`is_wants_fact`), `is_seeking` facts
  (`describes_person`) and free-text wish clauses ("looking forward to meet … investors", `strip_wishes`).
  The scorer's word and topic cover read only facts that describe the person.
- Found on the live corpus, not in the plan: "working on Investing" (a cards-web interest label) made the
  synonym "investing" fire the role. `role_matches(..., activities=False)` (`ACTIVITY_SYNONYMS`) is used for
  text outside a headline or job title.
- Topics: `search_text.topic_phrases` / `phrase_score`. A multi-word topic scores 1 as a phrase (one word may
  sit between), otherwise up to 0.5 for its specific words found apart; generic words alone earn nothing.
- Golden: 18 non-investor cards now want "Investors" (only that label, so the suggestions golden owners keep
  their two-way relations) and carry the fact cards-web writes. New gate
  `test_with_no_investors_wanting_to_meet_one_never_scores_like_being_one`: fails on the old scorer (a founder
  at 0.80), passes on the new (≤ 0.45). Precision@k 0.989 and recall@5 0.995, unchanged.
- **Real corpus** (the 58 live cards, real `text-embedding-3-small` vectors, memory's exact investor params,
  run locally): top non-investor 0.752 → 0.313, no "Role match" on a non-investor; "investors in Bengaluru"
  returns no Card instead of six 0.2 noise hits; "rust engineer" and "founders building AI agents" unchanged.
- cards-web no longer writes the fact. **A3 is not done**: existing cards keep it in their stored text until
  `scripts/reembed_all.py --apply` runs (ask the owner; run after this is deployed).

**Phase B (memory).** LinkedIn score = `LINKEDIN_PRIOR` 0.8 × `title_strength`, then the shared fit;
LinkedIn `topic_fit` is unknown (`None`). `order_by_quality` sets `match_quality` before the cut and caps
scores (`LOOSE_CEILING` 0.45, `CLOSE_CEILING` 0.79). Not the asked role is always `loose`; a broad title at a
non-fund company is a partial role (`PARTIAL_ROLE`, close at best, no "Investor (title)" reason). A loosened
place that is also missed counts once. Found while testing: a country target now counts a city of that
country (`_in_country`, from `CITIES`), so a Card in "Pune" is in India.
**Not done:** B3 (a second QuickEnrich page when the first lacks URLs); with the C request below, 10 of 10
had URLs in the live check.

**Phase C (memory).** Two more live calls (0 credits) showed `bio_li` matches phrases and `locality` matches a
country word. The request sends `locality: [country name]` for a country target (not for the US),
"seed stage"/"seed fund" for "seed", only strong titles when nothing narrows the company, and excludes
"Relation" too. Live, memory's new request for the investor query returned 10 Indian VC partners, all with a
LinkedIn URL and an Indian locality (one "Investor Relation" title, now excluded). `_qe_location` uses
`locality`. The fixture has the real layout. **Not done:** the memory-side phrase rule for `topic_fit`
and the `_merge_llm` change in A4; Cards' phrase scoring covers the case that was hurting.

**Phase D (cards-api, memory).**
- `services/card_cache.py`: one copy of the published cards (≤ `SNAPSHOT_MAX_CARDS` 500, `SNAPSHOT_TTL_SECONDS`
  30), parsed once, unit vectors so cosine is a dot product (no numpy in cards-api). Every pass of a search
  scores the same copy; `/search`'s searcher and claimed flags and `/lookup` read it too; every cards-api
  write to `agent_profile_cards` calls `invalidate()`. Above 500 cards the old database path runs unchanged.
- Locally over the 58 real cards: a warm relaxed search does 0 card reads (was 3 per search, each a round
  trip on prod) and ~45 ms of CPU.
- One OpenAI client per process; query vectors cached 10 min (`QUERY_VECTOR_TTL_SECONDS`), so memory's
  timeout retry costs no second embedding. Verification badges cached 60 s.
- D3 was already true: `events.emit` writes in a background task.
- Memory's `find_people` log line adds `ms_by_source=cards:…,zynd:…,quickenrich:…`.
- `tests/conftest.py` turns the snapshot off by default (tests fake the database per test);
  `tests/test_card_cache.py` turns it on, including a golden-set equivalence check.

**Still open:** deploy (cards-api first, then memory), then the live checks L1–L6 in §6; A3 re-embed and the
F2 archive with the owner's OK; §7 server logs to confirm the new timings.
