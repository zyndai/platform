# Agent-Persona — End-to-End Audit Report

**Date:** 2026-08-05
**Scope:** Full-stack audit of the live production deployment (`api` on :8000, `web` on :3001, PM2-managed, `persona.zynd.ai`) — feature testing, integration health (Zynd Network, memory layer, Google/LinkedIn/Twitter/Notion), chat UX, privacy/OAuth scoping, and missing-feature research.
**Status:** **Findings only — nothing in this report has been fixed yet.** See "Next Steps" at the bottom.

---

## How this was tested

This was a production system already serving real traffic, so I deliberately avoided anything that could disrupt it or a real user's data:

- **No restarts, no live chat traffic injected as the real user, no new persona/agent registered on the public Zynd registry.** I did not mint an auth token to impersonate the account.
- **Static code audit** of the full request path (backend orchestrator → MCP tools → frontend renderers) using the code graph plus direct reads, cross-checked by three focused background passes (log mining, chat-pipeline trace, OAuth scope audit).
- **90 days of real production logs** (`pm2 logs api/web`, full history back to 2026-05-07) — this is genuine evidence of what's actually happening in prod, not synthetic testing.
- **Backend test suite**: `144 passed, 0 failed` (`backend/tests/`, run via the project's own `.venv`).
- **LinkedIn live posting/DM was skipped**, per your instruction (no Apify credits) — the LinkedIn *code path* (scopes, scraper, tool implementations) was still audited.

Confidence is high throughout — every claim below cites a file:line or a specific log line, not speculation. Where I'm inferring rather than certain, I've said so.

---

## Executive summary

The core architecture (HD key derivation, A2A protocol, the Zynd search/ranking logic, Google scope minimization on Docs/Gmail) is genuinely well engineered — there's careful, documented thinking throughout. But three things are quietly broken in ways a normal user would never get an error message for, and one advertised feature is completely inert:

1. **The memory layer / context graph — the personalization feature — does nothing right now.** A required shared secret was never set in production. Every "remember this," "what do you know about me," proactive nudge, daily brief, and digital-twin personalization call silently no-ops.
2. **The backend has been crashing from native memory corruption roughly once a day for the last 90 days**, including hours before this audit. Root cause is unidentified (glibc-level, not a Python traceback).
3. **Realtime updates have been broken since the very first day in the logs (2026-05-07).** A backend bug means meeting/connection notifications never reach the frontend via realtime, which is very likely *why* the dashboard resorts to polling 5 endpoints every 8-20 seconds, continuously, for as long as a tab stays open (one session ran 34 days straight).
4. **The "ugly mixed-format" chat bug you flagged is real and I found the exact cause**: two different search tools are both sanctioned by the system prompt for the same "find people" query, return incompatibly-shaped results, and land in two visually unrelated UI components — plus the prompt tells the model to write full prose descriptions of people *and* a card renders the same people, with no instruction to be brief (unlike the sibling code path, which does have that instruction).

None of this needed exotic testing to find — it's either currently happening in production logs or directly readable in the code. Details below, worst first.

---

## P0 — Critical

### 1. Memory layer / context graph is fully disabled in production

- `backend/config.py:127`: `MEMORY_LAYER_JWT_SECRET: str = os.getenv("MEMORY_LAYER_JWT_SECRET", "")` — **not present in `backend/.env`** (confirmed: zero matches).
- `backend/agent/memory_client.py:61-63`: `_is_enabled()` returns `bool(config.MEMORY_LAYER_JWT_SECRET)` — always `False` right now.
- Every memory call degrades silently: `get_context`, `ingest_turns`, `confirm_fact`, `forget_fact` all short-circuit to empty/no-op (`memory_client.py:116-117, 192-193, 229-230, 249-250`).
- The user-facing tools are explicit about it: `backend/mcp/tools/memory.py:35-36` — if a user says "what do you remember about me," the persona literally replies *"Memory layer is not configured. Ask your admin to set MEMORY_LAYER_JWT_SECRET."*
- **Blast radius is bigger than just memory Q&A** — six subsystems import `memory_client`/`memory_context` and depend on it for personalization: `agent/nudge_engine.py`, `agent/network_intros.py`, `agent/digital_twin.py`, `agent/daily_brief.py`, `agent/proactive_loop.py`, `mcp/tools/twin.py`. All of these are running with zero personal context right now.
- `load_memory_context`/`ingest_conversation` are wired into **every** chat turn (`agent/orchestrator.py:2546, 2640, 2672, 2849, 2936, 3027, 3058, 3222`) — so this isn't a rarely-hit path, it's on the hot path of every single conversation, just quietly doing nothing.

**Fix direction (not yet applied):** set `MEMORY_LAYER_JWT_SECRET` in `backend/.env` to match whatever the memory-layer service (`api.zynd.ai`) has configured, restart `api`, confirm with a real "remember that I like X" → "what do you remember about me" round trip.

### 2. Backend is crashing from native memory corruption, ~daily, for 3 months

From full log history (`api-err.log`, 2026-05-07 → 2026-08-05, i.e. today):

- **86 glibc heap-corruption aborts** — `malloc(): unsorted double linked list corrupted`, `double free or corruption (!prev / out)`, `corrupted double-linked list`, `free(): corrupted unsorted chunks`, `malloc(): invalid size`, `malloc(): unaligned tcache chunk detected`. Averaging ~1/day, still occurring — most recent at **2026-08-05T19:56:33**, i.e. hours before this audit started.
- Each one kills the process instantly with **no Python traceback and no graceful-shutdown log line** — PM2's `autorestart` brings it back 1-2s later, which is why this has been invisible: users see a brief hiccup, not an error page.
- This is a native-code-level bug (glibc heap corruption doesn't originate in Python), so the usual suspects are C-extension dependencies loaded in-process — `grpc`/`google-api-core`, crypto libs (Ed25519 signing runs constantly for the heartbeat manager), or similar. **Root cause is not identifiable from application logs alone** — this needs a core dump (`ulimit -c unlimited`) or running under `valgrind`/ASAN to pin down which library is corrupting the heap.
- Secondary effect: of **2,936 total API process restarts** in 90 days, only 86 (2.9%) are explained by these crashes and 163 (5.5%) by clean deploy-shutdowns — **the remaining 91% have no explanatory log line at all**, which suggests either very frequent external restarts (CI/deploy hitting the process with a hard signal that bypasses uvicorn's graceful shutdown) or something else not visible in these logs. Worth cross-checking against deploy tooling separately.

### 3. Realtime broadcasting has been broken since day one — and is very likely *why* the app polls so aggressively

- `backend/services/meetings.py:88-97` (`_broadcast`) and `backend/mcp/tools/zynd_network.py:1361-1372` (`request_connection`'s new-thread ping) both call `.channel("system_pings").send(...)` on a client returned by `config.get_supabase_anon()`.
- `backend/config.py:170-179`: `get_supabase_anon()` uses `create_client` (the **synchronous** Supabase client), which does not support realtime broadcast sends. Every call throws, is caught, and logged as a warning — never surfaced anywhere else.
- Confirmed in production logs: **27 occurrences of `[meetings] broadcast failed for {event}: ... "This feature isn't available in the sync client. You can use the realtime feature in the async client only."`**, spanning the *entire* log history from **2026-05-07T06:47:50 to 2026-08-05T18:27:30 (today)**. This has never worked.
- Direct consequence: meeting-proposal and new-connection notifications never reach the frontend in real time. Correlates with real `book_failed` states in the logs (e.g. `2026-05-07T06:48:25`, `2026-08-05T18:26:41`).
- The frontend's own realtime subscriptions (`webapp/src/components/MessagesPanel.tsx:205-221`) use the JS Supabase client, which *does* support broadcast — so the client side is fine; this is purely a backend bug (wrong client type for the send side).
- **Likely root cause of the polling load** (see P2 below): `webapp/src/contexts/DashboardActivityContext.tsx:202` polls `/api/todos/`, `/api/approvals/`, `/api/meetings/pending/*`, `/api/groups/invitations/incoming`, and `/api/persona/*/status` every **20 seconds** unconditionally — a design that makes sense as a fallback *if* realtime is assumed unreliable, but given realtime broadcasting has never actually worked on the backend, polling is currently the *only* way these views update at all.

**Fix direction:** use `create_async_client` (or Supabase's REST broadcast endpoint, which doesn't require the realtime websocket client) for server-side broadcasts in `meetings.py` and `zynd_network.py`. Once broadcasts genuinely work, the 20s poll can likely be relaxed significantly.

### 4. MCP tool server runs with security disabled in production

- `backend/mcp/server.py:107,113,233`: `create_mcp_server(disable_security: bool = True)` is called with no override — `mcp_server = create_mcp_server()` at module load.
- `contextaware/ContextAware.py:17-28`: when `disable_security=True`, the server explicitly logs `"Security disabled. NOT RECOMMENDED!"` — confirmed firing on every restart in production logs (`2026-08-05T19:56:33`, `21:11:20`, etc.), alongside a freshly generated (and then unused, since security is off) API key.
- I did not trace how/whether this MCP endpoint is network-reachable beyond localhost — that's the key open question determining real severity — but the library's own wording ("NOT RECOMMENDED") and the fact it's silently true in prod (not an explicit, documented decision anywhere I found) makes this worth a deliberate go/no-go decision rather than an accidental default.

---

## P1 — High priority

### 5. The chat UX bug you described ("find AI founders" → cards + text + say-hi cards) — full root cause

This is a **combination bug**, confirmed via code + a prior engineer's own comment describing the exact same symptom:

- **Two tools, one query, two shapes.** The system prompt (`backend/agent/orchestrator.py:2235, 2263`) tells the LLM it's fine to use *either* `search_zynd_personas` or `search_zynd_network(kind="persona")` for a people-search like "AI founders" ("prefer... " not "always"). They return differently-keyed rows — `{name, agent_id, description, ...}` (`zynd_network.py:1002-1010`) vs. `{name, entity_id, summary, ...}` (`zynd_network.py:645-659`) — and the frontend has a purpose-built card renderer for only one of them.
- **Five independent, tool-name-keyed renderers, no shared "search result" component:**
  | Tool | Renderer | Look |
  |---|---|---|
  | `search_zynd_personas` | `MatchCard` (`webapp/src/components/chat/MatchCard.tsx:26-62`, wired at `ChatInterface.tsx:209-237`) | avatar + name + reason + **"Say hi →"** button — this is almost certainly the "hi card" you're describing |
  | `search_zynd_network` | `AgentResultRow`/`ServicesPanel` (live-stream only, `ChatInterface.tsx:673-728`) | plain technical list row with a `type-{kind}` badge and "Call"/"View card" buttons |
  | `call_zynd_service`/`call_zynd_agent` | `GenUiResult` (`GenUiResult.tsx:393-497`) | generic shape-classified card (table/list/record/raw) |
  | everything else | plain `ReactMarkdown` | plain text |
- **A previous engineer already found and half-fixed this.** `ChatInterface.tsx:660-672` has a comment explaining that `search_zynd_personas` results used to render **three times in one turn — "once as this block, once as prose, once as MatchCard"** — and excludes it from the generic card path. But `search_zynd_network` (the *other* tool the prompt sanctions for the identical query) was never given the same treatment, so the exact bug the comment describes is still fully reachable whenever the model picks that tool instead.
- **The system prompt directly contradicts itself** on whether the model should re-describe results in prose: `orchestrator.py:2139-2152` and `:2266` say "keep it short, the card carries the detail," while `orchestrator.py:2279-2287` ("When presenting PEOPLE results") explicitly instructs 1-2 full sentences *per person* — for the same result set the card is about to render.
- **Bonus finding:** `search_zynd_network` results aren't persisted (`webapp/src/components/chat/types.ts:45-47`, "Local-only, never persisted") — reload the page or switch conversations and those cards vanish entirely, leaving whichever prose the model happened to write.
- **Bonus finding #2:** the tool's own careful docstring guidance (`zynd_network.py:578-587`, explicit "IMPORTANT" advice on when to use `kind="persona"`) never reaches the model at all — `ContextAware.register()` (`contextaware/ContextAware.py:47-54`) replaces it with a much shorter `description=` string passed at registration (`mcp/server.py:170-171`). The good guidance exists; the LLM has never seen it.

**Fix direction:** pick one tool as the canonical path for people-search (the code comment already argues for `search_zynd_personas`), stop sanctioning the other for the same intent, and remove the "write 1-2 sentences per person" instruction now that a card renders the same info — mirroring the brevity instruction that already exists for the network/service path.

### 6. Zynd Network heartbeat is failing constantly

- **3,273 heartbeat failures over 90 days** (~36/day), still occurring: `TimeoutError: timed out while waiting for handshake response` (2,007×, dominant), `InvalidStatus: server rejected WebSocket connection: HTTP 502` (1,022×, stopped 2026-05-27), `ConnectionClosedError` (88×), `InvalidMessage` (64×), `ConnectionRefusedError` (53×), DNS resolution failures (34×, 2026-06-08/10 outage window).
- Heartbeats are what keep a persona showing as "active" on the network for discovery/messaging — this directly affects the reliability of the exact feature you asked me to test ("find AI founders" and the underlying network). One explicit persona-search timeout is also logged (`2026-08-04T12:40:13`).
- This looks like an external dependency issue (connectivity to `dns01.zynd.ai`) more than an app bug, but it's frequent enough to be worth surfacing/monitoring rather than silently retrying forever.

### 7. Google Calendar: users who connected Gmail-only get silent, confusing 403s

- Calendar is an **optional, separately-granted** Google feature (`backend/api/oauth_routes.py:285-326`) — a user who only ever clicked "Connect Email" never has the `calendar` scope on their stored token.
- Nothing gates a Calendar API call on that scope actually being present. `mcp/tools/google/calendar.py:39-47` → `common.py:73-74` only checks *whether* a Google token exists, never *which scopes* it has — unlike the equivalent, already-existing pattern for Drive (`backend/api/brief.py:86-104`, `_has_drive_scope()`, which returns a clean, actionable error).
- Confirmed happening in production: `2026-08-05T18:26:41`, `HttpError 403 ... "Request had insufficient authentication scopes"` from the new conflict-detection code (`calendar.py:84-113`, added in the recent "detect scheduling conflicts" commit) → directly caused a real `book_failed` meeting state that day. Same gap affects `agent/smart_scheduling.py:267-273`, `agent/daily_brief.py:142-143`, and `agent/group_calendar.py:81-92`.
- Also in logs: a **second, distinct Calendar bug** — `2026-08-05T16:50:10/16:50:44`, `HttpError 400 "Invalid attendee email"` with 26 invalid-email entries in one response, suggesting a malformed attendee list gets passed through somewhere upstream of the API call.

**Fix direction:** add a `_has_calendar_scope()` check mirroring the existing Drive one, and return a "reconnect Google Calendar" prompt instead of letting the raw Google error surface.

### 8. Systemic missing input validation → 500s instead of 404s

- **27 tracebacks**, `postgrest.exceptions.APIError: invalid input syntax for type uuid`, across `api/groups.py:125`, `agent/persona_manager.py:565`, `services/meetings.py:380/403`, `api/matches.py:75` — none of these endpoints validate that a path param is actually a UUID before querying, so any non-UUID value (`/1`, `/test`, `/abc`, `/%20`, `/bogus-user-000`, `/999999`, …) 500s instead of a clean 400/404.
- This produced real, repeated 500s: `/api/groups/discover` (14×), `/api/groups/auto-join-candidates` (13×), `/api/persona/<id>/status` (9× legitimate + many fuzz variants), `/api/meetings/pending/<id>` (24× — the single most common 500 in the whole log).
- Some of this traffic looks like external scanning/fuzzing rather than real users, but real users can trivially hit the same bug (a stale bookmark, a copy-paste error, a client-side bug passing the wrong ID type).

### 9. OAuth token storage is plaintext

- `backend/services/token_store.py:46-58` stores `access_token`, `refresh_token`, and `raw_data` (a redundant copy of both) as plain `TEXT`/`JSONB` columns (`backend/db/schema.sql:38-50`). No `pgcrypto`, Supabase Vault, KMS, or app-level encryption anywhere in the schema or migrations.
- Protection today is entirely Row-Level Security (only the owning user or the service role can read a row) — reasonable as a baseline, but it means a leaked service-role key or a SQL-injection-class bug would expose live Gmail/Calendar/Drive/Twitter/LinkedIn/Notion tokens for every connected user in cleartext.

### 10. Google Sheets integration is completely broken for every user

- `backend/api/oauth_routes.py:292` still documents `"sheets"` as a valid `features` value, but `feature_map` (`:313-317`) has **no `"sheets"` key** — so the Sheets scope (`.../auth/spreadsheets`) is never requested for anyone, ever.
- `backend/mcp/tools/google/sheets.py` (`create_spreadsheet`, `append_to_sheet`, `read_sheet_values`) will 403 for every single user who tries it. This is a pure functional bug, not a scoping/privacy issue — flagging it here because it surfaced during the scope audit and would otherwise go unnoticed (no user has the scope to even discover it's broken).

---

## P2 — Medium

- **`httpx`/`httpcore` "Server disconnected" — 633 occurrences** across the log (49 as full tracebacks, the rest as caught/logged warnings in background pollers: `[brief_watcher] Poll failed` ×257, `[a2a poll] list_pending failed` ×195, `[a2a poll] fetch failed` ×13). This is the single largest recurring backend fault pattern — looks like a connection-pool idle-timeout mismatch between the app's httpx pool and Supabase's edge closing idle connections. `config.py:148-155` already added one retry for exactly this class of error; it's not fully covering it.
- **Aggressive polling, now with hard numbers.** `DashboardActivityContext.tsx:202` (`POLL_MS = 20_000`) confirmed against live traffic: sessions polling all 5 endpoints in lockstep every 8-20s, one running **continuously for 34 days** (still active as of today), another for 18 days. At these rates, a single open tab generates on the order of 15,000-20,000 requests/day. No `document.visibilitychange`-based backoff appears consistently applied. This is the direct downstream cost of finding #3 (broken realtime).
- **Twitter `offline.access` scope requested but the refresh flow was never implemented** (`mcp/tools/twitter.py` builds `tweepy.Client(access_token=...)` only, no refresh call anywhere) — access tokens will just go stale and force a full reconnect rather than silently refreshing. Not a privacy over-grant (grants no extra API surface), but a functional gap.
- **Google `openid`/`email`/`profile` scope requested but never consumed** (`oauth_routes.py:307` — no `id_token` decode or userinfo call anywhere for Google, unlike LinkedIn which does use its equivalent). Dead scope — should either be removed or actually used to prefill the user's name/avatar.
- **`page_publisher.py`**: `get_page_public` throws `'NoneType' object has no attribute 'data'` for missing slugs (5× in logs, 2026-07-27/28) — resolves to a correct 404 at the HTTP layer but logs an ugly, uninformative error; a simple null-check away from being clean.
- **A2A payment schema drift**: `persona_agents.pricing` column referenced in code doesn't exist in the DB (`agent/a2a_router.py:486`) — currently papered over by a fallback that treats every request as free (`[a2a payment] pricing column missing — treating addressee as free`, 2026-05-26), not an actual fix.
- **Next.js "Failed to find Server Action" — 55 occurrences** (2026-05-11 through at least 2026-06-03) with a mix of plausible real hash-format IDs (stale client bundle after a deploy) and obviously synthetic ones (`"x"`, `"y"`, 40 zeros — bot fuzzing). Worth a client-side error reporting tool (Sentry or similar) since these server logs can't see actual browser-side runtime errors at all — meaning frontend health here is likely under-observed.

## P3 — Low / polish

- Generic 403 error messages: `error_utils.py:75-80` classifies "insufficient scope" the same as generic "forbidden" ("check the permissions for this account") rather than the more specific, more actionable reconnect-hint already used for expired tokens (`:47-52`) — small change, meaningfully better UX for finding #7.
- `web-err.log` has a cosmetic lockfile-location warning on every one of 269 restarts (`package-lock.json` vs `webapp/pnpm-lock.yaml` both present) — one line in `next.config.js` (`outputFileTracingRoot`) silences it.
- Bot/scanner noise hitting `/api/.env`, `/api/v1/.env` … `/api/staging/.env`, `/api/graphql`, `/api/proxy` (~36 hits) — not an app bug, but suggests no WAF/rate-limiting in front of the API; worth considering given real secrets live in that file.
- `APP_SECRET_KEY` (`config.py:134`) is left at its literal placeholder default (`"change-me-in-production"`) — harmless today since nothing in the codebase actually reads this constant (confirmed: only definition, zero uses), but it's dead, confusing config that should either be wired up or removed.
- Two historical bad-deploy incidents (2026-05-15: a `NameError` from a forward-referenced Pydantic model, then an `IndentationError` in `orchestrator.py` that hit PM2's `max_restarts:10` ceiling and took the app down for ~42s) — both were syntax/import-level errors that a basic CI check (`python -m py_compile` or just running the test suite pre-deploy) would have caught before they reached prod.

---

## Privacy / OAuth scope audit (summary)

Full detail available on request; headline table:

| Provider | Scope requested | Verdict |
|---|---|---|
| Google — identity | `openid email profile` | **Unused** — requested, never consumed |
| Google — Calendar | full `.../auth/calendar` | **Broader than needed** — only `calendar.events`-level operations are ever performed (events CRUD + freebusy on `primary` only; no calendar/ACL management) |
| Google — Docs/Drive | `documents` + `drive.file` | **Good** — already deliberately minimized (git history shows this was narrowed from a broader Drive scope), matches actual usage exactly |
| Google — Gmail | `gmail.readonly` + `gmail.send` | **Good** — already deliberately minimized from `gmail.modify`, matches actual usage (no delete/label/modify calls exist) |
| Google — Sheets | *(not requested — see P1 #10)* | Functionally broken, not a privacy issue |
| LinkedIn | `openid profile email w_member_social` | **Good** — tightly matched; unimplemented DM features correctly request no scope |
| Twitter/X | `tweet.read/write users.read dm.read/write offline.access` | **Good** — every scope maps to an implemented call (offline.access is unused for refresh but grants no extra surface) |
| Notion | *(page-level grants, no OAuth scope string)* | N/A — Notion's own model enforces least privilege |

**Token storage:** plaintext (see P1 #9). **Recommendation:** narrow the Calendar scope to `calendar.events`, remove or wire up the unused Google identity scope, and consider encrypting `access_token`/`refresh_token` at rest (e.g. via Supabase Vault or an application-level envelope key) given what's at stake if that table ever leaks.

---

## What's already working well

Worth naming, since a report like this skews toward problems:

- **144/144 backend tests pass**, no regressions.
- The **Zynd persona search/ranking logic** (`zynd_network.py`) is genuinely sophisticated — coverage-based multi-concept scoring, compound-word stemming ("cofounder" matching "founders"), honest "matched on X, missing Y" reasoning surfaced to the LLM rather than invented explanations, and a documented pool-floor workaround for a real registry quirk. This is not a "just wire up an API call" integration — real thought went into making "AI founders" actually work.
- **Google Docs/Gmail/Drive scoping is a good example of least-privilege done right**, and the code comments show it was *deliberately* narrowed over time, not accidentally broad.
- **The duplicate-meeting-proposal guardrail works correctly** (rejects a second proposal on a thread that already has one pending, per logs).
- **Published-page visibility defaults to "unlisted"** (link-only), not public, and the public persona-card endpoint explicitly omits `webhook_url`, `public_key`, and brief-document fields (`api/persona.py:200-209`) — sensible default-deny thinking.
- The A2A protocol design doc (`A2A.md`) is unusually rigorous for a "living design doc" — deterministic state machines, cryptographic accountability, explicit permission layering. The gap is between this design and a couple of the implementation details above (e.g. the sync/async client mixup), not the architecture itself.

---

## Missing features / integration opportunities

You asked me to think about what a broader "AI user" of this product would expect that isn't here yet. Current integration surface: Google (Calendar/Docs/Drive/Gmail/Sheets\*), LinkedIn, Twitter/X, Notion, Telegram, and the Zynd Network itself. Gaps, roughly in order of fit with the existing "professional-networking AI persona" positioning:

1. **Slack / Discord** — the two places professional and builder communities actually live; a persona that can represent you in a community channel (not just DM-to-DM on Zynd) would be a natural extension of the existing A2A model.
2. **Microsoft 365 / Outlook + Teams** — a large fraction of the target audience (corporate professionals) isn't on Google Workspace at all; right now they can't connect Calendar/Email/Docs to their persona at all.
3. **A public booking/Calendly-style link** — the app already has real scheduling and free/busy logic (`group_calendar.py`, `smart_scheduling.py`); a shareable "book time with my persona" page is a small extension of what's already built, not a new capability.
4. **A standard, opt-in MCP endpoint for external AI agents** — right now the only way another AI can reach a persona is the proprietary Zynd A2A protocol. Exposing a scoped, per-user MCP server (the app already runs `ContextAware`/MCP internally — see P0 #4 on its current security posture) would let Claude, ChatGPT, or any other MCP-speaking agent interact with someone's persona directly, which is a very literal reading of "an AI user could use it."
5. **A lightweight CRM view of Zynd connections** — the product already tracks connections, threads, and match reasons; surfacing that as "people I've met through my persona" with notes/follow-up reminders is a small step from data that already exists.
6. **GitHub** — for a developer-leaning persona, surfacing activity/notifications would fit the existing "brief" concept (`daily_brief.py`) well.

I'd treat this section as directional product input, not an audited finding — happy to go deeper on any of these if useful.

---

## Next steps

This report is findings-only, as requested. Suggested order if you want me to start fixing (I'll wait for your go-ahead before touching anything):

1. **Memory layer secret** (P0 #1) — almost certainly a one-line `.env` change plus a restart; highest personalization impact for the least risk.
2. **Realtime broadcast client bug** (P0 #3) — small, well-isolated code fix (two call sites), and it's the likely root cause of the polling load (P2).
3. **Chat UX triple-format bug** (P1 #5) — the fix is a product decision (which tool wins) more than a hard technical problem; I can propose a specific change once you confirm the direction.
4. **Calendar scope gate + UUID validation** (P1 #7, #8) — mechanical, low-risk, fixes real recurring 500s.
5. **The native memory-corruption crashes** (P0 #2) — this one needs investigation (core dump / ASAN) before a fix is even possible to propose; flagging it as the thing most worth dedicated time given it's a live stability issue, not a UX one.

Let me know which of these (if any) you'd like me to act on, and in what order.
