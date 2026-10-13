# S10 — Owner home (status)

**Landed on `dev` via PR #31** (`59fe4f4` / merge `5bd87d2`). Docs: `docs/S10_OWNER_HOME.md`.

## AC (code)

| AC | Status |
|---|---|
| Home score, inbox, connection, 7d views/hits | DONE (needs S04 events live) |
| Weekly digest + unsubscribe + weekly idempotency | DONE (SMTP gated; default noop) |
| Looking-for ≤3d → one nudge | DONE |
| Merge canonical + 301 + audit, no delete | DONE |
| Edit autosave + Saved | DONE (`useSectionAutosave`) |

## Residual (ops, not code)

1. Human-apply migrations `0010_s10_owner_home` + `0011_s10_owner_operations` (AGENTS §6).
2. Enable `FEATURE_S10_HOME` / `NEXT_PUBLIC_FEATURE_S10_HOME` / memory `FEATURE_S10_HOME` after migrate.
3. Digest: `FEATURE_S10_DIGEST=true` + `S10_MAILER=smtp` + SMTP env after sandbox proof.
4. Upstream stubs until later slices: S09 assistants, S11 query text, S12 intros.

## Do not re-implement

Parallel local work was discarded in favor of the merged PR. Use `docs/S10_OWNER_HOME.md` for rollout.
