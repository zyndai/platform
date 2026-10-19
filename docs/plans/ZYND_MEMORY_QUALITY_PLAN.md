# ZYND Memory Layer — Fact Quality & Context Retrieval Plan

> **Status:** proposed, 2026-10-20 — not implemented.
>
> **Scope:** `services/memory` (fact writes, ranking, decay) and the parts of
> `services/persona-api` that write facts into it (GitHub / LinkedIn / Twitter
> sync, chat ingest) or read context from it (`agent/memory_client.py`).
> Small follow-ups in `apps/cards-web` and `apps/persona-web` for display only.
>
> **Schema note:** memory's schema is *not* in `packages/db`. It lives in
> `services/memory/sql/schema.sql` (idempotent `CREATE TABLE IF NOT EXISTS` /
> `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, applied by `app/schema_apply.py`).
> "Migration" below means an expand-only edit to that file, rehearsed on a
> throwaway Postgres first. **Phase 4's schema change and Phase 5's data
> cleanup both need a human's go-ahead before they touch memory's prod DB**
> (AGENTS.md §6).

---

## 1. The problem in plain words

Users see three kinds of junk in their memory and on their card:

1. **Things they don't actually use.** A language or tool that only lives in
   a dependency, a config file, or generated code shows up as "Skilled in X".
2. **The same thing twice.** JavaScript under both "Skilled in" and "Tools I
   use". The same project under both "Working on" and "Interested in".
3. **Stale facts that never leave.** A "working on" from months ago still
   comes back in every context call.

And on the read side:

4. **`get_my_context` doesn't really filter.** It returns a big, arbitrary
   slice of everything, and the `topic` argument barely changes the result.

The goal: **memory stores few, useful, de-duplicated facts, and context
returns what's true now, plus older facts only when they relate to what the
user is asking about.**

---

## 2. What's causing it (evidence from the code)

### 2.1 Retrieval ignores relevance and freshness

`services/memory/app/services/export.py`

- `active_context()` (line ~59) runs
  `SELECT DISTINCT ON (a.predicate, e.canonical_name) … ORDER BY a.predicate, e.canonical_name, a.confidence DESC LIMIT k`.
  The `ORDER BY` needed by `DISTINCT ON` is also the order the `LIMIT`
  applies to, so the top-K is **the first K facts alphabetically by predicate
  name** (`has_expertise_in`, `has_skill`, `intends_to`, `is_building`, …),
  not the most confident or the most recent.
- `context_slice()` (line ~87) has the same shape. Topic similarity
  (`e.embedding <=> topic`) is only the third sort key, so it only picks
  between rows that share predicate *and* name. **The topic filter is
  effectively a no-op.**
- Neither query looks at how old a fact is. Only the nightly decay job does,
  and that's broken too (§2.4).

`services/persona-api/agent/memory_client.py` `get_context()` (line ~130)
works around this: it pulls up to 50 facts from `/me/context` (which has no
`topic` parameter, `services/memory/app/main.py` ~539) and ranks them
client-side by **keyword overlap**. So persona chat effectively fetches
"everything" and string-matches it.

### 2.2 Duplicates: the same thing stored under different labels

An assertion's identity is `(user_id, predicate, object_entity_id)`
(`assertions.py` `upsert_assertion`). Anything that differs in predicate *or*
resolves to a different entity becomes a separate fact.

| Source of duplicate | Where | Example |
|---|---|---|
| Typed MCP fields map to different predicates | `mcp_http.py` `report_user_info` ~334: `languages`/`frameworks`/`skills` → `has_skill`, `tools` → `uses_tool` | Agent passes JavaScript in both `languages` and `tools`, giving two facts |
| Entity resolution is per `entity_type` | `entities.py` `resolve_entity`: exact and embedding match both filter `entity_type = $3` | `has_skill` uses `skill_technical`; extraction may emit `skill_domain` or `concept_topic` for the same name, so no merge |
| No name normalization | `quality.canonicalize` only trims whitespace and quotes | "JS", "javascript", "JavaScript" are three strings; exact match fails, and the 0.92 embedding threshold doesn't always catch short names |
| GitHub sync writes twice | `persona-api/services/github_sync.py` `sync_to_memory` ~451: declares `has_skill` per language **and** ingests an LLM summary containing "Main languages: …", which extraction turns into `has_skill` / `uses_tool` / `has_expertise_in` again | Python ×2–3 after one sync |
| LinkedIn sync writes twice | `linkedin_scraper.py` ~435 declares facts, ~447 ingests a summary turn | Same pattern |
| Overlapping predicate families | `is_working_on` / `is_building` / `is_learning` (persona profile "interests" are declared as `is_learning`, `persona_ingest.py` ~116) | "Working on: Zynd" and "Learning: Zynd" |
| Display-only dedupe | `apps/cards-web/src/lib/memory-facts.ts` folds `has_skill` into `has_expertise_in`, but nothing folds `uses_tool` or `is_learning` | The UI hides some duplicates and shows others |

Related bug, worth fixing in the same pass: persona-api declares predicates
that **are not in memory's taxonomy**: Twitter `is_interested_in`
(`twitter_scraper.py` ~292), LinkedIn `works_at` and `lives_in`
(`linkedin_scraper.py` ~330). `declare_private` raises `ValueError` for these,
which becomes a 400. `declare_fact` swallows it at `debug` level, so these
writes **probably fail silently** (verify in logs). The facts then only arrive
through LLM extraction of the summary turn, with whatever predicate the LLM
picks.

### 2.3 Dependency / incidental tech gets saved as skills

- **GitHub:** `_derive_profile` (`github_sync.py` ~209) sums
  `/repos/{repo}/languages` bytes across up to 100 owned non-fork repos and
  takes the top 8 (`MAX_SKILLS`) with **no minimum share and no ignore
  list**. HTML, CSS, Shell, Dockerfile, Makefile, generated code and
  committed vendored code all count.
- **Extraction prompt** (`services/memory/app/services/extraction.py`)
  tells the LLM what `uses_tool` means but not that a dependency, a package
  in a lockfile, or a stack mentioned in passing is *not* the person's tool
  or skill. Persona chat ingests every user turn (`persona_manager.py` ~702),
  so "my build fails in some-lib's webpack config" can become
  `uses_tool → webpack`.
- **Coding agents** call `report_user_info` with whatever stack they see in
  the repo. The tool description says "only EXPLICITLY stated", but nothing
  enforces it. One call can add up to `MAX_TYPED_TOTAL` facts.

### 2.4 Old facts don't go away, and decay math is wrong

`services/memory/app/services/decay.py` `run_decay_job`:

```
new = current_confidence × 0.5 ^ (days_since_observed / halflife)
```

It runs nightly on the **already-decayed** `confidence`, while
`days_since_observed` keeps growing from the original date. Night *n* gives
`c₀ × 0.5^(n(n+1) / 2h)`: quadratic, not exponential. For `is_working_on`
(h = 14 days) a 0.9 fact is archived after **~9 days** instead of the intended
~44.

But in practice old facts *stick*, because:

- Every re-mention runs a Bayesian bump (`bayesian_update`) and resets
  `observed_at`, so anything touched now and then never fades.
- Declared facts (`declare`, `declare_private`, `declare_for_review`) write a
  flat confidence and are re-declared by syncs.
- There is no concept of "current vs past". A fact is either active
  (`valid_until IS NULL`) or archived, and archived facts can't be reached by
  a topic query.

Action item: check whether `decay_cron` actually runs in prod
(`assertion_history` rows with `change_reason = 'decay'`). If it doesn't,
that alone explains much of the staleness.

---

## 3. Decisions (agreed 2026-10-20)

| # | Question | Decision |
|---|---|---|
| D1 | When does a language/tool count as the user's own skill? | **Strict + threshold.** Saved if the user stated it, or it's a big share of their own code (≥ 15% of bytes and in ≥ 2 repos; ≥ 15% alone if they have one repo). HTML/CSS/Shell/Dockerfile/Makefile and vendored/generated code are ignored. |
| D2 | JavaScript shows up as both a language and a tool. Where does it live? | **Languages and frameworks are always skills** (`has_skill` / `has_expertise_in`). "Tools I use" (`uses_tool`) is only for products: Docker, Cursor, Supabase, Figma. Each thing appears once. |
| D3 | What happens to old "working on" / "interested in" facts? | **Hide from default context, keep searchable.** They drop out of the no-topic context packet but come back when a topic query matches. Nothing is deleted. |
| D4 | When is a "working on" fact old? | **30 days** without being seen again. |

---

## 4. Target behaviour

### 4.1 Write side: "one fact per thing"

Every fact write, whether extraction, typed MCP, declared, or a sync, goes
through **one function** that:

1. **Normalizes the name** (`js` → `JavaScript`, `postgres` → `PostgreSQL`).
2. **Classifies tech names** as `language | framework | product | other`, and
   moves a language/framework sent as `uses_tool` to `has_skill` (D2).
3. **Finds the existing fact for that thing** in the same *family* (§5.2.3),
   regardless of predicate or entity type.
4. **Keeps the stronger predicate.** A weaker report only refreshes the
   stronger fact's `last_seen_at`. A stronger report supersedes the weaker
   fact (archived, not deleted).
5. **Records `last_seen_at` and `mention_count`** (Phase 4).

### 4.2 Read side: "now" by default, "related" on request

| Call | Returns |
|---|---|
| `get_my_context()` / `GET /me/context` with **no topic** | **Core** facts (location, affiliation, top expertise, what they're building) + **now** facts (non-stale, ranked by confidence × freshness). No stale facts. |
| `get_my_context(topic="…")` / `GET /me/context?topic=…` | Everything above that relates to the topic, **plus related** older or stale facts whose similarity clears a floor, marked `stale: true`. Ranked by relevance × confidence × freshness. |

Each returned fact gets additive fields: `section` (`core | now | related`),
`stale` (bool) and `last_seen_at`. Existing fields stay, so old clients keep
working.

---

## 5. Implementation plan

Phases are ordered by value ÷ risk. Each one is a separate PR to `dev` with
the memory test suite at its baseline (AGENTS.md §5: 9 known DB-dependent
failures). New behaviour sits behind a `settings.feature_*` flag where it
changes stored data or output shape, matching the existing
`feature_s05_*` / `feature_s01_*` pattern.

### Phase 1: Retrieval that actually filters (no schema change)

**Goal:** fix §2.1. Biggest user-visible win, read-only, easy to roll back.

1. **`services/memory/app/services/export.py`**, new
   `rank_context(pool, user_id, *, topic: str | None, k: int) -> list[dict]`
   replacing the bodies of `active_context` and `context_slice` (keep both
   names as thin wrappers so callers don't change):
   - Inner query: active facts (`valid_until IS NULL`, `dismissed_at IS NULL`),
     deduped with `DISTINCT ON (family(predicate), lower(canonical_name))`,
     keeping the strongest predicate per family (§5.2.3), then highest
     confidence.
   - Outer query: `ORDER BY score DESC LIMIT k`, where until Phase 4 lands
     - `freshness = 0.5 ^ (days_since(coalesce(observed_at, extracted_at)) / halflife)`
       (1.0 for no-decay predicates)
     - `stale = predicate ∈ TIME_BOUND and days_since(...) > STALE_AFTER_DAYS[predicate]`
     - no topic: `score = confidence × freshness × predicate_weight`, `stale` rows excluded
     - topic: `relevance = 1 − (entity.embedding <=> topic_vec)`;
       include rows with `relevance ≥ RELATED_MIN`;
       `score = relevance² × confidence × max(freshness, 0.3)`
   - **Core facts** (`is_located_in`, `is_affiliated_with`, top 3
     `has_expertise_in`, top 3 `is_building`) are always included when there's
     no topic, capped so they never crowd out "now" facts (≤ 40% of `k`).
   - Keep `CONTEXT_CONFIDENCE_FLOOR = 0.4` for both modes. Today it only
     applies to the topic path.
2. **`services/memory/app/taxonomy.py`**, add:
   - `STALE_AFTER_DAYS: dict[str, int]`: `is_working_on: 30` (D4),
     `is_learning: 60`, `is_seeking: 30`, `intends_to: 45`,
     `is_preparing_for: 30`, `is_building: 120`. Others never go stale.
   - `PREDICATE_FAMILY` and `FAMILY_RANK` (§5.2.3), used by both read and
     write paths.
   - `CORE_PREDICATES`.
   - `RELATED_MIN = 0.45` (starting value, tuned in step 6).
3. **`services/memory/app/main.py` `GET /me/context`**: add `topic: str | None = None`
   and route it to the ranked path. Response stays additive.
4. **`services/memory/app/mcp_http.py` `get_my_context`**: same ranking.
   Update the docstring to tell the AI to **pass `topic`** whenever the
   conversation has a subject, and that facts with `stale: true` are past
   context, not current.
5. **`services/persona-api/agent/memory_client.py` `get_context`**: pass
   `topic` to `/me/context` and use the server's order. Keep
   `_keyword_relevance` only as a fallback when the server returns no
   `relevance` (older memory deploy).
6. **Eval set** (`services/memory/tests/fixtures/context_eval.json`): about 10
   synthetic users with a hand-labelled "should appear / should not appear"
   list for no-topic and 3 topics each. A test asserts precision@k ≥ target,
   used to tune `RELATED_MIN` and the weights. Runs under
   `-m integration` (needs Postgres + pgvector).

**Done when:** no-topic context for a user with 100+ facts returns ≤ k facts,
none stale, none duplicated by family; a topic query returns different,
topic-relevant facts; persona chat sends the topic.

### Phase 2: One fact per thing (write path; no schema change)

**Goal:** fix §2.2 and D2.

1. **New `services/memory/app/services/canonical.py`:**
   - `ALIASES: dict[str, str]`, lowercase key → display name. Start with the
     ~150 most common: `js/javascript → JavaScript`, `ts → TypeScript`,
     `py/python3 → Python`, `golang → Go`, `postgres/postgresql/psql → PostgreSQL`,
     `nextjs/next.js/next → Next.js`, `node/nodejs/node.js → Node.js`,
     `react.js/reactjs → React`, `k8s → Kubernetes`, `gcp → Google Cloud`, …
   - `LANGUAGES`, `FRAMEWORKS` and `PRODUCTS` sets (merge `quality._KNOWN_TOOLS`
     into these; it currently mixes React and Docker together).
   - `canonical_name(value: str) -> str`: trim, collapse whitespace, strip
     version suffixes (`Python 3.12` → `Python`, `React 18` → `React`), apply
     aliases, else keep the user's casing.
   - `tech_kind(name) -> Literal["language", "framework", "product"] | None`.
2. **Single write entry point**, `services/memory/app/services/facts.py`
   `write_fact(conn, user_id, predicate, name, *, confidence, source, source_system, trace_chunk_id=None, observed_at=None, visibility=...)`.
   Route these through it:
   - `worker.chunk_processor` → currently `resolve_entity` + `upsert_assertion`
   - `findability.declare`, `declare_private`, `declare_for_review`
   - `persona_ingest.publish_persona_findability` (through `declare`)

   `write_fact` does: canonicalize → reclassify (D2) → resolve entity →
   family lookup → precedence → insert/update → history row.
3. **Families and precedence** (`taxonomy.PREDICATE_FAMILY` / `FAMILY_RANK`):

   | Family | Stronger → weaker |
   |---|---|
   | `tech` | `has_expertise_in` > `has_skill` > `uses_tool` > `is_learning` (when the object is tech) |
   | `work` | `is_building` > `is_creating` > `is_working_on` > `intends_to` > `is_learning` / interests (when the object is a project) |

   Rules:
   - Weaker arrives, stronger exists → bump the stronger fact's evidence
     (`observed_at` / `last_seen_at`), write no new row.
   - Stronger arrives, weaker exists → insert stronger, set the weaker's
     `valid_until = now()` with `assertion_history.change_reason = 'superseded'`.
   - **Exception:** never auto-supersede a fact the owner approved onto their
     card (`approved_at IS NOT NULL`). Keep both and let the existing UI family
     dedupe handle display. Changing what's public is the owner's call.
   - `dismissed_at` facts keep blocking re-adds, matched on canonical name
     across the family (today it's same predicate only).
   - `is_learning X` and `has_expertise_in X` together is legitimate when X is
     a *field* rather than a tool. Apply the tech-family rule only when
     `tech_kind(X)` is not `None`.
4. **`entities.resolve_entity`:** before the embedding step, exact-match
   `lower(canonical_name)` across the **compatible type group**
   (`skill_technical`, `skill_domain`, `concept_topic` for tech names;
   `project_*` for work). Embedding fallback keeps its per-type scope.
5. **`mcp_http.report_user_info`:** canonicalize and de-dupe values *across*
   fields before writing (JavaScript in `languages` and `tools` saves once,
   as `has_skill`).
6. **Stop sync double-writes** (persona-api):
   - Chunks whose `source_system ∈ {github, linkedin, twitter}` drop
     extracted `has_skill` / `uses_tool` / `has_expertise_in` /
     `is_working_on` / `is_building` (the sync already declared those
     directly). Implemented in `worker.chunk_processor` as a per-source
     predicate filter in taxonomy.
   - Fix the out-of-taxonomy predicates: Twitter `is_interested_in` →
     `is_learning`; LinkedIn `works_at` → `is_affiliated_with`,
     `lives_in` → `is_located_in`. Raise the `declare_fact` failure log from
     `debug` to `warning` so a rejected write is visible.
7. **UI:** add `uses_tool` and `is_learning` folding to
   `apps/cards-web/src/lib/memory-facts.ts` `PUBLIC_FAMILY` as a safety net
   for rows written before Phase 5 cleanup. Show `is_interested_in` rows (if
   any exist) under the `is_learning` label in
   `apps/persona-web/src/app/dashboard/settings/memory/page.tsx`.

**Done when:** reporting JavaScript as a language, a tool and a skill (three
calls, any order) leaves exactly one active `has_skill → JavaScript` fact; a
GitHub sync followed by its summary ingest adds no duplicate tech facts.

### Phase 3: Keep dependency noise out

**Goal:** fix §2.3 and D1.

1. **GitHub** (`services/persona-api/services/github_sync.py` `_derive_profile`):
   - `IGNORED_LANGUAGES = {HTML, CSS, SCSS, Sass, Less, Shell, PowerShell, Batchfile, Dockerfile, Makefile, CMake, Procfile, Jinja, Handlebars, Mustache, Roff, TeX}` (data/markup/config, not "what you code in").
   - Skip repos GitHub marks as `archived`. Already skips forks.
   - A language qualifies only if its share of the remaining bytes is
     **≥ 15% and it appears in ≥ 2 repos**, or ≥ 15% when the user has one
     qualifying repo (D1). Cap at 5 instead of 8.
   - Per-repo vendoring guard: ignore a repo's language entry if that one repo
     contributes > 80% of the language's total bytes *and* the language
     makes up < 5% of the user's other repos. That catches a committed SDK
     or a generated client.
2. **Extraction prompt** (`services/memory/app/services/extraction.py`), add a
   short "not the person's own" block:
   - Don't extract libraries, packages, or dependencies that only appear
     inside a dependency, an error message, a stack trace, a lockfile, or
     someone else's code.
   - `uses_tool` and `has_skill` need the person to say they use, know, or
     write it, not just that it's present in a project.
   - Don't extract `is_working_on` for a one-off task ("fix this bug",
     "rename this file"); only for a work stream that lasts days or weeks.
   - Add 4–6 negative examples to the prompt.
3. **Second-sighting rule for inferred tech:** extracted
   `has_skill` / `uses_tool` with `source = 'inferred'` and confidence < 0.9
   are written but **hidden from context and the review queue until seen in
   ≥ 2 distinct chunks** (Phase 4's `mention_count`). Until Phase 4 lands,
   count distinct `trace_chunk_id`s in `assertion_history`. Declared facts,
   and anything the user states, are visible immediately.
4. **`report_user_info`:** if one call has more than 5 tech values across
   `languages` / `frameworks` / `tools` / `skills`, keep the first 5 and
   return a note asking the agent to send only what the user said. Tighten
   the docstring with a short bad example ("don't send the repo's
   package.json").

**Done when:** a GitHub account with a Python project that vendors a JS
frontend build yields `has_skill → Python` and no HTML/CSS/JS-from-vendor
facts, and a chat turn quoting a webpack error adds no `uses_tool → webpack`.

### Phase 4: Freshness, done right (schema change, needs human OK)

**Goal:** fix §2.4, D3 and D4.

1. **Schema** (`services/memory/sql/schema.sql`, expand-only):
   ```sql
   ALTER TABLE assertions ADD COLUMN IF NOT EXISTS last_seen_at   timestamptz;
   ALTER TABLE assertions ADD COLUMN IF NOT EXISTS mention_count  int NOT NULL DEFAULT 1;
   ALTER TABLE assertions ADD COLUMN IF NOT EXISTS base_confidence double precision;
   UPDATE assertions SET last_seen_at = coalesce(observed_at, extracted_at)
    WHERE last_seen_at IS NULL;
   UPDATE assertions SET base_confidence = confidence WHERE base_confidence IS NULL;
   CREATE INDEX IF NOT EXISTS assertions_user_active_seen
     ON assertions (user_id, last_seen_at DESC) WHERE valid_until IS NULL;
   ```
   Rehearse on a throwaway Postgres with a prod-shaped dump before it goes
   anywhere near memory's prod DB.
2. **`write_fact`:** on new evidence set `last_seen_at = greatest(last_seen_at, observed_at)`,
   `mention_count += 1` (only when `trace_chunk_id` is new, so re-processing
   doesn't double-count), and `base_confidence = bayesian_update(...)`.
3. **Decay, fixed** (`decay.py`): compute from the evidence, not from
   yesterday's result:
   `confidence = base_confidence × 0.5 ^ (days_since(last_seen_at) / halflife)`.
   This is idempotent, so running it twice in a night changes nothing.
   **Stop auto-archiving** time-bound predicates (`STALE_AFTER_DAYS` keys).
   Being stale is now a read-time state (D3: hidden, still searchable). Keep
   archiving below 0.1 only for predicates that aren't time-bound, such as
   beliefs and feelings.
4. **Ranking** (Phase 1) switches from `observed_at` to `last_seen_at` and
   uses `mention_count` for the second-sighting rule.
5. **Confirm the cron runs:** add the decay summary to the existing
   `/health` or a log-based alert. If `decay_cron` hasn't run in 48 hours,
   say so.

**Done when:** a `working on` fact last seen 31 days ago is absent from
no-topic context, present with `stale: true` for a matching topic, and still
`valid_until IS NULL` in the DB.

### Phase 5: Clean up existing data (prod data, needs human OK)

1. **`services/memory/scripts/dedupe_memory.py`**:
   - `--dry-run` (default): for each user (or `--user <id>`), compute what
     Phases 2–3 *would* have done to the existing active facts:
     - canonical-name merges
     - family supersedes (respecting the approved-fact exception)
     - `uses_tool → has_skill` reclassification
     - GitHub-noise languages (ignore list) to archive
   - Prints a per-user report and writes `dedupe_report.json`.
   - `--apply`: performs the plan in one transaction per user, archiving
     (`valid_until = now()`, `change_reason = 'cleanup_merge' | 'cleanup_noise'`),
     **never deleting**. Undo is a single `UPDATE … SET valid_until = NULL`
     on those history-tagged rows, and the script ships with `--undo <run_id>`.
2. Order: run on a restored copy → review the report with a human → apply to
   prod with the human's go-ahead → recompute match embeddings
   (`python -m app.jobs recompute`).

---

## 6. Testing

Per AGENTS.md §5, run before and after each phase:

- `cd services/memory && uv run pytest -q -m "not integration"`: baseline 9
  known failures, report only new ones.
- `cd services/persona-api && pytest -q`: baseline 5.
- `apps/cards-web`: `npm run lint && npx tsc --noEmit` and
  `src/lib/memory-facts.test.ts` for the family-folding change.

New tests:

| Phase | Test |
|---|---|
| 1 | Unit: score/stale computation (pure function). Integration: `rank_context` against the eval fixture; topic changes results; no family duplicates; stale excluded without topic, included with matching topic |
| 2 | Unit: `canonical_name`, `tech_kind`, aliases incl. versions. Integration: `write_fact` precedence matrix (each pair, both orders); approved-fact exception; dismissed blocks across family; `report_user_info` cross-field dedupe |
| 3 | Unit: `_derive_profile` with ignore list, 15% / 2-repo rule, vendoring guard. Extraction prompt: fixture turns run through `mock_llm` plus a small recorded-response set |
| 4 | Integration: decay idempotent (run twice = same values); time-bound facts never archived; `mention_count` not double-counted on re-processing |
| 5 | Integration: dry-run makes no writes; apply then undo restores the exact prior active set |

---

## 7. Rollout and flags

| Flag (`services/memory/app/config.py`) | Gates | Default on merge |
|---|---|---|
| `feature_ranked_context` | Phase 1 ranking in `/me/context` and `get_my_context` | on in dev, off in prod until the eval passes |
| `feature_fact_families` | Phase 2 `write_fact` precedence and reclassification | on in dev |
| `feature_strict_tech` | Phase 3 extraction prompt and second-sighting rule | on in dev |
| `feature_freshness_v2` | Phase 4 decay and `last_seen_at` ranking | off until the schema is applied |

Phase 3's GitHub changes live in persona-api and ship with persona's normal
`dev` auto-deploy. They only affect *new* syncs; existing noise is Phase 5's
job.

Reminder (AGENTS.md §3): cards and memory are not yet auto-deployed from
this monorepo, so merging to `dev` doesn't reach the live memory service.
Coordinate the memory deploy with a maintainer.

---

## 8. Risks and open questions

- **Over-merging.** "Go" (language) vs "Go" (the game), "Swift" vs "Taylor
  Swift". The alias map only applies inside the `tech` family, and
  `tech_kind` needs an exact alias hit, not a substring.
- **Hiding something the user still cares about.** Stale facts are never
  deleted and come back by topic (D3). If users complain, add a
  "keep this current" pin (`pinned_at`) later. Out of scope here.
- **Approved card facts.** Phase 2 deliberately doesn't change what's public.
  If a card shows both "Skilled in Python" and "Expert in Python", the UI
  family fold hides one; the owner can dismiss the other.
- **`RELATED_MIN` tuning.** 0.45 is a guess for `text-embedding-3-small`-style
  vectors on short entity names. The Phase 1 eval set decides the real value.
- **Open:** should `is_learning` count as "interested in" for display
  everywhere (persona-web labels it "Learning"; Twitter meant
  "Interested in")? This plan maps both to `is_learning`. Rename the label if
  "Interested in" reads better.
- **Open:** does `decay_cron` run in prod today? Check before Phase 4 so the
  before/after comparison is honest.
