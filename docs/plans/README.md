# Planning docs

These are the design and migration documents behind `zynd-platform`. They
were written across several sessions as the plan evolved — later docs
supersede earlier ones in places, and each header table says so explicitly.
**Trust the newest status line over an older doc's summary of it.**

None of these describe what's live in prod today; check with a maintainer
or the `AGENTS.md` "migration status" section for that.

## Reading order

**1. Background — why this repo exists at all**

| Doc | Covers |
|---|---|
| [`ZYND_PLATFORM_ARCHITECTURE.md`](./ZYND_PLATFORM_ARCHITECTURE.md) | The original findings, decisions (ADR-1 … ADR-14), and target architecture for unifying persona/cards/memory identity |
| [`ZYND_PLATFORM_HLD.md`](./ZYND_PLATFORM_HLD.md) | How it works: components, auth flows, data flows, deployment |
| [`ZYND_PLATFORM_LLD.md`](./ZYND_PLATFORM_LLD.md) | Exactly what to change, file by file — written before this repo existed, so its status table (top of file) is the most reliable part; the rest describes a separate-repos world |

These three assumed **separate repos** for persona/cards/memory. That
assumption was overtaken by the monorepo decision below — read them for the
*why* (identity model, security findings, target architecture), not for the
current *how*.

**2. How this repo came to exist**

| Doc | Covers |
|---|---|
| [`ZYND_MONOREPO_PLAN.md`](./ZYND_MONOREPO_PLAN.md) | The decision to merge persona/cards/memory into one repo with full git history, and the M0–M5 build plan. Mostly executed — the repo you're standing in is the result |

**3. Active — the in-flight work**

| Doc | Covers |
|---|---|
| [`ZYND_DB_UNIFY_PLAN.md`](./ZYND_DB_UNIFY_PLAN.md) | **Current plan** for moving cards' data and login off the dashboard's Supabase project (xmfj) onto persona's (aafo), with Drizzle-managed migrations in `packages/db`. Supersedes §3/P1/P3/P4 of the cards-move plan below |
| [`ZYND_CARDS_MOVE_PLAN.md`](./ZYND_CARDS_MOVE_PLAN.md) | The broader cards-move plan (P0–P5). P0, P2, and P5 still apply; P1/P3/P4 are replaced by `ZYND_DB_UNIFY_PLAN.md` above |

**4. Paused**

| Doc | Covers |
|---|---|
| [`ZYND_STAGE2_PLAN.md`](./ZYND_STAGE2_PLAN.md) | The original Stage 2 ("Zynd Account") rollout plan, written before the monorepo/cards-move decisions reordered the work. Paused until the cards move above is done |

## If you're picking this up fresh

1. Skim `ZYND_PLATFORM_ARCHITECTURE.md` for the *why*.
2. Read `ZYND_DB_UNIFY_PLAN.md` — that's the plan actually being executed
   right now.
3. Check `../../AGENTS.md` §7 (migration status) for what's actually landed
   vs. still pending, since these docs describe intent at the time they were
   written, not a live status board.
