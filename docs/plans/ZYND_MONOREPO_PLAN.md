# Monorepo plan: persona + cards + memory → `zyndai/platform` (bridge stays separate)

| | |
|---|---|
| **Status** | Planned · inventory done 2026-09-25 |
| **Goal** | One repo for the consumer product family, so cross-service changes, shared DB migrations and shared auth libraries live together |
| **Order** | Monorepo first. Within it: M0 freeze → M1 build with history → M2 plumbing → **M3 GitHub** (creates the repo the boxes will clone from) → **M4 server cutover**. GitHub comes before the servers, reversed from the original draft. Then the cards move (`ZYND_CARDS_MOVE_PLAN.md`) happens inside it, with `apps/cards-web` instead of a `zynd-cards-web` repo and `packages/db` instead of a `zynd-db` repo. Stage 2 stays paused. |
| **Background** | `ZYND_PLATFORM_ARCHITECTURE.md` (ADR-10), `ZYND_CARDS_MOVE_PLAN.md` |

---

## 1. Decisions

| # | Decision | Status |
|---|---|---|
| D1 | Monorepo = **agent-persona** (backend + webapp), **zynd-cards** (API; `apps/cards-web` later), **memory-layer**, plus DB migrations and shared libraries | **Decided 2026-09-25** |
| D2 | **Visibility.** `agent-persona` and `memory-layer` are **public** today, `zynd-cards` is **private**. Recommended: **private** (cards is private, and `infra/` holds server configs). If persona/memory are public deliberately (open source), publish read-only mirrors later. **What going private changes:** the old public repos stay archived and public, frozen at their last commit — no new exposure; both boxes need a read-only deploy key (SSH, no `gh`/tokens); Actions minutes become metered (Free org quota: 2,000 min/month, see Q13); branch protection on `main` needs a paid org tier on GitHub Free (Q10); memory's existing `main` ruleset doesn't carry over and must be recreated; the one public link to a moving repo (`docs` repo, `v2/resources/support.md:45`) needs fixing (M5.3); today all 3 repos have 0 forks and 0 stars, so nothing external depends on them being public. | **Confirm with the user before M4** (M0–M3 are local and don't depend on it) |
| D3 | **zynd-bridge stays a separate repo.** It's an npm CLI running on users' machines, so it can't change in step with the server: old versions stay installed, and memory must stay backward-compatible with them anyway. Its native tooling (Playwright, better-sqlite3) would weigh on monorepo CI. Link: the monorepo publishes memory's route list at `packages/contracts/memory-routes.json`, and bridge's `scripts/update-memory-routes.sh` + `tests/memory-contract.test.ts` consume it. Rule: routes bridge uses (see `services/memory/tests/test_bridge_contract.py`) are deprecated before removal, never removed in the same release. | **Decided 2026-09-25** |
| D4 | Repo name `zyndai/platform` | Recommended; confirm with D2 |
| D5 | **Branch policy for the whole monorepo.** `dev` auto-deploys **persona dev only** (cards and memory have no dev environment on the boxes today, and their prod deploys stay manual from `main`). `main` is prod, PR-only and protected. This replaces: persona dev→main, memory PR-only, cards/bridge direct main. | Recommended; confirm with D2 |
| D6 | **Stays separate:** the zynd.ai `dashboard` (separate product), and the public SDKs/infra (`zyndai-agent`, `zyndai-ts-sdk`, `agent-dns`, `mcp-server`, `docs`, `zynd-deployer`, `agent-registry`) | Decided |

## 2. Facts (checked 2026-09-25, re-confirmed at planning time)

| Repo | Visibility | Size of `.git` | Remote branches | Runtime / deploy today | Tests (baseline, see Appendix A4) |
|---|---|---|---|---|---|
| agent-persona | public | 7.8 MB | 20 | pm2 on EC2 (**zynd-deployer**, `13.219.55.137`). Prod `/home/ubuntu/agent-persona` (`api` :8000, `web` :3001); dev `/home/ubuntu/agent-persona-dev` (`api-dev` :8001, `web-dev` :3002). Caddy `/etc/caddy/Caddyfile`. A push to `dev` auto-deploys dev.persona.zynd.ai via the pm2 process `persona-dev-webhook` (exact mechanism: Q2). | backend: **313 passed, 5 failed** · webapp: tsc 5 errors (stale local install) · eslint 88 problems (57 errors, 31 warnings) |
| zynd-cards | private | 0.4 MB | 3 | Docker service `cards` on **zynd-api** (`54.147.91.20`), built from `/home/ubuntu/zynd-cards`, declared in **memory-layer's** `docker-compose.prod.yml`, env `/home/ubuntu/zynd-cards/.env.prod` | **89 passed, 2 failed** (`test_x_bot`) |
| memory-layer | public | 1.4 MB | 17 | Docker compose on zynd-api: `api` :8000, `mcp` :8090, `worker`, Postgres + pgvector, Redis, Caddy (`Caddyfile` in repo). Deployed by `make deploy` (rsync + compose), **not** `git pull` — the box checkout can drift from git. `render.yaml` exists; Render use unconfirmed (Q9). `main` is protected by a GitHub ruleset. | **203 passed, 9 failed, 81 deselected** (`-m "not integration"`) |
| zynd-bridge | private | 0.4 MB | 2 | npm package `@zynd/bridge`, CLI `zynd`, runs on users' machines | **276 passed** |

**Server facts (confirmed by DNS + the AWS audit reports in `p3ai/`; the rest is Appendix A5 and the open questions in Appendix C):**
- **Two hosts, not one.** `persona.zynd.ai` and `dev.persona.zynd.ai` both resolve to **zynd-deployer** (`13.219.55.137`, t4g.large/8GB). `api.zynd.ai` resolves to **zynd-api** (`54.147.91.20`, t3.medium, **only 4.1 GB disk free / 79% used**).
- zynd-api also holds two dead clones worth cleaning up post-cutover: `~/zynd` (a stale second memory-layer copy per commit `d3b7f84`) and `~/zynd-cards.old` / `~/zynd-src`.
- zynd-deployer separately runs its own memory-layer clone on branch `twitter-source-tags` (Postgres :5433, Redis :6380) for the deployer product — out of scope, left alone (Q6).
- No tags, submodules or Git LFS in any of the 4 repos. No `.github/` workflows exist today in any of them (memory-layer had one once; it survives only in history). No repo has ever committed a `.env`, `.pem` or key file (verified: a full-history secret scan of all 4 repos for AWS/OpenAI/Anthropic/JWT/PEM/GitHub/Slack/Google/Supabase/Telegram token patterns found 0 real hits).
- Each repo has gitignored `.env` files, `CLAUDE.md`/`AGENTS.md`/`GEMINI.md` agent docs, and `.code-review-graph`/`.repowise` tool folders. **Don't commit those tool folders.**
- **Tooling on this Mac:** no Docker, no `gh`. `uv venv --python 3.12` venvs in the scratchpad (repo `.venv`s may be broken/missing — confirmed missing for cards and memory). Node 26. `git-filter-repo` not yet installed; `uv tool install git-filter-repo`.

## 3. Target layout

```
zyndai/platform
├── apps/
│   ├── persona-web/          ← agent-persona/webapp, incl. persona-web/db/ (frozen SQL, see packages/db)
│   └── cards-web/            ← created later by the cards move (P2), not in this plan
├── services/
│   ├── persona-api/          ← agent-persona/backend, incl. persona-api/contextaware/ (only importer:
│   │                            mcp/server.py, via sys.path — confirmed, moves with it)
│   ├── cards-api/            ← zynd-cards
│   └── memory/               ← memory-layer (app/, sql/, scripts/, tests/, pyproject.toml, render.yaml)
├── packages/
│   ├── db/                   ← Supabase CLI layout for the shared persona DB (scaffold only here;
│   │                            baseline + cards tables come from the cards move P1)
│   ├── account-py/  account-ts/   ← Stage 2 (empty placeholders with README, or omit)
│   └── contracts/            ← memory's OpenAPI route list (memory-routes.json), consumed by the separate zynd-bridge repo
├── infra/
│   ├── api-box/              ← Caddyfile + docker-compose.prod.yml (moved from memory-layer; build
│   │                            contexts → ../../services/cards-api and ../../services/memory; needs an
│   │                            explicit `name: memory-layer` — see Appendix B, risk R1)
│   └── persona-box/          ← ecosystem.config.js + ecosystem.dev.config.js (cwd → monorepo paths)
├── docs/
│   ├── persona/               ← architecture.md, A2A.md, GROUPS.md, theme.md, AUDIT_REPORT.md, IMPLEMENTATION_MEMORY_BRIEF.md
│   └── monorepo/               ← IMPORT.md (source SHAs + commit-map files), DEPLOY.md, CUTOVER_MONOREPO.md
├── archive/                   ← history only (old memory/, prisma/, images_for_debug/ from agent-persona);
│                                  nothing here at HEAD
├── .github/workflows/        ← path-filtered test jobs per service/app
├── CLAUDE.md                 ← root: layout, branch policy, per-service commands; service CLAUDE.md files stay
├── CODEOWNERS  README.md  .gitignore  .editorconfig
```

Full file-by-file mapping (every top-level entry of all 3 repos, with the reasoning) is Appendix A2. Root dotfiles that tools read at the repo root (`.mcp.json`, `.opencode.json`, `.cursorrules`, `.windsurfrules`, `GEMINI.md`) come from agent-persona and land at the monorepo root, not under a service folder.

## 4. Principles

1. **Phase 1 is a pure move.** No code changes except paths and config needed for the new locations. No tooling migration (no pnpm or uv workspaces yet), no dependency upgrades.
2. **Keep history.** Every file's history must survive, so `git log --follow services/memory/app/main.py` shows the old commits.
3. **Nothing breaks in prod before cutover.** Old repos, server directories and deploys stay untouched until the new ones are verified. Every server step has a rollback.
4. **The agent never touches servers, GitHub settings or prod.** It prepares commands and runbooks; the user runs them and pastes output.
5. **Stop after every phase**, report, and wait for an OK.
6. **Prod must run exactly the imported SHA before its cutover.** Memory is deployed by rsync (not `git pull`), so its box checkout can drift from git; cards may have a pending redeploy; persona prod may be on the wrong branch (Appendix C, Q1). M0.5 brings each prod to the freeze SHA first, and each M4 cutover step re-checks the box SHA against `docs/monorepo/IMPORT.md` before proceeding.

## 5. Phases

**Order changed from the original draft:** GitHub (M3) now comes **before** the server cutover (M4), because the boxes clone from GitHub — pushing the repo before the boxes need it removes a chicken-and-egg step.

**Freeze window:** from M1.2 (SHAs recorded) to the end of M4. Target ≤ 2 working days. A hotfix needed during the freeze goes to the old repo **and** gets re-imported (M3.1 re-checks for this).

**Variables used throughout:**
```
S=<executing session's scratchpad>
W=$S/mono
P=/Users/apple/Desktop/p3ai
Z=$P/zynd
```

### M0: Inventory and freeze

- **M0.1 AGENT: done.** See Appendix A (branch inventory, file-by-file map, hard-coded paths, test baselines).
- **M0.2 USER:** Answer the open questions in Appendix C (Q1–Q13). Decide the "merge before the freeze / port after / abandon" call per branch in Appendix A1.
- **M0.3 USER:** Merge agent-persona `dev` → `main` (brings in `c6e2948`, the auth fix). Open and merge the memory-layer PR `fix/bridge-contract-and-uid` (no PR exists yet — open one first), plus `fix/cors-dev-persona` if you choose to fold it in now. Handle persona PR #18 (`feat/people-smart-sections`) per your Appendix A1 decision.
- **M0.4 USER:** Announce the freeze window to the team: no pushes to agent-persona / zynd-cards / memory-layer for the duration. Work on branches is fine — it gets ported in M5.5.
- **M0.5 USER:** Bring each prod deploy up to the exact tip of main before the freeze (principle 6): deploy the merged memory PR, redeploy zynd-cards `main`, and make persona prod run `main` (same content as `dev` after M0.3 — Appendix C Q1 first, since the audit suggests prod may currently be on `dev`). *Rollback:* the previous deploy.
- **M0.6 AGENT:** Once M0.3/M0.5 have landed and each prod runs its tip, `git -C $P/<repo> fetch origin` for all 3 repos and record `git ls-remote` of `main` and `dev` to `$W/freeze-shas.txt`. This is the freeze snapshot M1 imports from.

### M1: Build the monorepo locally, with history (AGENT, in `$Z`)

Everything below is captured in `$S/build_monorepo.sh` so a re-import (M3.1) is one command, not a re-derivation.

- **M1.1** `uv tool install git-filter-repo`, confirm with `git filter-repo --version`.
- **M1.2 Fresh bare clones from GitHub** (never touch the working copies in `$P`):
  ```
  mkdir -p $W && cd $W
  for r in agent-persona zynd-cards memory-layer; do git clone --bare "$(git -C $P/$r remote get-url origin)" $r.git; done
  ```
- **M1.3 Filter each clone.** Rules apply in the order given (per the filter-repo source). `--prune-empty never --prune-degenerate never` keeps commit counts identical — some renames (e.g. `8b645ef`, a webapp/→root README move) become empty after the path-rename and must still be kept for `git log --follow` continuity.
  ```
  F="--prune-empty never --prune-degenerate never"
  git -C $W/zynd-cards.git filter-repo $F --to-subdirectory-filter services/cards-api

  git -C $W/memory-layer.git filter-repo $F --to-subdirectory-filter services/memory \
    --path-rename services/memory/Caddyfile:infra/api-box/Caddyfile \
    --path-rename services/memory/docker-compose.prod.yml:infra/api-box/docker-compose.prod.yml

  git -C $W/agent-persona.git filter-repo $F --to-subdirectory-filter _src \
    --path-rename _src/backend/:services/persona-api/ \
    --path-rename _src/contextaware/:services/persona-api/contextaware/ \
    --path-rename _src/webapp/:apps/persona-web/ \
    --path-rename _src/db/:apps/persona-web/db/ \
    --path-rename _src/README.md:apps/persona-web/README.md \
    --path-rename _src/CLAUDE.md:services/persona-api/CLAUDE.md \
    --path-rename _src/AGENTS.md:services/persona-api/AGENTS.md \
    --path-rename _src/docs/:docs/persona/ \
    --path-rename _src/architecture.md:docs/persona/architecture.md \
    --path-rename _src/A2A.md:docs/persona/A2A.md \
    --path-rename _src/GROUPS.md:docs/persona/GROUPS.md \
    --path-rename _src/theme.md:docs/persona/theme.md \
    --path-rename _src/AUDIT_REPORT.md:docs/persona/AUDIT_REPORT.md \
    --path-rename _src/IMPLEMENTATION_MEMORY_BRIEF.md:docs/persona/IMPLEMENTATION_MEMORY_BRIEF.md \
    --path-rename _src/ecosystem.config.js:infra/persona-box/ecosystem.config.js \
    --path-rename _src/ecosystem.dev.config.js:infra/persona-box/ecosystem.dev.config.js \
    --path-rename _src/ecosystem.config.js.bak-2026-05-26:infra/persona-box/ecosystem.config.js.bak-2026-05-26 \
    --path-rename _src/.gitignore:.gitignore \
    --path-rename _src/.mcp.json:.mcp.json \
    --path-rename _src/.opencode.json:.opencode.json \
    --path-rename _src/.cursorrules:.cursorrules \
    --path-rename _src/.windsurfrules:.windsurfrules \
    --path-rename _src/GEMINI.md:GEMINI.md \
    --path-rename _src/:archive/agent-persona/
  ```
  The last rule is a catch-all: anything not explicitly named lands in `archive/`, and M1.5 fails the build if anything besides two known strays (a stray root `package-lock.json` and a tracked `.claude/scheduled_tasks.lock`) is there at HEAD.
- **M1.4 Parity per source.** Commit counts equal, blob sets identical (content untouched by a rename):
  ```
  for r in agent-persona zynd-cards memory-layer; do for b in main dev; do
    git -C $W/$r.git rev-parse -q --verify $b >/dev/null || continue
    echo "$r/$b commits $(git -C $P/$r rev-list --count origin/$b) -> $(git -C $W/$r.git rev-list --count $b)"
    diff <(git -C $P/$r ls-tree -r origin/$b --format='%(objectname)' | sort) \
         <(git -C $W/$r.git ls-tree -r $b --format='%(objectname)' | sort) && echo "  blobs identical"
  done; done
  ```
- **M1.5 Layout check** on the filtered agent-persona clone:
  - `git -C $W/agent-persona.git ls-tree --name-only main` must list only: `.cursorrules .gitignore .mcp.json .opencode.json .windsurfrules GEMINI.md apps archive docs infra services`.
  - `git -C $W/agent-persona.git ls-tree -r --name-only main archive` must list only `archive/agent-persona/package-lock.json` and `archive/agent-persona/.claude/scheduled_tasks.lock`.
  - Across all history: `git log --all --format= --name-only | cut -d/ -f1 | sort -u` shows nothing outside those roots.
- **M1.6 Assemble** — merge order memory → cards → persona (smallest risk first; persona goes last because it brings the root dotfiles):
  ```
  mkdir $Z && cd $Z && git init -b main && git commit --allow-empty -m "Start the zyndai/platform monorepo"
  for r in memory-layer zynd-cards agent-persona; do git fetch --no-tags $W/$r.git "refs/heads/*:refs/import/$r/*"; done
  git merge --no-ff --allow-unrelated-histories refs/import/memory-layer/main -m "Import memory-layer@<sha> into services/memory and infra/api-box (history preserved)"
  git merge --no-ff --allow-unrelated-histories refs/import/zynd-cards/main   -m "Import zynd-cards@<sha> into services/cards-api (history preserved)"
  git merge --no-ff --allow-unrelated-histories refs/import/agent-persona/main -m "Import agent-persona@<sha> into services/persona-api, apps/persona-web, docs/persona, infra/persona-box (history preserved)"
  git branch dev main    # if persona dev == main after M0.3; otherwise: git switch -c dev main && git merge --no-ff refs/import/agent-persona/dev
  # "port after" branches from Appendix A1, one per branch, e.g.:
  git branch port/agent-persona/feat/people-smart-sections refs/import/agent-persona/feat/people-smart-sections
  ```
- **M1.7 Monorepo parity.** The assembled tree must equal the union of the filtered sources:
  ```
  diff <(for r in memory-layer zynd-cards agent-persona; do git ls-tree -r refs/import/$r/main --format='%(objectname) %(path)'; done | sort) \
       <(git ls-tree -r main --format='%(objectname) %(path)' | sort) && echo "tree == union of sources"
  ```
  History must follow through the rename. Each count must equal the source's count for the old path:
  ```
  git log --oneline --follow -- services/memory/app/main.py | wc -l
  git log --oneline --follow -- infra/api-box/Caddyfile | wc -l
  git log --oneline --follow -- services/persona-api/agent/orchestrator.py | wc -l
  git log --oneline --follow -- apps/persona-web/src/app/layout.tsx | wc -l
  git log --oneline --follow -- apps/persona-web/README.md            # includes the now-empty 8b645ef move
  git log --oneline --follow -- services/cards-api/main.py | wc -l
  git log --oneline --follow -- infra/persona-box/ecosystem.config.js | wc -l
  git blame -s services/persona-api/mcp/server.py | head -3           # shows old commits, not the import merge
  git log --first-parent --oneline main                                # 1 root + 3 import merges
  ```
- **M1.8 Secret and junk scan** of every ref about to be pushed (`main dev port/*`):
  - `git log main dev $(git for-each-ref --format='%(refname)' refs/heads/port) -p | python3 $S/secret_scan.py` — the same AWS/OpenAI/JWT/PEM/GitHub/Slack/Google/Supabase/Telegram pattern scanner used for the Appendix A4 baseline scan. Expect 0 hits.
  - `git ls-files | grep -E '(^|/)\.env($|\.)' | grep -v '\.example$'` → expect empty.
  - `git ls-files | grep -E '(^|/)(\.code-review-graph|\.repowise|node_modules|\.venv|__pycache__)/'` → expect empty.
  - `git ls-files -z | xargs -0 ls -l | awk '$5>1000000'` → expect empty (no accidental large binaries).
- **M1.9 One fix-up commit**, "Fix paths for the monorepo layout" — paths and config only, via `Edit`/`sed`, not a rewrite of the whole file:
  1. `services/persona-api/mcp/server.py:10`: `.parent.parent.parent / "contextaware"` → `.parent.parent / "contextaware"`.
  2. `apps/persona-web/package.json`: `-f ../db/sql/policies.sql` → `-f db/sql/policies.sql`.
  3. `git rm -r archive/` (the empty root lockfile and the stray lock file).
  4. `/.gitignore`: rewrite the 15 anchored `/backend/…` / `/webapp/…` rules to `/services/persona-api/…` / `/apps/persona-web/…`. Add `!.env.example` and `!.env.*.example`.
- **M1.10 Tests vs baseline.**
  - **Before:** re-run in a fresh `--no-local` clone of each repo at its freeze SHA (no `.env`), so the comparison is apples-to-apples.
  - **After:** run the same suites in `$Z`.
  - Pass/fail counts and the failing test IDs must match between before and after.
  - Venvs: `uv venv --python 3.12 $S/venv-{persona,cards,memory}`; install each service's own requirements/pyproject plus `pytest pytest-asyncio`.
  ```
  T="env PYTHONDONTWRITEBYTECODE=1"
  (cd $Z/services/persona-api && $T $S/venv-persona/bin/python -m pytest -q -p no:cacheprovider -rf)
  (cd $Z/services/cards-api   && $T $S/venv-cards/bin/python   -m pytest -q -p no:cacheprovider -rf)
  (cd $Z/services/memory      && $T $S/venv-memory/bin/python  -m pytest -q -p no:cacheprovider -m "not integration" -rf)
  (cd $Z/services/persona-api && $T $S/venv-persona/bin/python -c "import mcp.server as m; print(type(m.mcp_server).__name__)")  # confirms the M1.9 contextaware fix
  (cd $Z/apps/persona-web && npm ci && npx tsc --noEmit --incremental false; npx eslint | tail -1; npm run build)
  ```
- **STOP.** Report parity results, the secret/junk scan outcome, and before/after test counts.

### M2: Monorepo plumbing (AGENT, commits on `main`, then fast-forward `dev`)

- **M2.1 `infra/api-box/docker-compose.prod.yml`** (paths relative to this file's new location):
  - Add `name: memory-layer` at the top — **must match the live compose project name**, or `docker compose up` creates a new empty Postgres volume (Appendix B, risk R1).
  - api/worker/mcp: `build: .` → `build: ../../services/memory`; `env_file: .env.prod` → `env_file: ../../services/memory/.env.prod`.
  - cards: `context: /home/ubuntu/zynd-cards` → `context: ../../services/cards-api`; `env_file: /home/ubuntu/zynd-cards/.env.prod` → `env_file: ../../services/cards-api/.env.prod`.
  - caddy's `./Caddyfile` stays as-is (the file moves with it). Update the stale "Built from ~/zynd-cards" comment.
- **M2.2 `infra/persona-box/ecosystem*.config.js`:** `/home/ubuntu/agent-persona/{backend,webapp}` → `/home/ubuntu/zyndai-zynd/{services/persona-api,apps/persona-web}`; the dev file's `DEV = "/home/ubuntu/agent-persona-dev"` → `"/home/ubuntu/zyndai-zynd-dev"`, and `${DEV}/backend`/`${DEV}/webapp` follow. pm2 app names, ports and `env:` blocks stay as they are.
- **M2.3 `services/memory/Makefile` deploy target:** rsync targets → `/home/ubuntu/zyndai-zynd/services/memory/{app,sql}/`; `cd ~/zynd && sudo docker compose -f docker-compose.prod.yml …` → `cd ~/zyndai-zynd-platform/infra/api-box && sudo docker compose -f docker-compose.prod.yml …`; the schema pipe `< sql/schema.sql` → `< ../../services/memory/sql/schema.sql`. `EC2_HOST` unchanged. (This also fixes the `~/zynd` vs `~/memory-layer` bug from `d3b7f84` for good, since that fix never made it to a merged branch.)
- **M2.4 `infra/README.md` and `docs/monorepo/DEPLOY.md`:** box list, folder layout, env-file locations (`services/*/.env.prod`, `services/persona-api/.env`, `apps/persona-web/.env*`), the R1 warning, and the per-service deploy commands (persona box: `git pull` → pip if requirements changed → `npm run build` → `pm2 restart <apps>`; api box: `git pull` → `docker compose … up -d --build <svc>`).
- **M2.5 Root files:** `README.md`; `CLAUDE.md` (layout, branch policy per D5, per-service test commands — `dev` auto-deploys persona dev only); `CODEOWNERS` (placeholders); `.editorconfig`; `docs/monorepo/IMPORT.md` (source SHAs, plus each repo's `filter-repo/commit-map` copied in, so an old SHA like `c6e2948` stays traceable).
- **M2.6 `services/persona-api/CLAUDE.md` and `AGENTS.md`:** replace the "push to agent-persona dev" git-workflow section with the monorepo policy; `cd backend` → `cd services/persona-api`, `cd webapp` → `cd apps/persona-web`; fix the deploy-table folders. `apps/persona-web/CLAUDE.md` gets a pointer to `../../services/persona-api/CLAUDE.md`.
- **M2.7 `packages/db/`:** `npx supabase init` (creates `supabase/config.toml`; placeholder `project_id`), `supabase/migrations/.gitkeep`, `README.md`, `OWNERS.md`. No SQL yet — the cards-move P1 fills it in. "Frozen — see packages/db" READMEs go into `services/persona-api/db`, `services/persona-api/supabase/migrations`, `apps/persona-web/db` and `services/cards-api/db`.
- **M2.8 `packages/contracts/`:** `memory-routes.json` generated from `services/memory`'s OpenAPI, in the same format as `zynd-bridge/tests/fixtures/memory-routes.json` (must match byte-for-byte once generated); `scripts/gen-memory-routes.sh`; `README.md`.
- **M2.9 `.github/workflows/`,** one file per unit, `paths:`-filtered, no deploy jobs: `persona-api.yml`, `cards-api.yml`, `memory.yml` (uv, Python 3.12, `pytest -q`, memory adds `-m "not integration"`, with `--deselect` for the Appendix A4 known-failing IDs, flagged as debt); `persona-web.yml` (`npm ci`, `npx tsc --noEmit`, `npm run build`, `npm run lint` with `continue-on-error: true` until the 57 errors are cleared); `contracts.yml` (regenerate, then `git diff --exit-code packages/contracts/`).
- **M2.10 Re-run all of M1.10** (must still match), then `git switch dev && git merge --ff-only main`. **STOP** and report.

### M3: GitHub (USER clicks; AGENT pushes only after your OK)

- **M3.1 AGENT:** re-check `git ls-remote` on the 3 old repos against `$W/freeze-shas.txt`. If anything moved during the freeze, re-run `$S/build_monorepo.sh`, cherry-pick the M1.9/M2 commits, and redo M1.4–M1.10.
- **M3.2 USER:** github.com/organizations/zyndai/repositories/new → name **`zynd`**, **Private**, no README/.gitignore/license.
- **M3.3 AGENT:**
  ```
  git remote add origin https://github.com/zyndai/platform.git
  git push -u origin main dev
  git push origin 'refs/heads/port/*:refs/heads/port/*'
  ```
- **M3.4 USER:** Settings → General → Default branch → **`dev`** (per your Appendix C Q12 answer).
- **M3.5 USER:** Settings → Rules → Rulesets (needs a paid org tier on a private repo — Appendix C Q10):
  - Ruleset **"main"**, target `main`, Active: restrict deletions; block force pushes; require a pull request (0–1 approvals); require status checks (persona-api, cards-api, memory, persona-web, contracts); no bypass.
  - Ruleset **"dev"**, target `dev`: block force pushes and deletions only.
- **M3.6 USER:** Settings → Deploy keys → add the two read-only public keys generated in M4.1 ("zynd-api box", "zynd-deployer box").
- **M3.7 USER:** Settings → Collaborators/teams → mirror the 3 old repos' access. Settings → Actions → General → allow.
- **M3.8 AGENT:** confirm the first CI run is green on `dev` and `main`. **STOP.**

### M4: Server cutover (USER runs; pastes output; the agent checks each step before the next)

Order: **persona dev → persona prod → api box** (cards + memory together, since they share the api-box compose file). Old folders stay untouched for 7 days as the rollback.

- **M4.1 USER, both boxes — deploy key** (additive, no rollback needed):
  ```
  ssh-keygen -t ed25519 -f ~/.ssh/zynd_platform_monorepo_deploy -N '' -C "$(hostname) zyndai/platform read-only"
  printf 'Host github-zynd-platform\n  HostName github.com\n  User git\n  IdentityFile ~/.ssh/zynd_platform_monorepo_deploy\n  IdentitiesOnly yes\n' >> ~/.ssh/config
  cat ~/.ssh/zynd_platform_monorepo_deploy.pub     # → paste into M3.6
  ssh -T github-zynd-platform                       # expect "Hi zyndai/platform! …"
  ```
- **M4.2 USER, zynd-deployer — persona DEV:**
  ```
  O=~/agent-persona-dev; D=~/zyndai-zynd-platform-dev
  git clone -b dev github-zynd-platform:zyndai/platform.git $D
  cp -p $O/backend/.env $D/services/persona-api/.env
  for f in $O/webapp/.env*; do cp -p "$f" $D/apps/persona-web/; done
  BASEPY=$($O/backend/.venv/bin/python -c 'import sys; print(sys._base_executable)')
  $O/backend/.venv/bin/pip freeze > /tmp/persona-dev-freeze.txt
  cd $D/services/persona-api && $BASEPY -m venv .venv && .venv/bin/pip install -r /tmp/persona-dev-freeze.txt
  cd $D/apps/persona-web && npm ci && npm run build
  pm2 delete api-dev web-dev && pm2 start $D/infra/persona-box/ecosystem.dev.config.js && pm2 save
  curl -fsS 127.0.0.1:8001/health; curl -s -o /dev/null -w '%{http_code}\n' https://dev.persona.zynd.ai/   # expect 200
  pm2 logs api-dev --lines 50 --nostream
  ```
  **Rollback:** `pm2 delete api-dev web-dev && pm2 start ~/agent-persona-dev/ecosystem.dev.config.js && pm2 save`
- **M4.3 USER + AGENT — dev auto-deploy:** back up the `persona-dev-webhook` script; the agent gives the exact edit (repo folder → `~/zyndai-zynd-platform-dev`, build folder → `apps/persona-web`, backend → `services/persona-api`, repo-name check → `zyndai/platform`, once you've pasted the script per Appendix C Q2); `pm2 restart persona-dev-webhook`; add a matching webhook on the new GitHub repo (same payload URL/secret/content-type as the old one); test with a docs-only push to `dev`. **Rollback:** restore the `.bak`, restart, disable the new hook — the old hook on agent-persona stays until M5.
- **M4.4 USER, zynd-deployer — persona PROD** (after dev has been stable ≥1 hour, in a quiet hour):
  ```
  O=~/agent-persona; N=~/zyndai-zynd-platform
  git -C $O rev-parse HEAD      # must equal the agent-persona SHA in docs/monorepo/IMPORT.md, else STOP
  git clone -b main github-zynd-platform:zyndai/platform.git $N
  cp -p $O/backend/.env $N/services/persona-api/.env; for f in $O/webapp/.env*; do cp -p "$f" $N/apps/persona-web/; done
  BASEPY=$($O/backend/.venv/bin/python -c 'import sys; print(sys._base_executable)')
  $O/backend/.venv/bin/pip freeze > /tmp/persona-prod-freeze.txt
  cd $N/services/persona-api && $BASEPY -m venv .venv && .venv/bin/pip install -r /tmp/persona-prod-freeze.txt
  cd $N/apps/persona-web && npm ci && npm run build
  pm2 delete api web && pm2 start $N/infra/persona-box/ecosystem.config.js && pm2 save
  curl -fsS 127.0.0.1:8000/health; curl -s -o /dev/null -w '%{http_code}\n' https://persona.zynd.ai/
  ```
  Smoke test by hand: login, chat, messages, a Telegram message to the bot (prod only). **Rollback:** `pm2 delete api web && pm2 start ~/agent-persona/ecosystem.config.js && pm2 save`
- **M4.5 USER, zynd-api — cards + memory** (quiet hour). **Prechecks** — stop if any fails: `df -h /` (≥3 GB free), `git status --porcelain` + `rev-parse HEAD` clean and == IMPORT sha on both `~/memory-layer` and `~/zynd-cards`, `sudo docker compose ls` shows project `memory-layer`.
  ```
  Z=~/zyndai-zynd-platform; git clone -b main github-zynd-platform:zyndai/platform.git $Z
  cp -p ~/memory-layer/.env.prod $Z/services/memory/.env.prod
  cp -p ~/zynd-cards/.env.prod   $Z/services/cards-api/.env.prod
  [ -f ~/memory-layer/.env ] && cp -p ~/memory-layer/.env $Z/infra/api-box/.env
  cd $Z/infra/api-box
  diff <(cd ~/memory-layer && sudo docker compose -f docker-compose.prod.yml config --no-env-resolution --no-interpolate) \
       <(sudo docker compose -f docker-compose.prod.yml config --no-env-resolution --no-interpolate)
  #   expect only: build contexts, env_file paths, Caddyfile bind source. Same project name.
  sudo docker compose -f docker-compose.prod.yml build
  sudo docker compose -f docker-compose.prod.yml up -d --no-deps api worker mcp cards
  sudo docker compose -f docker-compose.prod.yml up -d --no-deps caddy
  sudo docker compose -f docker-compose.prod.yml ps    # postgres/redis uptime unchanged — confirms no new volume
  ```
  **Smoke test:** `/health`, `/cards?limit=1`, `/.well-known/oauth-authorization-server`, `/.well-known/oauth-protected-resource/mcp` all 200; `/mcp` (GET) 405 — matches the Appendix A5 baseline. `docker compose logs --since 10m` for errors. Then persona chat memory recall, and `zynd sync` from the bridge. **Rollback:** `cd ~/memory-layer && sudo docker compose -f docker-compose.prod.yml up -d --no-deps api worker mcp cards caddy`. Keep old images — **no `docker image prune` for 7 days**.
- **M4.6 USER:** 7-day soak, deploying only from the monorepo per `docs/monorepo/DEPLOY.md`. Leave the old folders alone.
- **M4.7 USER (day +7):** rename the old folders to `*.pre-monorepo` (keep 30 days, then delete); `sudo docker image prune` (dangling only).

### M5: Retire the old repos and update docs

- **M5.1 AGENT (after OK):** a "Moved to zyndai/platform → `<path>`" README commit in each old repo, following its existing push policy — cards → main; persona → dev, then you merge to main; memory → a branch, then you open the PR.
- **M5.2 USER (day +7):** remove the persona dev webhook and any deploy keys from the old repos, then Settings → Danger Zone → **Archive** each one. Never delete.
- **M5.3 USER:** fix the public link in the `docs` repo, `v2/resources/support.md:45`.
- **M5.4 AGENT:** zynd-bridge `scripts/update-memory-routes.sh` → default to `${ZYND_MONOREPO:-../zynd}/packages/contracts/memory-routes.json` instead of running memory-layer directly; fix the comments in `tests/memory-contract.test.ts`; `npm test` must still pass 276; push to main per bridge's policy.
- **M5.5 AGENT:** update the LLD status line; update the memory notes so the push policy reads "monorepo `dev` / PR to `main`" and the Stage 2 repo references point at the monorepo paths; land the "port after" branches (`git switch -c <b> dev && git merge port/<repo>/<b>`, then a PR to `dev`), and delete the `port/*` refs once merged.

## 6. Working rules
- `git status` / `git pull --ff-only` on every source repo before starting. Never rewrite history in the existing working copies; all filtering happens on fresh clones in the scratchpad.
- **Execution convention:** moves and mechanical edits use git/shell commands (`git filter-repo`, `git mv`, `cp`, `sed`) or targeted `Edit` calls for a handful of lines — never the `Write` tool to reconstitute a file that already has content, which risks silent transcription drift and defeats `--path-rename`'s byte-identical-blob guarantee (verified in M1.4/M1.7). `Write` is only for genuinely new files (e.g. `packages/db/README.md`, `docs/monorepo/IMPORT.md`).
- Don't push anything to the old repos except the M5.1 "moved" README, and that only with the user's OK.
- **No server, GitHub-settings, DNS, Vercel or prod-DB actions by the agent.** Commands go to the user.
- **Don't commit secrets or tool folders.** Scan before the first push (M1.8).
- **Never `docker image prune` or delete the old server folders within the first 7 days** of cutover — they're the rollback.
- **After each phase, report:** what was done, test results against the baselines, anything that needs a decision, and the exact commands the user must run, in order.

---

## Appendix A: Inventory (2026-09-25)

### A1. Branches (GitHub = local refs, checked 2026-09-25 21:10 IST). "+N" = commits not in main.

**agent-persona** (main `b7aada4`, 2026-09-23; 272 commits across all refs, 348 files on dev)

| Branch | Last commit | State vs main | Recommendation |
|---|---|---|---|
| `dev` | 2026-09-24 `c6e2948` | +1 (security fix: auth on all routes) | **Merge dev→main before the freeze** |
| `feat/people-smart-sections` | 2026-08-24 | +1, **open PR #18 → dev** (0xSY3) | Decide: merge into dev before the freeze, or port after |
| `feat/mcp-connect-ux-v2` | 2026-08-24 | 3 unique (12 already in main) | Port after, or abandon |
| `feat/mcp-connect-ux` | 2026-08-19 | 4 unique, looks superseded by v2 | Abandon |
| `fix/card-visibility-toggle` | 2026-08-18 | 3 unique, but 4 of 5 files in `e3a5ae7` already match main | Abandon (landed another way) |
| `ux-revamp` | 2026-04-23 | 1 commit, 49 files, 240 behind | Abandon |
| `feat/compliance-linkedin-google-data-controls`, `fix/sidebar-search` | Aug | Patch-equivalent in main (squash-merged) | Nothing to do |
| 11 others (`group`, `zynd-mcp`, `retire-google-doc-brief`, …) | Apr–Aug | Ancestors of main | Nothing to do |

**memory-layer** (main `4bcefdf`, 2026-09-16; main is protected by a ruleset; **no open PRs**)

| Branch | Last commit | State | Recommendation |
|---|---|---|---|
| `fix/bridge-contract-and-uid` | 2026-09-25 `e08cd2d` | +1, **no PR opened yet** | **Open the PR and merge before the freeze, then deploy it** |
| `fix/cors-dev-persona` | 2026-08-19 | +1: allow the `dev.persona.zynd.ai` origin | Merge before the freeze (1 line), or port |
| `fix/notion-not-connected-and-test-reliability` | 2026-08-26 | +5: `auth_user` routing, Notion error handling, Makefile `~/zynd`→`~/memory-layer` fix | Port after. The Makefile part is superseded by M2.3 |
| `twitter-source-tags` | 2026-08-26 | +1 (source_system tags). The zynd-deployer box's memory clone is on this branch | Port or abandon |
| `dev` + 12 others | ≤2026-09-16 | Merged | Nothing (the monorepo `dev` replaces it) |

**zynd-cards** (main `88bd60d`, 2026-09-25): `feat/refresh-memory-endpoint` and `fix/publish-owner-and-search` are both merged.

**Not moving:** zynd-bridge main `7f1acd2`. dashboard `fix/card-claim-token` is needed by the cards move but doesn't block the freeze.

**Other facts:**
- No tags, submodules or LFS in any repo.
- No `.github/` in any repo today, so there is no CI yet. memory-layer had one once; it survives only in history.
- Commit counts: persona 247 on main (272 across all refs), cards 43, memory 95 on main (103 across all refs).

### A2. Where every top-level entry goes

**agent-persona**

| Today | Monorepo path | Why |
|---|---|---|
| `backend/` | `services/persona-api/` | — |
| `contextaware/` | `services/persona-api/contextaware/` | Its only importer is `backend/mcp/server.py:10` (via `sys.path`). `orchestrator.py` imports that at startup |
| `webapp/` | `apps/persona-web/` | — |
| `db/` (migrations 0000–0004, `sql/policies.sql`) | `apps/persona-web/db/` | Its only consumer is the webapp's `db:policies` script (`../db/sql/policies.sql`). Frozen by cards-move P1 |
| `README.md` | `apps/persona-web/README.md` | It's the create-next-app README, moved out of webapp/ in `8b645ef` |
| `CLAUDE.md`, `AGENTS.md` | `services/persona-api/` | Persona-wide agent docs. M2.6 rewrites their git-workflow section |
| `GEMINI.md`, `.cursorrules`, `.windsurfrules`, `.mcp.json`, `.opencode.json` | repo root | Generic code-review-graph MCP config that tools read at the root |
| `.gitignore` | `/.gitignore` | Anchored paths rewritten in M1.9 |
| `docs/`, `architecture.md`, `A2A.md`, `GROUPS.md`, `theme.md`, `AUDIT_REPORT.md`, `IMPLEMENTATION_MEMORY_BRIEF.md` | `docs/persona/` | Historical text is left as it is |
| `ecosystem.config.js`, `ecosystem.dev.config.js`, `ecosystem.config.js.bak-2026-05-26` | `infra/persona-box/` | The `.bak` gets deleted in a later cleanup |
| `package-lock.json` (empty, `"packages": {}`) | `archive/` → deleted at HEAD in M1.9 | A root lockfile would change Next.js's workspace-root detection |
| `.claude/scheduled_tasks.lock` (tracked by accident; `/.claude/` is gitignored) | `archive/` → deleted at HEAD in M1.9 | — |
| History only: `memory/` (removed in `9c3ed20`), `prisma/`, `images_for_debug/` | `archive/agent-persona/…` (history only) | Keeps the monorepo root clean in old commits |
| Untracked: `memory/` (only `__pycache__`), `.code-review-graph/`, `.DS_Store` | not moved | Nothing imports `memory` (checked) |

Tracked junk that moves as-is, for a later cleanup PR: `backend/.next/trace*`, `backend/telegram_users.json` (1 entry, replaced by a DB table), `backend/supabase/.temp/*`.

**zynd-cards:** every entry goes under `services/cards-api/`. That covers `.dockerignore`, `.env.example`, `.env.prod.example`, `.gitignore`, `Dockerfile`, `api/`, `config.py`, `db/`, `docker-compose.prod.yml` (standalone, not used on the box), `main.py`, `models/`, `publish/`, `requirements.txt`, `scraping/`, `scripts/`, `services/`, `synthesis/`, `tests/` and `x/`.

**memory-layer:** `Caddyfile` and `docker-compose.prod.yml` go to `infra/api-box/`. Everything else goes under `services/memory/`: `.dockerignore`, `.env.example`, `.gitignore`, `Dockerfile`, `Makefile`, `app/`, `docker-compose.yml` (local dev), `mcp-test-prompts.txt`, `openapi/`, `pyproject.toml`, `render.yaml`, `scripts/`, `sql/`, `tests/`, and the history-only `.github/`.

Note: memory's `.gitignore` ignores `*.md` and `docs/`. So a new `services/memory/README.md` needs `git add -f`, or a change to that `.gitignore`.

### A3. Hard-coded paths

| File (new path) | What | Breaks? | Fix |
|---|---|---|---|
| `services/persona-api/mcp/server.py:10` | `Path(__file__).resolve().parent.parent.parent / "contextaware"` | **Yes** (would point to `services/contextaware`); the app wouldn't start | `.parent.parent / "contextaware"` (M1.9) |
| `apps/persona-web/package.json:10` | `psql … -f ../db/sql/policies.sql` | **Yes** | `-f db/sql/policies.sql` (M1.9) |
| `/.gitignore` | 15 anchored `/backend/…` and `/webapp/…` rules | Silently stops ignoring | Rewrite to the new paths, and add `!.env.example` / `!.env.*.example` (M1.9) |
| `infra/api-box/docker-compose.prod.yml` | `build: .` ×3, `env_file: .env.prod` ×3, cards `context:/env_file: /home/ubuntu/zynd-cards…`, **project name taken from the directory** | **Yes, dangerously** (see risk R1) | M2.1 |
| `infra/api-box/Caddyfile` | `./Caddyfile` bind mount, relative to the compose file | No (they move together) | — |
| `infra/persona-box/ecosystem.config.js` | `cwd`/`script` = `/home/ubuntu/agent-persona/{backend,webapp}` | Yes, at cutover | M2.2 |
| `infra/persona-box/ecosystem.dev.config.js` | `DEV="/home/ubuntu/agent-persona-dev"`, `${DEV}/backend`, `${DEV}/webapp` | Yes, at cutover | M2.2 |
| `services/memory/Makefile:10-13` | Deploy rsyncs to `/home/ubuntu/zynd/{app,sql}` and runs `cd ~/zynd`. **This is already wrong on main** (the fix `d3b7f84` is on an unmerged branch) | Yes | M2.3 |
| `services/memory/render.yaml` | `dockerfilePath: ./Dockerfile`, relative to the repo root on Render | Only if Render is used (Q9) | Render "Root Directory" |
| persona box: `persona-dev-webhook` script | Not in git; presumably pulls `~/agent-persona-dev` | Yes, at cutover | M4.3 |
| `/etc/caddy/Caddyfile` (persona box) | Unknown whether it has any `root`/`file_server` paths | Q7 | — |
| `services/persona-api/{CLAUDE,AGENTS}.md` | `cd backend`, `cd webapp`, deploy dirs, the "push to dev of agent-persona" rule | Wrong instructions | M2.6 |
| zynd-bridge `scripts/update-memory-routes.sh` | Default `../memory-layer` | After the archive | M5.4 |

**Safe as they are** (paths are relative to their own service):
- persona `config.py` `.env`, `tests/conftest.py`, and `scripts/*` `sys.path` (all relative to the backend root)
- memory `app/schema_apply.py`, `tests/conftest.py` `parents[1]/"sql"` and `scripts/apply_schema.sh`
- cards `config.py` and `scripts/seed_profiles.py`
- both Dockerfiles and `.dockerignore` files (build context = the service dir)
- webapp `tsconfig`/`next.config` (nothing outside the app)

**Must NOT change (these are data, not paths):**
- `source_system="agent-persona"` and `"agent-persona-remember"`
- the string `"See agent-persona/architecture.md"` in `card.py`
- the `"agent-persona": "Chat"` label in the webapp

### A4. Test baselines (2026-09-25, Python 3.12.14, pytest 9.1.1)

| Suite @ SHA | Result | Known failures |
|---|---|---|
| persona backend @ `c6e2948` (dev), with local `backend/.env` | **313 passed, 5 failed** | `test_linkedin_scraper_memory_sync` ×2, `test_memory_fact_ref::test_make_jwt_has_required_claims`, `test_twitter_scraper` ×2 |
| persona webapp @ `c6e2948` (stale local node_modules) | tsc **5 errors** (all missing `@dicebear/*` / qrcode types, i.e. a stale install) · eslint **88 problems (57 errors, 31 warnings)** | Re-baselined in M1.10 after a fresh `npm ci` |
| cards @ `88bd60d` | **89 passed, 2 failed** | `test_x_bot` ×2 |
| memory @ `e08cd2d` (PR branch), `-m "not integration"` | **203 passed, 9 failed, 81 deselected** | `test_concurrency_and_isolation` ×2, `test_oauth_integrations` ×5, `test_user_journeys` ×2 |
| bridge @ `7f1acd2` (not moving; checks the contract) | **276 passed** | — |

Secret scan (the full `git log --all -p` of all 4 repos, for AWS, OpenAI/Anthropic, JWT, PEM, GitHub, Slack, Google, `sb_secret_` and Telegram token patterns): **0 real hits**. The 3 matches were a lockfile hash, a `your_s…` placeholder and test fixtures. No `.env`, `.pem` or key file has ever been committed.

### A5. Server facts (DNS + `AWS-*-Report.md` in `p3ai/`)

- **Two hosts.**
  - **zynd-api** `54.147.91.20` (t3.medium x86, **4.1 GB disk free, 79% used**) runs api.zynd.ai: the Docker compose stack from `~/memory-layer` plus cards built from `~/zynd-cards`. It also holds `~/zynd` (a dead second memory copy per `d3b7f84`), `~/zynd-src` and `~/zynd-cards.old`.
  - **zynd-deployer** `13.219.55.137` (ARM64, right-sized to t4g.large with 8 GB) runs persona.zynd.ai and dev.persona.zynd.ai. Its pm2 processes are `api`, `web`, `api-dev`, `web-dev`, **`persona-dev-webhook`**, `deployer-web` and `deployer-worker`, fronted by system Caddy. It also has a `~/memory-layer` clone on `twitter-source-tags` running Postgres :5433 and Redis :6380.
- memory reaches prod by **rsync + compose** (`make deploy` from an SSH-allowlisted IP), not by `git pull`. So the box's checkout can differ from git.
- Endpoint status on 2026-09-25, to compare against after cutover:

  | Endpoint | Status |
  |---|---|
  | api `/health` | 200 |
  | `/cards?limit=1` | 200 |
  | `/.well-known/oauth-authorization-server` | 200 |
  | `/.well-known/oauth-protected-resource/mcp` | 200 |
  | `/mcp` (GET) | 405 |
  | persona `/` | 200 |
  | dev.persona `/` | 200 |

  The persona backend's `/health` is only reachable at `127.0.0.1:8000` and `127.0.0.1:8001`.
- The only public link to a moving repo: `docs` repo, `v2/resources/support.md:45` → github.com/zyndai/agent-persona.

---

## Appendix B: Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | **Compose project name.** It comes from the folder the file sits in. Running from `infra/api-box/` creates project `api-box`, with a new empty Postgres volume and a second Caddy fighting for ports 80/443 | Put `name: memory-layer` at the top of the file (M2.1). Diff `docker compose config` old vs new before `up` (M4.5) |
| R2 | `/home/ubuntu/zynd` already exists on zynd-api (the dead memory copy) | Check out to `~/zyndai-zynd-platform` (prod) and `~/zyndai-zynd-platform-dev` (persona dev) |
| R3 | Prod may not be running what we import: memory is deployed by rsync, cards has a pending redeploy (H7), and the audit says persona prod `~/agent-persona` is on **dev** | M0.5: bring each prod up to its import SHA *before* the freeze. M4 prechecks compare the box HEAD and `git status` with the IMPORT SHAs |
| R4 | A private repo breaks anonymous pulls on the persona box. **On GitHub Free, private repos can't have branch protection or rulesets** | Read-only deploy key per box (M3.6/M4.1). Q10 covers the plan |
| R5 | A new venv could pull newer dependencies, since requirements use unpinned `>=` | Install the new venv from `pip freeze` of the running venv (M4.2/M4.4) |
| R6 | 4 GB free on zynd-api; `compose build` makes new images | `df -h` precheck. Remove `~/zynd-cards.old` and `~/zynd-src` only after Q5. Don't prune old images for 7 days (they are the rollback) |
| R7 | Commits land in the old repos during the freeze | M1 is a re-runnable script. M3.1 re-checks `ls-remote` against the freeze SHAs and re-imports if they moved |
| R8 | The persona dev webhook listener may check `repository.full_name` or a path | M4.3 edits the script, and you paste it first (Q2) |
| R9 | Every CI job would be red on day one (known failures) | Deselect the known failing test IDs in the workflows (listed, as debt). Lint is non-blocking until the 57 errors are fixed |

## Appendix C: Questions for you (only the servers or you can answer)

Run these read-only commands and paste the output (redact secrets).

**Q1.** Which branch and SHA does persona **prod** run? The audit says `dev`; CLAUDE.md says `main`.
`git -C ~/agent-persona rev-parse --abbrev-ref HEAD; git -C ~/agent-persona log -1 --oneline`, and the same for `~/agent-persona-dev`.

**Q2.** How does the dev auto-deploy work?
`pm2 describe persona-dev-webhook | grep -E "script path|exec cwd|args"`, then `cat` that script. Also: which webhook on github.com/zyndai/agent-persona → Settings → Webhooks points at it, and do you still have its secret?

**Q3.** How do the boxes authenticate to GitHub? zynd-cards is private, so zynd-api must have a key or token.
`git -C ~/zynd-cards remote -v; ls ~/.ssh; grep -i -A3 github ~/.ssh/config` on both boxes.

**Q4.** What state is zynd-api in?
```
for d in memory-layer zynd-cards zynd zynd-src zynd-cards.old; do echo "== $d"; git -C ~/$d rev-parse --abbrev-ref HEAD; git -C ~/$d log -1 --oneline; git -C ~/$d status --porcelain | head -5; done
sudo docker compose ls; sudo docker volume ls; ls -a ~/memory-layer | grep '^\.env'; df -h /; sudo docker system df; docker compose version
```

**Q5.** Does anything still use `~/zynd`, `~/zynd-src` or `~/zynd-cards.old` on zynd-api?
`sudo docker ps -a --format '{{.Names}}  {{.Label "com.docker.compose.project.working_dir"}}'`

**Q6.** What uses the memory-layer stack on zynd-deployer (branch `twitter-source-tags`, Postgres :5433)? It's out of scope and will be left alone unless you say otherwise.

**Q7.** Does the persona box's Caddyfile point into the repo folders?
`sudo grep -nE "home/ubuntu|root |file_server|import" /etc/caddy/Caddyfile`

**Q8.** Does any cron job or systemd unit reference the old folders? Run on both boxes:
`crontab -l; sudo grep -rlE "agent-persona|memory-layer|zynd-cards" /etc/systemd/system /etc/cron* 2>/dev/null`

**Q9.** Is `render.yaml` in use (any Render service connected to zyndai/memory-layer)? Is any Vercel project connected to agent-persona?

**Q10.** Is the zyndai GitHub org on **Free or Team**? A private repo with a protected `main` (D2+D5) needs Team (about $4 per user per month). On Free: upgrade, keep `main` unprotected (a team rule only), or reconsider D2.

**Q11.** The branch decisions in Appendix A1: merge before the freeze / port after / abandon. My recommendations are in the table.

**Q12.** Default branch of zyndai/platform: `dev` (recommended, since everyone targets it) or `main`?

**Q13.** Are Actions minutes on a private repo OK (the Free org quota is 2,000 minutes a month)?

## Appendix D: Effort

| Phase | Who | Effort |
|---|---|---|
| M0 | USER | 1–2 h (merges, deploys, answering Q1–Q13) |
| M1 | AGENT | 2–3 h (script, parity checks, tests) |
| M2 | AGENT | 3–4 h |
| M3 | USER + AGENT | 30–45 min of clicks, 15 min push and CI |
| M4 | USER | 2–3 h hands-on across both boxes (dev → prod → api box), then a 7-day soak |
| M5 | AGENT + USER | ~1 h |

Freeze window about 1.5–2 working days from M1 to the end of M4.
