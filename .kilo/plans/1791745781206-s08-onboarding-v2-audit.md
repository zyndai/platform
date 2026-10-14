# S08 — Onboarding v2 audit (status only)

**Verdict: PARTIAL (~55–65%). Not complete against acceptance criteria.**  
Confidence: **high** (key files read; zero `FEATURE_S08` hits; `ALLOWED_EVENTS` enumerated; create page still 2057-line monolith).

Shipped in `562ea53` (“S08 onboarding v2”) alongside other cards work. This doc is an audit — **no implementation tasks**. Switch to a Code agent if/when gaps should be closed.

---

## Acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | LinkedIn → live card &lt;~60s **same screen**; **no separate 5-step quiz** | **Fail / partial** | `QUESTIONS` still has **6** items (`create/page.tsx` ~53–102). Smoke test skips all six (`smoke.spec.ts` ~74–78). During `working`, UI shows chip status + progress ring — **no live scraped card preview**. Card appears at **review**, after questions. |
| 2 | Existing card never reaches “Add profiles”; unclaimed lookalike → claim | **Mostly pass** | Signed-in + `existingHandle`: “You already have a card” / Edit / View; URL form gated (`~1198–1240`). Claim poll → `GET /onboard/claim-candidates` (`~576–588`). Landing: `useMyCard` → “View my profile” (not literal “Open my card”; same intent). |
| 3 | No login prompt after publish for creator | **Mostly pass** | Auth-before-build nudge (`~677–682`, `~1271–1288`). Signed-in publish → `/p/[handle]/welcome` (`~828–832`). Anonymous path still offers optional “Claim with LinkedIn” (not a hard wall). |
| 4 | First-win: **working** “Ask your card” answer + Connect / Share / Looking-for | **Partial** | `/p/[handle]/welcome` steps Ask / Looking / Share / Connect exist. Ask only opens chat via `zynd:open-profile-chat` — **no pre-seeded demo Q&A / visible answer on load**. Chat widget mounts when claimed. |
| 5 | Funnel events; drop-off per step from `card_events` | **Fail** | API emits `create_start` + `create_publish` only. `ALLOWED_EVENTS` has **no** `question_answered` / `first_win_*` (`services/events.py` ~21–33). Cannot compute question-step or first-win drop-off. |
| 6 | Mobile 390px, no horizontal scroll | **Likely CSS-done, unproven** | `zc-theme.ts` 640px breakpoints, overflow-wrap, flex-wrap. **No** Playwright `viewport: 390` test. |

---

## PR plan checklist

| Item | Status |
|---|---|
| **PR 0:** split `create/page.tsx` into step components + state hook; Playwright smoke first | **Not done.** Only `zc-theme.ts` extracted. No `UrlStep`, `LiveCardPreview`, `InlineQuestion`, `ClaimCandidates`, `FirstWin`, `useOnboardingState`. Page still **2057** lines. Smoke happy path **exists** (URL → auth nudge → skip questions → review). |
| Auth-before-build + claim-first + signed-in CTA | **Done** (behavior). |
| Live-preview single screen + inline questions | **Partial.** Questions concurrent with scrape; **no** live card of scraped content on the same screen. |
| First-win screen + progress ring + events | Screen + ring **done**; first-win / question funnel events **missing**. |
| Optional GitHub sign-in | **Not started / product conflict.** `useAuth.tsx`: “LinkedIn-only login (D12 — Google, GitHub and the email magic link are removed).” Ticket optional; D12 says no. |
| `FEATURE_S08_ONBOARDING_V2` + % cookie rollout; keep v1 until metrics | **Absent.** Repo has `FEATURE_S03_*`, `FEATURE_S04_EVENTS`, `FEATURE_S06_CARDVIEW` only. New flow is **always on**. Rollback = git revert / redeploy. |

---

## What exists (inventory)

### Web
| Path | Role |
|---|---|
| `apps/cards-web/src/app/(site)/create/page.tsx` | Full onboarding monolith (S08 markers throughout) |
| `apps/cards-web/src/app/(site)/create/zc-theme.ts` | Theme / mobile CSS extract (“PR0-ish”) |
| `apps/cards-web/src/app/(site)/p/[handle]/welcome/page.tsx` | First-win steps + mounts `ProfileChatWidget` |
| `apps/cards-web/src/app/(site)/p/[handle]/welcome/welcome-actions.tsx` | Ask / Looking / Share / Connect CTAs |
| `apps/cards-web/src/hooks/useMyCard.tsx` | Ownership context for landing CTA |
| `apps/cards-web/src/app/(landing)/page.tsx` | Signed-in owners → View / Edit, not Create |
| `apps/cards-web/tests/smoke.spec.ts` | Create → auth nudge → review (mocked BE) |

### Cards BE
| Path | Role |
|---|---|
| `services/cards-api/api/onboard.py` | `GET /onboard/claim-candidates`; `create_start` / `create_publish` emits |
| `services/cards-api/services/cards.py` | `claim_candidates_by_linkedin` (published + unclaimed) |
| `services/cards-api/tests/test_unclaimed_tiering.py` | Unit: normalised LinkedIn match |
| `services/cards-api/services/events.py` | S04 allowlist (no S08 step events) |

### Explicitly off default path
- Memory-key paste step: `memoryStep` defaults to `"done"` (`create/page.tsx` ~473–475) — matches ticket.

---

## Highest-impact gaps (ordered)

1. **No `FEATURE_S08_ONBOARDING_V2` / cookie % rollout** → no safe rollback; contradicts ticket rollout section.
2. **Still a 6-question wizard**; **no live card preview** during scrape → AC1 fails.
3. **Funnel incomplete** — missing `question_answered`, `first_win_*` → AC5 fails.
4. **PR0 component split** not done — maintainability risk; ticket said do not skip.
5. **First-win Ask** opens empty chat — no demonstrated working answer → AC4 weak.
6. **GitHub OAuth** ticket-optional vs **D12 LinkedIn-only** — treat as out of scope unless product revisits D12.
7. **Playwright gaps:** claim UI (non-empty candidates), welcome/first-win, existing-owner skip, publish→welcome, 390px scroll.

---

## Test coverage

| Area | Coverage |
|---|---|
| Create → auth nudge → review | Yes (`smoke.spec.ts`) |
| Claim-candidates UI (non-empty) | No (mock always `[]`) |
| Welcome / Ask chat | No |
| Existing owner skips “Add profiles” | No |
| Signed-in publish → `/welcome` | No |
| Mobile 390px no H-scroll | No |
| API `claim_candidates_by_linkedin` | Yes (unit) |
| `create_start` / `create_publish` | Via S04 when `FEATURE_S04_EVENTS` on |
| `question_answered` / `first_win_*` | N/A — not implemented |

---

## Rollout / rollback reality

| Ticket expectation | Actual |
|---|---|
| Flag `FEATURE_S08_ONBOARDING_V2` + cookie % | **Does not exist** |
| Keep v1 route until S04 metrics parity | **v2 always on**; no dual route |
| Rollback | Redeploy / revert `562ea53` (and follow-ups), not a flag flip |

Related: events themselves are gated by `FEATURE_S04_EVENTS` (default **false**) — even existing create funnel events may be dark in prod unless that flag was turned on ops-side.

---

## Scope notes / conflicts

- **D12 vs optional GitHub:** product decision already removed GitHub/Google/email magic link. Do not treat missing GitHub OAuth as an S08 defect unless D12 is overturned.
- **Landing copy:** “View my profile” vs ticket “Open my card” — functional equivalent; cosmetic only.
- **Scraper latency:** ticket risk stands — progressive partial results not implemented; “60s same screen” unmet for other reasons (quiz + no live preview) even before scraper timing.

---

## Out of scope for this plan

- Implementing any of the gaps above.
- Redesigning review/edit (ticket: don’t).
- MCP/Memory Connect (S09).
- Schema / `packages/db` changes.

---

## If a follow-up implementation is requested

Recommended order (not part of this audit deliverable):

1. Feature flag + keep/restore v1 escape hatch (rollback).
2. Live preview + collapse/remove multi-step quiz (AC1).
3. First-win seeded Ask answer (AC4).
4. Allowlist + emit `question_answered` / `first_win_*` (AC5; needs S04 on).
5. Playwright: claim, welcome, existing owner, 390px.
6. Optional later: PR0 split; GitHub only if D12 revisited.
