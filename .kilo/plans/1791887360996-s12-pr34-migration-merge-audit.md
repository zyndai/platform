# S12 PR #34 — merge + migration audit

## Goal

Determine whether [PR #34](https://github.com/zyndai/platform/pull/34) (`s12` → `dev`) will merge cleanly and whether its `packages/db` migrations are correctly formed per `packages/db/README.md` / CI.

## Verdict (current head `d866491`)

| Check | Result |
|---|---|
| GitHub mergeability | **MERGEABLE**, `mergeStateStatus: CLEAN` |
| CI | **All green** — `migrations`, `python (persona-api|cards-api|memory)`, `web (cards-web|persona-web)` |
| Migration hygiene / apply / schema sync | **Passed** in `db` workflow run `38376939524` (empty Postgres apply + `db:lint` + drizzle generate empty + drift) |
| Branch vs `dev` | **Diverged**: ahead 11, **behind 3** (S11/S10 docs+MCP only; **no `packages/db` overlap**) |
| Migration form | **Correct enough to merge** — owner headers, journals, expand-only, schema↔SQL aligned (CI proved). See caveats below. |
| Apply to prod aafo | **Out of scope for merge** — human-only (`AGENTS.md` §6); do not treat merge as apply |

**Recommendation:** Safe to merge into `dev` from a migrations/GitHub-merge perspective. Prefer updating the branch from `dev` first only to avoid a noisy env-example conflict resolution and to re-run CI on the merged tip. Do **not** apply migrations to aafo as part of merge.

## Scope

**In scope**

- PR #34 merge readiness into `dev`
- Form of persona `0002`–`0006` and cards `0012`–`0014`
- Journals, snapshots, owner headers, OWNERS.md, expand-only / FK sequencing
- Non-db overlap with the 3 commits on `dev` that `s12` lacks

**Out of scope**

- Feature correctness of intros product UX beyond migration shape
- Applying migrations to prod/dev aafo
- Fixing historical Persona auth issues listed in `docs/S12_READINESS.md` (already addressed in-PR via guards/triggers per author; not re-audited here as merge blockers)

## Migration inventory (new on `s12`)

### Cards (`cards` schema) — after `0011_s10_owner_operations`

| File | Kind | Notes |
|---|---|---|
| `0012_s12_intro_projection.sql` | Generated table | `cards.intro_requests` + RLS + FKs (`ON DELETE no action`) + index + service_role policy |
| `0013_s12_intro_events.sql` | Custom | Grants/revokes + `cards.s12_sync_intro(jsonb,boolean)` SECURITY DEFINER, service_role only; writes `card_events` (`intro_request` / `intro_accepted`) |
| `0014_s12_deletion_compatibility.sql` | Custom | Drop/re-add FKs to `ON DELETE cascade` (expand-then-tighten on **new** table only) |

Journal tags `0012`–`0014` match files; snapshots present.

### Persona (`public`) — after `0001_persona_drop_public_read`

| File | Kind | Notes |
|---|---|---|
| `0002_s12_intro_requests.sql` | Generated tables | `persona_intro_audit`, `persona_intro_rules`, `persona_intro_requests` + RLS/policies/FKs (`no action`) + indexes |
| `0003_s12_intro_operations.sql` | Custom | Grants; `s12_guard_*` triggers on `dm_threads` / `dm_messages` / `agent_tasks`; `s12_create_intro` / `s12_respond_intro` / `s12_set_intro_rule` / `s12_save_thread_permissions` (service_role EXECUTE only) |
| `0004_s12_audit_details.sql` | Generated column | Adds `persona_intro_audit.details jsonb NOT NULL DEFAULT '{}'` |
| `0005_s12_deletion_compatibility.sql` | Custom | Drop/re-add FKs → cascade / `meeting_task_id` set null |
| `0006_s12_meeting_grants.sql` | Custom | `CREATE OR REPLACE` of `s12_guard_meeting_write` with intro permission checks |

Journal tags `0002`–`0006` match files; snapshots present. Schema TS (`persona/schema/intros.ts`, `cards/schema/intros.ts`) matches final FK on-delete semantics (cascade / set null).

## Form checklist vs `packages/db` rules

| Rule | Status |
|---|---|
| Lives under `packages/db/<history>/migrations/` (not frozen service SQL) | Pass |
| First line `-- owner: persona\|cards\|shared` | Pass on all 8 new SQL files |
| Why + rollback comments | Pass |
| Expand-only (no drops of pre-existing tables/data) | Pass — only drops FKs on **new** S12 tables to re-add with cascade |
| Journal ↔ `*.sql` tags | Pass (CI `db:lint`) |
| Naming `NNNN_lower_snake` | Pass |
| Schema files + migrations agree | Pass (CI drizzle generate empty) |
| Apply from empty DB | Pass (CI `db:migrate --yes`) |
| OWNERS.md updated for new tables | Pass |
| Functions listed in OWNERS “Functions” table | **Gap (docs only)** — `s12_*` / `cards.s12_sync_intro` not listed under Functions section |

## Caveats (non-blocking for GitHub merge; note before apply)

1. **`0003` uses `persona_intro_audit.details` before `0004` adds the column.**  
   Safe when pending persona migrations run in **one transaction** (`README`: history pending runs as one txn). **Unsafe** if someone applies `0002`+`0003` alone without `0004`. Prefer documenting “apply persona through `0006` together” or (follow-up) fold `details` into `0002` / stop writing `details` until after `0004`.

2. **Initial FKs are `ON DELETE no action`, then `0014`/`0005` flip to cascade.** Intentional expand + deletion-compat pattern; correct final schema matches Drizzle. Intermediate state between those migrations would block account/card deletes if code ran against it — same “apply the S12 batch together” guidance.

3. **Branch behind `dev` by 3 commits** (`d37d7af6`, `4c3d65e7`, `e119b5d0`): S11 MCP/docs + env knobs. Overlap on `apps/cards-web/.env.local.example` and `services/memory/.env.example` (both sides append different feature blocks). GitHub still MERGEABLE; merge commit will combine. Updating from `dev` before merge reduces surprise.

4. **`docs/S12_READINESS.md` still says “not ready”** while the PR implements S12 — historical assessment text; do not treat as a migration blocker, but avoid confusing operators.

5. **Prod apply is separate.** No staging DB; rehearse locally, `db:drift`, then human `db:migrate --project persona|cards --yes` only after review.

## Ordered tasks for an implementer / merger

1. Reconfirm PR tip and CI still green (`gh pr view 34` / `gh pr checks 34`).
2. Optionally merge `origin/dev` into `s12`, resolve env-example appends (keep **both** S11 and S12 knobs), push, wait for CI.
3. Merge PR #34 into `dev` (human). Do **not** apply SQL to aafo in the same step.
4. Post-merge (human, when ready to enable intros):
   - Local rehearsal: empty Postgres + stubs + `db:migrate --yes`
   - `db:drift` vs prod with correct `--upto`
   - Apply **persona `0002`–`0006` as one pending batch**, then **cards `0012`–`0014` as one pending batch** (or full histories)
   - Deploy code / flip `FEATURE_S12_INTROS` only after schema is live
5. Optional hygiene follow-ups (can be a tiny follow-up PR): add `s12_*` functions to `OWNERS.md` Functions table; clarify batch-apply note in migration comments.

## Validation already done / to re-run after update-from-dev

- [x] CI `migrations` job (lint, apply empty, schema sync, drift)
- [x] CI service/web jobs green at current tip
- [ ] If branch updated from `dev`: re-check CI + spot-check combined `.env.example` files
- [ ] Before prod apply: local rehearsal + drift (human)

## Failure modes

| Failure | Impact | Mitigation |
|---|---|---|
| Merge without updating from `dev` | Possible env-example conflict resolution wrong; lose S11 knobs | Prefer update-from-dev; review merge of `.env.example` |
| Partial persona migrate (stop after `0003`) | `details` column missing → function create fails or audit inserts fail | Always apply through `0006` |
| Code deploy before migrate | Runtime errors calling missing RPCs/tables | Feature flag off until migrate |
| Migrate before code / flags | Tables exist unused — OK (expand-only) | Fine |

## Open questions

None blocking. Optional: whether to require update-from-dev before merge (recommended but not required for GitHub CLEAN merge).
