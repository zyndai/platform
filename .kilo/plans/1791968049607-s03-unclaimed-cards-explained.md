# S03 — Unclaimed cards: what it means + verification checklist

**Mode:** explain + verify (no implementation). Known ticket deviations are flagged, not treated as hard failures.

**Verdict from code audit:** S03 is largely shipped. `FEATURE_S03_UNCLAIMED_TIERING` defaults **true**. Core AC (public to people / quiet to agents / claim / not-me / no `owner_email` in public JSON) is implemented with unit + Playwright coverage.

---

## What this feature means (plain English)

Zynd scrapes/builds profile cards for people who never signed up. Those cards grow the directory, but they create impersonation and consent risk if agents can chat them, index them, or pull contact data.

**Policy in one line:** unclaimed cards stay **visible to humans** on the site, but stay **quiet to agents and search engines**, and every such page is a claim / remove funnel.

| Surface | Unclaimed (`owner_email` IS NULL) | Claimed |
|---|---|---|
| Directory / find / search UI | Shown, labelled **Unclaimed** | Shown |
| Profile page | Trimmed: no chat, booking, PDF resume, memory tile; **Is this you?** banner | Full |
| Search engines | `noindex, follow` | Indexed |
| `llms.txt`, sitemap | Excluded | Included |
| `/ask`, `/v1/agents/*`, `data.json`, public MCP (S11) | Excluded by default; `include_unclaimed=true` may return with `claimed:false` and no contact | Included |
| Claim | **Claim with LinkedIn** — signed-in LinkedIn must match card LinkedIn URL | — |
| Remove | **Not me** → hide from agent/search immediately + `takedown_requests` row | Owner |

**Claimed definition:** `claimed` = `owner_email IS NOT NULL` (generated stored column on `cards` schema; Python fallback on legacy DBs). Public APIs expose only the boolean — never `owner_email`.

---

## How it works in this repo

### Data

| Piece | Path |
|---|---|
| `claimed` generated column + index | `packages/db/cards/migrations/0006_claimed_generated_column.sql` |
| `takedown_requests` + alias | `0004_takedown_requests_and_alias.sql` |
| Search RPCs `include_unclaimed` (default false) | `0005_unclaimed_search_functions.sql`, `0007_search_use_claimed.sql` |
| Drizzle mirrors | `packages/db/cards/schema/cards.ts`, `takedown_requests.ts` |

### Backend (`services/cards-api`)

| Piece | Path |
|---|---|
| Flag (default true) | `config.py` → `FEATURE_S03_UNCLAIMED_TIERING` |
| Public payload strips email | `services/cards.py` → `_public_card_payload`, `_claimed_from_row` |
| LinkedIn claim | `POST /cards/by-handle/{handle}/claim` → `claim_card_by_owner` |
| Legacy claim-token | `PATCH …` + `X-Claim-Token` / `can_claim` |
| Not-me | `POST …/report-not-me` → `request_takedown` (`status=takedown_requested`) |
| Agent search defaults | `api/ask.py`, `api/agents.py` — `include_unclaimed` default false when flag on |
| Chat gate | `api/chat.py` — 403 if unclaimed |
| Tests | `tests/test_unclaimed_tiering.py` |

### Web (`apps/cards-web`)

| Piece | Path |
|---|---|
| `claimed` type + fail-closed helper | `src/lib/cards.ts` → `cardIsClaimed` |
| Profile trim + robots | `src/app/(site)/p/[handle]/page.tsx` |
| Claim / Not-me UI | `claim-banner.tsx` |
| Directory chip | `directory/page.tsx` |
| Human search includes unclaimed | `find/page.tsx`, `search/page.tsx` pass `include_unclaimed=true` |
| Agent discovery exclude | `llms.txt/route.ts`, `llms-full.txt/route.ts`, `sitemap.ts` |
| `data.json` quiet stub | `p/[handle]/data.json/route.ts` → 410-style `{claimed:false}` |
| Playwright | `tests/smoke.spec.ts` — banner + no chat |

There is **no** `NEXT_PUBLIC_FEATURE_S03_*`. Web trusts API `claimed` + caller-side `include_unclaimed`. Rollback for agent exclusion is API flag off.

---

## Acceptance criteria vs code

| AC | Status | Evidence |
|---|---|---|
| Unclaimed absent from `llms.txt`, sitemap, default `/ask`, quiet `data.json`; visible in directory with chip | **Met** | Web filters + ask/agents default exclude |
| Profile: `noindex,follow`, no chat/booking/PDF/memory; claim banner | **Met** | `page.tsx` + smoke test |
| Matching LinkedIn claims; mismatch 403; then fully visible/indexed | **Met (code)** | `claim_card_by_owner` + tests; live LinkedIn E2E needs human |
| Not-me removes from agent/search + creates takedown row | **Met** | `request_takedown` sets `takedown_requested` |
| `owner_email` never in public responses | **Met** | `_public_card_payload` + tests |

---

## Known deviations (flag, do not fail checklist)

Document these; do not block “S03 explained/verified” on them unless product reopens the ticket.

1. **`GET /cards` and `GET /cards?q=` still return unclaimed** — human list/search endpoints; agents using them bypass `/ask` tiering. Ticket expected agent surfaces quiet; these are a remaining leak path.
2. **`GET /cards/by-handle/{h}/view` always 404s unclaimed** — no `FEATURE_S03` rollback path (unlike `/ask`).
3. **`claim_card_by_owner` sets `owner_email` + clears token but does not set `owner_user_id`** — token/`update_card` path can set `owner_user_id` for aafo; LinkedIn claim path does not.
4. **Prod migration state** — AGENTS.md: `packages/db` may not be fully applied on aafo; xmfj/`public` may lack `claimed` / `takedown_requests`. Code has select fallbacks.
5. **Legal takedown copy** — ticket required legal sign-off; not verifiable from code.
6. **No in-repo admin restore/delete API** for `takedown_requests` (`dismissed` / `actioned`) — Mattermost notify + manual review.
7. **Empty-string `owner_email`** — SQL generated column is `IS NOT NULL`; Python also treats whitespace as unclaimed. Edge mismatch if empty string stored.

---

## Verification checklist

Run against a known unclaimed handle `U` and claimed handle `C` (fixtures: Playwright `unclaimed` / `claimed`, or live handles).

### A. Automated (local)

```bash
cd services/cards-api && pytest -q tests/test_unclaimed_tiering.py
cd apps/cards-web && npx playwright test tests/smoke.spec.ts -g "unclaimed|claimed profile"
```

Pass if: claim match/mismatch, takedown insert, no `owner_email` in public JSON, `/ask` + `/v1/agents/search` default-exclude, flag-off restores include, smoke shows banner + no `.pf-chat-fab` on unclaimed.

### B. Agent-quiet surfaces (manual or curl)

| Check | Expect for `U` | Expect for `C` |
|---|---|---|
| `GET /ask?q=…` (no flag) | Not in results | May appear |
| `GET /ask?q=…&include_unclaimed=true` | In results with `claimed:false`, no contact/email | `claimed:true` |
| `GET /v1/agents/search?q=…` | Absent by default | Present |
| `GET /v1/agents/{id}` for unclaimed | 404 when flag on | 200 |
| `POST /v1/chat/{U}` | 403 | 200 path (auth/rules permitting) |
| `GET /p/{U}/data.json` | Quiet stub / not full facts | Full card JSON |
| `/llms.txt`, `/sitemap.xml` | No `/p/{U}` | Includes `/p/{C}` |

### C. Human-visible surfaces

| Check | Expect for `U` |
|---|---|
| `/directory`, `/find`, `/search` | Visible + **Unclaimed** chip / label |
| `/p/{U}` meta robots | `noindex, follow` |
| Chat FAB / HeroAsk / booking / PDF / memory | Absent |
| Claim banner | “Is this you?” + Claim with LinkedIn + Not me |

### D. Claim + Not-me (needs LinkedIn session)

1. Sign in with LinkedIn that **matches** card `identity.links.linkedin` → `POST …/claim` → 200; card becomes `claimed:true`; appears in sitemap/ask defaults after refresh.
2. Sign in with **different** LinkedIn → 403 helpful mismatch message; card stays unclaimed.
3. Missing LinkedIn on card → refuse with “no LinkedIn” style message; fallback claim-token or manual.
4. **Not me** → `POST …/report-not-me` → `{removed:true}`; card `status=takedown_requested`; row in `cards.takedown_requests`; gone from published list / agent search.

### E. Privacy scan

For every public response in B/C (and `GET /cards`, `GET /cards/by-handle/{h}`): assert JSON has **no** `owner_email` key. Prefer grepping response bodies; unit tests already cover by-handle + list.

### F. Flag rollback smoke

Set `FEATURE_S03_UNCLAIMED_TIERING=false` on cards-api → `/ask` without flag behaves as include-all. Note: `/view` and web trimming are **not** fully rolled back by this flag alone (known deviation).

### G. Env / migration sanity (ops)

Confirm on the live cards DB (ask a human before any SQL):

- Column `cards.agent_profile_cards.claimed` exists (or fallback path in use).
- Functions `match_cards` / `search_cards_fts` accept `include_unclaimed`.
- Table `cards.takedown_requests` exists.
- Flag present in cards-api env (default true is fine).

---

## Out of scope for this plan

- Implementing gap closure for `GET /cards` leak, `owner_user_id` on LinkedIn claim, or `/view` flag wiring (separate gap-closure plan if product wants it).
- S10 dedupe/merge, S11 MCP beyond “must honour claimed” (already does via cards-api).
- Legal copy rewrite, Google Search Console removals, admin review UI.
- Applying migrations to prod without human say-so (AGENTS.md §6).

---

## Suggested follow-ups (optional, not this plan)

1. Gate `GET /cards` / `search_cards` with the same `include_unclaimed` default as `/ask`.
2. Set `owner_user_id` in `claim_card_by_owner` when principal is aafo.
3. Align `/view` with `FEATURE_S03` for consistent rollback.
4. Legal review of banner / Not-me copy + takedown SLA.
5. Confirm aafo migration apply status for 0004–0007.
