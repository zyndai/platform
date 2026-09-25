# Zynd — Google + LinkedIn Auth Compliance & Data Controls

**Entity:** Zynd AI Inc (Delaware)
**Scope:** This repo only (`persona.zynd.ai` — `backend/` + `webapp/`). The ZYND memory layer (`api.zynd.ai`) is a separate deployment and is **out of scope**.
**Last updated:** 2026-08-22

---

## 1. Objective

Reach a credible, unified compliance baseline covering **both Google OAuth and LinkedIn OAuth**, so that a new, isolated LinkedIn Developer App can request **Member Data Portability** without being rejected for missing consent / storage / deletion / disclosure infrastructure.

Key LinkedIn facts driving this work:

- Member Data Portability is **not a paid product** (LinkedIn "Costs & Fees" §8.2 does not apply; each party bears its own costs).
- It must live on its **own app** — not the current `Zynd Persona` app (which has Share on LinkedIn, Sign-In with LinkedIn, Advertising API request).
- Access is **member-authorized** and region-scoped (DMA program → EU/EEA/CH members).
- LinkedIn API terms require LinkedIn-sourced data to be **identifiable, segregable, and selectively deletable**, deleted on member request / account closure, and **never mixed with scraped/crawled data** (e.g. Apify).
- Storage is allowed with member consent + legal basis.

## 2. Current state (audited 2026-08-22)

### Already present

| Capability | Location |
|---|---|
| Privacy Policy page (Google-only) | `webapp/src/app/privacy/page.tsx` |
| Terms of Service page (Google-only) | `webapp/src/app/terms/page.tsx` |
| Full account purge (delete everything) | UI `webapp/src/components/settings/DeleteAccountModal.tsx` + `webapp/src/app/dashboard/settings/you/page.tsx` → `DELETE /api/persona/{id}/account` → `backend/agent/persona_manager.py:422` `purge_user_account` |
| Google disconnect | `webapp/src/app/dashboard/settings/accounts/page.tsx` → `DELETE /api/connections/google` (`backend/api/connections.py:54`) |
| LinkedIn disconnect (wipes scrape + token) | `DELETE /api/linkedin/me` (`backend/api/linkedin.py:130`) + `DELETE /api/connections/linkedin` |
| OAuth flows | `backend/api/oauth_routes.py` — Google `:285`, LinkedIn `:98` |
| Segregated token storage | `api_tokens` table (`backend/services/token_store.py`) |
| Segregated LinkedIn data | `linkedin_profiles` table (`db/migrations/0000_baseline/migration.sql:224`) |
| RLS on all sensitive tables | `db/sql/policies.sql` |
| Privacy audit log (group discovery) | `persona_group_discovery_audit` table |

### Gaps

1. Legal pages are **Google-only** — no LinkedIn disclosure anywhere.
2. Terms governing law = **California** (`webapp/src/app/terms/page.tsx:247`) — entity is Delaware.
3. No `/data-deletion`, `/security`, `/contact` pages; no cookie/analytics note (GA `G-1L9YDBKGRT` is loaded).
4. No granular **"Delete [provider] data"** (keep-account delete) — only full disconnect.
5. `purge_user_account` does **not** explicitly delete `linkedin_profiles` / `telegram_links` / `telegram_chat_history` (relies on `ON DELETE CASCADE` from `auth.users`). No deletion audit event.
6. No **data export** ("download my data") and no **retention policy**.
7. OAuth consent does not explicitly disclose storage/processing (relies on provider consent screens only).
8. LinkedIn data is currently **Apify-scraped** (`backend/services/linkedin_scraper.py`) — no `source` lineage; cannot be mixed with future Portability data.

---

## 3. How to test (baseline)

- **Backend tests:** `cd backend && python -m pytest tests/ -q` (no pytest config file; `conftest.py` injects `backend/` into `sys.path`).
- **Webapp build (REQUIRED before deploy):** `cd webapp && npm run build`.
- **Webapp lint:** `cd webapp && npm run lint`.
- **Deploy flow (dev → prod):** see `AGENTS.md`. `npm run build` is mandatory after every webapp change; backend needs `pip install -r requirements.txt` only if deps changed.

Run backend tests **before** any change, then again after each change group.

> **Known baseline (2026-08-22):** `backend/tests/test_linkedin_people_search.py::test_maps_real_actor_output_shape` fails (`count == 1` expected, got `0`). This is **pre-existing and unrelated** to this plan — the scraper mapping changed but the test wasn't updated. Treat "153 passed, 1 failed (this one)" as the green baseline. Do not fix it as part of this plan unless separately approved.

---

## 4. Change catalog

Legend:
- **Type** — `additive` (new file/route/field, no existing behavior changed) vs `modifies-existing` (changes current output/behavior → **requires approval**).
- **🔒 Approval** — item changes an existing workflow; do not implement until explicitly approved.

---

### Group A — Public legal pages (Phase 1)

#### A1. Add "LinkedIn Data" section to Privacy Policy — `modifies-existing` 🔒
- **File:** `webapp/src/app/privacy/page.tsx`
- **Change:** Insert a new `<Section>` (after the existing Google scopes section) titled **"LinkedIn Data"** covering: what Zynd accesses (public profile fields, posts — as authorized), the OAuth scopes (`openid profile email w_member_social`), purpose (persona context / profile enrichment), storage (encrypted, segregated `linkedin_profiles` table), consent basis, deletion mechanism, and retention.
- **Also:** add a **"Data Retention"** section covering both providers; update entity string `ZyndAI` → **"Zynd AI Inc"** in the intro; update "Last updated".
- **Approval:** yes — changes existing published page text.
- **Test:** `npm run build`; visually verify `/privacy`; confirm existing Google sections still render unchanged.

#### A2. Add "LinkedIn API Services" section to Terms + fix governing law — `modifies-existing` 🔒
- **File:** `webapp/src/app/terms/page.tsx`
- **Change:** Add a LinkedIn section mirroring the existing Google API section (scopes + limited-use language). Change §11 governing law from **"State of California"** → **"State of Delaware"**. Entity → **"Zynd AI Inc"**. Update "Last updated".
- **Approval:** yes — changes existing Terms (governing-law change is a legal decision; confirm before shipping).
- **Test:** `npm run build`; verify `/terms`.

#### A3. Create `/data-deletion` page — `additive`
- **File (new):** `webapp/src/app/data-deletion/page.tsx`
- **Change:** Public page describing how to delete data for **both** providers: disconnect steps, "delete provider data" (in-app), full account deletion, retention window, and contact email.
- **Approval:** no (new page).
- **Test:** `npm run build`; visit `/data-deletion`.

#### A4. Create `/security` page — `additive`
- **File (new):** `webapp/src/app/security/page.tsx`
- **Change:** Describe encryption at rest (Supabase), RLS, OAuth token handling, and scope minimization for both providers.
- **Approval:** no.
- **Test:** `npm run build`; visit `/security`.

#### A5. Create `/contact` page — `additive`
- **File (new):** `webapp/src/app/contact/page.tsx`
- **Change:** Contact page listing support + privacy/DPO contact email (see **Decision D1**).
- **Approval:** no.
- **Test:** `npm run build`; visit `/contact`.

#### A6. Cookie / analytics note — `additive`
- **File:** `webapp/src/app/privacy/page.tsx` (new short section) or a small `/cookies` page.
- **Change:** Disclose GA `G-1L9YDBKGRT` usage. Minimal note in Privacy Policy is sufficient for now.
- **Approval:** no (additive section).
- **Test:** `npm run build`.

#### A7. Wire new pages into nav/footers + crawler metadata — `modifies-existing` 🔒
- **Files:**
  - `webapp/src/app/LandingClientWrapper.tsx` (footer ~line 230)
  - `webapp/src/app/privacy/page.tsx` (footer ~line 216)
  - `webapp/src/app/terms/page.tsx` (footer ~line 259)
  - `webapp/src/app/llms.txt/route.ts` (`STATIC_PAGES` array)
  - `docs/seo-plan.md` (sitemap static list) and, if a real `webapp/public/sitemap.xml` exists, add the new paths.
- **Change:** Add footer links for `/data-deletion`, `/security`, `/contact` (and `/cookies` if created). Add them to `llms.txt` static list.
- **Approval:** yes — edits existing footers/nav (low visual risk, but touches published surfaces).
- **Test:** `npm run build`; click each new footer link on `/`, `/terms`, `/privacy`.

---

### Group B — Backend data controls (Phase 2)

#### B1. Granular "delete LinkedIn data" endpoint — `additive`
- **File:** `backend/api/linkedin.py`
- **Change:** Add `DELETE /api/linkedin/data` that deletes the `linkedin_profiles` row **and** the `api_tokens` `linkedin` row, while **keeping the account/persona** (distinct from full disconnect — functionally the same DB writes as today's disconnect, but exposed as an explicit "delete my LinkedIn data" action for compliance).
- **Approval:** no (additive route; does not alter existing `DELETE /me`).
- **Test:** add `backend/tests/test_linkedin_delete_data.py` — mock Supabase, assert both tables hit with `eq("user_id", ...)`. Run `python -m pytest tests/test_linkedin_delete_data.py`.

#### B2. Generalize provider data deletion — `additive`
- **File:** `backend/api/connections.py`
- **Change:** Add `DELETE /api/connections/{provider}/data` that deletes provider tokens (and for `linkedin`, the profile data) without removing the account. Keep the existing `DELETE /api/connections/{provider}` (disconnect) unchanged.
- **Approval:** no (additive route).
- **Test:** extend `backend/tests/` with a connections data-delete test (mirror existing disconnect tests if any).

#### B3. Harden `purge_user_account` to explicitly delete provider data + audit — `modifies-existing` 🔒
- **File:** `backend/agent/persona_manager.py` (`purge_user_account`, line 422)
- **Change:** Add explicit `linkedin_profiles`, `telegram_links`, `telegram_chat_history` deletes **before** the `auth.users` delete (defence-in-depth; today these rely on FK cascade and would linger if the final step fails). Append a `data_deleted` audit entry (reuse `persona_group_audit_events` pattern or a lightweight audit table).
- **Approval:** yes — modifies the account-deletion path (a production-critical workflow).
- **Test:** add `backend/tests/test_purge_account.py` — mock Supabase, assert each table is deleted; assert behavior is unchanged when `auth.users` delete succeeds.
- **Note:** do **not** change the existing cascade semantics; this is strictly additive hardening.

#### B4. Deletion audit logging — `additive`
- **File:** `backend/services/` (small helper) or reuse `persona_group_audit_events`.
- **Change:** Record provider-data deletions (user_id, provider, timestamp, actor=user).
- **Approval:** no.
- **Test:** unit-test the helper; verify no audit row is written for failed deletes.

#### B5. Data export endpoint — `additive`
- **File:** `backend/api/persona.py` (new `GET /api/persona/{user_id}/export`)
- **Change:** Return a JSON bundle of the user's own data (persona profile, brief, chat history, connected-provider list). Read-only; does not expose tokens.
- **Approval:** no (additive, read-only).
- **Test:** `backend/tests/test_persona_export.py` — assert response shape + no token fields.

---

### Group C — Frontend data controls (Phase 2)

#### C1. "Delete data" buttons on Accounts page — `modifies-existing` 🔒
- **File:** `webapp/src/app/dashboard/settings/accounts/page.tsx`
- **Change:** For LinkedIn **and** Google cards, add a secondary **"Delete data"** action (calls B1/B2) distinct from the existing **"Disconnect"** (which already exists). Surface the deletion result via the existing `oauthFlash`/notice pattern. Add an inline confirm note describing what is removed.
- **Approval:** yes — adds controls to an existing, working settings screen (should not alter existing Disconnect/Connect behavior).
- **Test:** `npm run build`; manual: connect → delete data → confirm the card returns to "Not connected" state and that Disconnect/Connect still work.

#### C2. "Download my data" button — `additive`
- **File:** `webapp/src/app/dashboard/settings/you/page.tsx` (Account card) + `webapp/src/components/settings/` if a modal is needed.
- **Change:** Add a "Download my data" button that fetches B5 and triggers a client-side download.
- **Approval:** no.
- **Test:** `npm run build`; manual download + JSON validity.

#### C3. OAuth consent disclosure text — `modifies-existing` 🔒
- **File:** `webapp/src/app/dashboard/settings/accounts/page.tsx`
- **Change:** Add a one-line disclosure near the LinkedIn/Google connect buttons, e.g. *"By connecting, you authorize Zynd to store and process the data described in our Privacy Policy."*
- **Approval:** yes — changes existing connect-flow copy.
- **Test:** `npm run build`; visual check on both cards.

---

### Group D — Data lineage + migration (Phase 3)

#### D1. Add `source` field to `linkedin_profiles` — `modifies-existing` 🔒 (DB migration)
- **File:** new migration `db/migrations/XXXX_add_linkedin_source.sql` (or `db/sql/` patch, following existing convention — see `backend/db/patch_*.sql`)
- **Change:** `ALTER TABLE public.linkedin_profiles ADD COLUMN source TEXT NOT NULL DEFAULT 'apify_scrape';` with a CHECK (`source IN ('apify_scrape','linkedin_api','portability')`). Backfill existing rows to `'apify_scrape'`.
- **Approval:** yes — schema change on a live table (requires running the migration on the shared Supabase project; both prod + dev copies).
- **Test:** run the migration via `psql "$DIRECT_URL" -f <file>` (see `webapp/package.json` `db:policies` for the connection pattern); verify default + CHECK enforcement; ensure existing scrape upserts still succeed.

#### D2. Write `source` on scrape vs OIDC upsert — `modifies-existing` 🔒
- **File:** `backend/services/linkedin_scraper.py` (scrape upsert) and `backend/api/oauth_routes.py` (OIDC placeholder upsert, ~line 199)
- **Change:** Set `source='apify_scrape'` on scrape writes and `source='linkedin_api'` on OIDC placeholder writes. Any future Portability import MUST write `source='portability'` to a **separate table** (never `linkedin_profiles`).
- **Approval:** yes — modifies existing write paths (must not alter current scrape behavior; only add the column value).
- **Test:** update `backend/tests/test_linkedin_scraper_search_payload.py` / `test_linkedin_post_fields.py` if they assert on the upsert payload; add assertion that `source` is set.

#### D3. Document separation rule — `additive`
- **File:** `docs/` note or this file's Phase 3 section.
- **Change:** State that Portability-derived connection data must never be co-mingled with `apify_scrape` data.
- **Approval:** no.

---

### Group E — LinkedIn submission (Phase 4)

#### E1. Create isolated LinkedIn Developer App — `external` (no code)
- New app with **only** Member Data Portability product. Register with **Zynd AI Inc** (Delaware) details, privacy policy URL, contact email.

#### E2. Verify Portability schema includes 1st-degree connections — `external` (no code)
- Confirm the 2026 Portability API actually exposes connections before building any import feature.

---

## 5. Regression risk matrix

| Change | Existing flow touched | Blast radius | Mitigation |
|---|---|---|---|
| A1/A2 legal copy | `/privacy`, `/terms` | Low (static) | build + visual |
| A7 footer/nav links | `/`, `/terms`, `/privacy`, `llms.txt` | Low | build + click-through |
| B3 purge hardening | `DELETE /api/persona/{id}/account` | **High** (account deletion) | additive-only, explicit test |
| B1/B2 new delete endpoints | none (new routes) | Low | new tests |
| C1 delete buttons | Accounts page | Medium (existing UI) | keep Disconnect/Connect untouched |
| C3 consent copy | connect flow | Low (text only) | build + visual |
| D1/D2 source field | scrape + OIDC upsert, schema | **High** (live table + write paths) | backfill default, keep upserts compatible |

---

## 6. Implementation order (safe sequencing)

1. **Group A** (legal pages) — static, low risk.
2. **Group D1/D2** (source field) — schema first so future writes are tagged. *(needs approval)*
3. **Group B1/B2 + B4/B5** (new endpoints) — additive backend.
4. **Group C1/C2/C3** (frontend controls) — after backend endpoints exist.
5. **Group B3** (purge hardening) — last among backend changes, with full test. *(needs approval)*
6. **Group E** (external LinkedIn steps) — after all code is live + `npm run build` on dev/prod.

## 7. Deploy checklist

- [ ] `cd backend && python -m pytest tests/ -q` green.
- [ ] `cd webapp && npm run build` green, `npm run lint` green.
- [ ] Run D1 migration on Supabase (prod project shared by both copies).
- [ ] Deploy **dev** copy first (`git pull`, restart `api-dev web-dev`, build webapp), smoke-test.
- [ ] Deploy **prod** copy (`git pull`, restart `api web`, build webapp), smoke-test.
- [ ] Verify new pages reachable at `persona.zynd.ai/data-deletion`, `/security`, `/contact`.

---

## 8. Resolved decisions

- **D1 (contact email):** `contact@zynd.ai` (privacy/DPO + all "Contact Us" sections).
- **D2 (entity string):** `Zynd AI Inc` — registered address: **Zynd AI Inc, 8 The Green STE A, Dover, DE 19901**.
- **D3 (governing law):** **Delaware** (Terms §11).
- **D4 (cookie policy):** a note inside the Privacy Policy (A6), not a separate page.

---

## 9. Permission summary

The following items change **existing behavior/workflows** and will **not** be implemented until you approve each:

| ID | What it changes | Why approval is needed |
|---|---|---|
| A1 | Privacy Policy content | published page text |
| A2 | Terms content + governing law | legal text + jurisdiction |
| A7 | footers / llms.txt | published surfaces |
| B3 | account-deletion path | production-critical workflow |
| C1 | Accounts settings UI | existing working screen |
| C3 | connect-flow copy | existing flow text |
| D1 | `linkedin_profiles` schema | live table migration |
| D2 | scrape/OIDC write paths | existing write behavior |

All other items are **additive** (new pages, new routes, new endpoints, new field default) and are safe to implement without touching existing behavior.
