<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.

---

## Deployment: prod + dev channels (PM2 + Caddy)

Two copies of this repo run on this box, both tracking `main` on GitHub:

| Channel | Code dir | pm2 apps | Backend | Web | URL |
|---|---|---|---|---|---|
| Prod | `/home/ubuntu/agent-persona` | `api`, `web` | 127.0.0.1:8000 | 127.0.0.1:3001 | https://persona.zynd.ai |
| Dev | `/home/ubuntu/agent-persona-dev` | `api-dev`, `web-dev` | 127.0.0.1:8001 | 127.0.0.1:3002 | https://dev.persona.zynd.ai |

- Caddy (`/etc/caddy/Caddyfile`) fronts both: `/api/*` → backend port, everything
  else → web port. PM2 apps: prod from `ecosystem.config.js`, dev from
  `ecosystem.dev.config.js`. After adding/removing apps: `pm2 save`.
- Env files are gitignored; each copy has its own `.env` / `.env.local`
  (dev's differs only in FRONTEND_URL, PUBLIC_PAGE_BASE_URL, NEXT_PUBLIC_API_URL
  → dev URL; ZYND_WEBHOOK_BASE_URL and OAuth redirect URIs stay on prod).
- Both copies share: Supabase project, LLM/API keys, memory layer, and the
  Zynd identity keypair (`~/.zynd/developer.json`). Duplicate heartbeats from
  the dev backend are expected and harmless at dev traffic levels.
- **Telegram**: only prod may register the webhook (one URL per bot). Never
  run `register_webhook()` on the dev backend. Inbound Telegram messages only
  reach prod; outbound notify works from both.

### Deploy flow (dev first, then prod)

1. Commit + push to `main` on GitHub.
2. **Dev copy** (`/home/ubuntu/agent-persona-dev`):
   - `git pull`
   - backend: `pip install -r requirements.txt` only if `requirements.txt` changed
   - webapp: **`npm run build` is REQUIRED after every webapp pull** — `next start`
     serves stale build artifacts otherwise; restart alone is not enough
   - `pm2 restart api-dev web-dev`
3. Smoke-test dev channel (chat turn, persona pages).
4. **Prod copy** (`/home/ubuntu/agent-persona`): repeat step 2 with
   `pm2 restart api web`.

`pm2 restart all` restarts everything (prod + dev + deployer) — prefer the
per-app names above.

## Git workflow (always follow, no exceptions)

This repo is checked out on `dev`, which auto-deploys to dev.persona.zynd.ai via webhook the moment you push. `main` is prod and is manual-merge-only by humans.

Whenever you finish ANY task that changes files in this repo, your LAST action before reporting done must be:

1. `git add -A`
2. `git commit -m "<short description>"`
3. `git push origin dev`

Do this automatically. Do NOT ask the user "want me to commit it?" or "should I push?" — just do it, then report what you shipped. Only skip this if the user explicitly said not to commit/push in their request. Never push to `main` (blocked by the pre-push hook anyway).
