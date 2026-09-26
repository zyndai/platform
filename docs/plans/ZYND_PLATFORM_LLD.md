# Zynd Platform: Low-Level Design (LLD)

| | |
|---|---|
| **Document** | LLD (3 of 3). Exactly what to change, where, and how |
| **Read with** | [ZYND_PLATFORM_ARCHITECTURE.md](./ZYND_PLATFORM_ARCHITECTURE.md) (decisions, findings F1–F17) · [ZYND_PLATFORM_HLD.md](./ZYND_PLATFORM_HLD.md) (flows) |
| **Status** | Proposed · 2026-09-23 |
| **Phases** | **Now** (§3) security and blockers · **Next** (§4) Zynd Account, connected data, cards app · **Later** (§5) people search, consent, consolidation |

All file:line references were checked against the repos on 2026-09-23 (main branches unless stated otherwise).

### Implementation status (updated 2026-09-24)

| Stage | Repo | Branch | State |
|---|---|---|---|
| Now §3.1 | agent-persona | `fix/route-auth-guards` → pushed to `dev` (`c6e2948`) | Done. **44** unguarded routes, not 39: the A2A router adds `push`, `agent-card.json` and `a2a/v1`, plus `/health` and a debug `/test-json` (removed). **Correction to §3.1.1:** about 32 webapp calls used a bare `fetch` with no token, so the webapp gained `authFetch()` in the same commit |
| Now §3.2 | zynd-cards + dashboard | `fix/publish-owner-and-search`, `fix/card-claim-token` | Done, not committed. **Extra finding:** `update_card` let *any* signed-in user claim *any* unowned card. It now requires the one-time claim token returned at anonymous publish (`X-Claim-Token`); older unowned cards are claimable only with `LEGACY_UNOWNED_CLAIM=true`. Refresh endpoints now require the owner |
| Now §3.3 | memory-layer | `fix/bridge-contract-and-uid` | Done, not committed. Path-param routes accept the caller's own Supabase id; other ids get 403 (stricter than `fb34842`, which dropped the check) |
| Now §3.4 | zynd-bridge | `fix/memory-contract` | Done, not committed. Bridge already queues facts in its outbox on failure, so only the contract test was added |
| Now §3.5 | Supabase console / prod env | — | **Needs a human**: see §3.5 |

---

## 1. Conventions

| Item | Convention |
|---|---|
| User ID | `zynd_uid`: UUID (`auth.users.id` in Zynd Account). Never email |
| Auth header | `Authorization: Bearer <session JWT \| memory OAuth token \| zk_… \| zsk_…>` |
| Acting for a user | `X-Zynd-User: <zynd_uid>`. Honored only for `zsk_` keys that have the `obo` scope |
| Tracing | `X-Request-Id`: generated at the edge if missing, propagated on every outbound call, logged |
| Error body | `{"error": {"code": "forbidden", "message": "…", "request_id": "…"}}` with 401 (no or invalid credential), 403 (valid credential but not allowed), 404, 409 (conflict, e.g. handle taken), 422, 429 |
| Route guard vocabulary | `public`, `user`, `self(param)`, `self_or_service(param, scopes)`, `thread_participant`, `task_participant`, `service(scopes)`, `admin` |
| Scopes | `memory.read`, `memory.write`, `findability.read`, `people.search`, `persona.internal`, `tokens.broker`, `events.deliver`, `obo` |
| Key formats | Personal `zk_live_<43 base62>` (`zk_test_` on staging). Service `zsk_live_<svc>_<43 base62>`. Stored as SHA-256 hex |
| Events | Envelope `{event_id, type, version, occurred_at, subject, producer, data}`, at-least-once delivery, idempotent consumers |

---

## 2. Repository and ownership map

| Repo | Runtime | Owns tables in | Changes in |
|---|---|---|---|
| `zynd-account` (**new**) | Library + SQL | Zynd Account DB: identity tables, views, outbox | Next |
| `agent-persona/backend` | FastAPI (pm2 `api`, :8000) | Zynd Account DB: persona tables | Now, Next, Later |
| `agent-persona/webapp` | Next.js (pm2 `web`, :3001) | — | Next, Later |
| `zynd-cards` (API) | FastAPI (compose `cards` on the api box) | Zynd Account DB: `agent_profile_cards`, `x_*` | Now, Next, Later |
| `zynd-cards/web` (**new**) | Next.js (Vercel) | — | Next, Later |
| `memory-layer` | FastAPI `api` :8000, `mcp` :8090, arq `worker` | memory DB | Now, Next, Later |
| `zynd-bridge` | Node CLI/daemon | local `~/.zynd` | Now, Next, Later |
| `dashboard` | Next.js (Vercel) | xmfj (unchanged) | Next (removal only) |

---

## 3. NOW: security fixes and blockers (target: 1–2 weeks)

### 3.1 agent-persona backend: guard every route (F1)

#### 3.1.1 New module `backend/api/guards.py`

This is an interim implementation that works **before** `zynd-account` exists. In Next it becomes a thin wrapper around `zynd_account.fastapi`.

```python
# backend/api/guards.py
import asyncio
import hmac
import logging
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

import config
from api.auth import get_current_user

log = logging.getLogger("zynd.guards")


@dataclass(frozen=True)
class Caller:
    user_id: str | None          # the user this request acts for
    service: str | None = None   # calling service, when service-to-service

    @property
    def is_service(self) -> bool:
        return self.service is not None


def _mark(fn):
    fn.__zynd_guard__ = True     # read by the route-coverage test (§10.3)
    return fn


def _service_name(request: Request) -> str | None:
    """NOW (interim): memory-layer already sends persona's SUPABASE_SERVICE_KEY as a bearer
    (memory-layer/app/services/persona.py:_svc_headers). Accept it as the 'memory' service.
    NEXT: replaced by the zsk_ allowlist (§4.4)."""
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    key = config.SUPABASE_SERVICE_KEY
    if key and token and hmac.compare_digest(token, key):
        return "memory"
    return None


@_mark
async def current_caller(request: Request) -> Caller:
    svc = _service_name(request)
    if svc:
        return Caller(user_id=request.headers.get("X-Zynd-User"), service=svc)
    user = await get_current_user(request)            # existing Supabase verification
    return Caller(user_id=user["id"])


def self_or_service(param: str = "user_id"):
    @_mark
    async def dep(request: Request, caller: Caller = Depends(current_caller)) -> Caller:
        target = request.path_params.get(param)
        if caller.is_service:
            log.info("obo service=%s user=%s route=%s", caller.service, target, request.url.path)
            return Caller(user_id=target, service=caller.service)
        if caller.user_id != target:
            raise HTTPException(status_code=403, detail="forbidden")
        return caller
    return dep


def self_only(param: str = "user_id"):
    @_mark
    async def dep(request: Request, caller: Caller = Depends(current_caller)) -> Caller:
        if caller.is_service or caller.user_id != request.path_params.get(param):
            raise HTTPException(status_code=403, detail="forbidden")
        return caller
    return dep


def ensure_actor(caller: Caller, claimed_user_id: str) -> None:
    """For bodies that carry a user id (register.user_id, meetings.actor_user_id)."""
    if caller.is_service:
        return
    if caller.user_id != claimed_user_id:
        raise HTTPException(status_code=403, detail="forbidden")


async def _my_ids(user_id: str) -> set[str]:
    sb = config.get_supabase()
    rows = await asyncio.to_thread(
        lambda: sb.table("persona_agents").select("agent_id").eq("user_id", user_id).limit(1).execute().data
    )
    return {user_id, *(r["agent_id"] for r in rows or [])}


@_mark
async def thread_participant(thread_id: str, caller: Caller = Depends(current_caller)) -> Caller:
    if caller.is_service:
        return caller                                     # NEXT: require obo + participant check
    sb = config.get_supabase()
    t = await asyncio.to_thread(
        lambda: sb.table("dm_threads").select("initiator_id,receiver_id").eq("id", thread_id).limit(1).execute().data
    )
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")
    if not ({t[0]["initiator_id"], t[0]["receiver_id"]} & await _my_ids(caller.user_id)):
        raise HTTPException(status_code=403, detail="not a participant")
    return caller


@_mark
async def task_participant(task_id: str, caller: Caller = Depends(current_caller)) -> Caller:
    if caller.is_service:
        return caller
    sb = config.get_supabase()
    t = await asyncio.to_thread(
        lambda: sb.table("agent_tasks").select("initiator_user_id,recipient_user_id").eq("id", task_id).limit(1).execute().data
    )
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if caller.user_id not in {t[0]["initiator_user_id"], t[0]["recipient_user_id"]}:
        raise HTTPException(status_code=403, detail="not a participant")
    return caller


def public(fn):
    """Decorator that documents a route as intentionally public (read by the coverage test)."""
    fn.__zynd_public__ = True
    return fn
```

Column names come from `backend/db/schema.sql`: `dm_threads.initiator_id` / `receiver_id` are TEXT and hold either a user uuid or an agent id; `agent_tasks.initiator_user_id` / `recipient_user_id` are UUIDs.

The `apiGet` / `apiPost` helpers send `Authorization: Bearer <session>` (`webapp/src/lib/api.ts:15–28`), but about 32 components called `fetch` directly without the token. They were switched to `authFetch()` in the same change, because the guards would otherwise have broken those screens.

#### 3.1.2 Route guard table (all 39 routes that currently have no auth)

| # | Route (prefix + path) | File:line | Guard | Extra check in handler |
|---|---|---|---|---|
| 1 | `GET /api/groups/by-invite/{token}` | `api/groups.py:1122` | `public` | rate-limit 30/min/IP |
| 2 | `GET /api/matches/{user_id}` | `api/matches.py:58` | `self_or_service()` | — |
| 3 | `POST /api/meetings` | `api/meetings.py:47` | `current_caller` | `ensure_actor(caller, req.actor_user_id)` + participant of `req.thread_id` |
| 4 | `POST /api/meetings/{task_id}/respond` | `api/meetings.py:62` | `task_participant` | `ensure_actor(caller, req.actor_user_id)` |
| 5 | `GET /api/meetings/thread/{thread_id}` | `api/meetings.py:77` | `thread_participant` | — |
| 6 | `GET /api/meetings/pending/{user_id}` | `api/meetings.py:84` | `self_or_service()` | — |
| 7 | `GET /api/meetings/{task_id}` | `api/meetings.py:90` | `task_participant` | — |
| 8 | `GET /api/oauth/linkedin/authorize` | `api/oauth_routes.py:140` | `public` + **connect code** (§3.1.5) | replace `?token=` |
| 9 | `GET /api/oauth/linkedin/callback` | `api/oauth_routes.py:164` | `public` (state-validated) | state single-use, 10 min TTL |
| 10 | `GET /api/oauth/github/authorize` | `api/oauth_routes.py:261` | same as #8 | |
| 11 | `GET /api/oauth/github/callback` | `api/oauth_routes.py:285` | same as #9 | |
| 12 | `GET /api/oauth/google/authorize` | `api/oauth_routes.py:382` | same as #8 | |
| 13 | `GET /api/oauth/google/callback` | `api/oauth_routes.py:462` | same as #9 | |
| 14 | `GET /api/oauth/notion/authorize` | `api/oauth_routes.py:503` | same as #8 | |
| 15 | `GET /api/oauth/notion/callback` | `api/oauth_routes.py:526` | same as #9 | |
| 16 | `GET /api/pages/public/{slug}` | `api/pages.py:126` | `public` | — |
| 17 | `GET /api/persona/{user_id}/status` | `api/persona.py:195` | `self_or_service()` | — |
| 18 | `GET /api/persona/{user_id}/public` | `api/persona.py:200` | `public` | only public fields |
| 19 | `POST /api/persona/register` | `api/persona.py:296` | `current_caller` | `ensure_actor(caller, req.user_id)` |
| 20 | `DELETE /api/persona/{user_id}` | `api/persona.py:331` | `self_only()` | — |
| 21 | **`DELETE /api/persona/{user_id}/account`** | `api/persona.py:342` | `self_only()` | **plus a live re-auth:** `sb.auth.get_user(token)` must succeed, and the session must be less than 10 min old (`iat`) |
| 22 | `PUT /api/persona/{user_id}/profile` | `api/persona.py:446` | `self_or_service()` | — |
| 23 | `GET /api/persona/{user_id}/brief` | `api/persona.py:459` | `self_or_service()` | — |
| 24 | `PATCH /api/persona/{user_id}/brief` | `api/persona.py:474` | `self_or_service()` | — |
| 25 | `POST /api/persona/{user_id}/agent-send` | `api/persona.py:496` | `self_or_service()` | — |
| 26 | `POST /api/persona/{user_id}/threads` | `api/persona.py:659` | `self_or_service()` | — |
| 27 | `GET /api/persona/threads/{thread_id}/permissions` | `api/persona.py:699` | `thread_participant` | — |
| 28 | `PATCH /api/persona/threads/{thread_id}/permissions` | `api/persona.py:711` | `thread_participant` | caller edits only **their own side's** permissions |
| 29 | `PATCH /api/persona/threads/{thread_id}/status` | `api/persona.py:747` | `thread_participant` | only the receiver may accept or decline |
| 30 | `PATCH /api/persona/threads/{thread_id}/mode` | `api/persona.py:812` | `thread_participant` | only your own side's mode |
| 31 | `GET /api/persona/search` | `api/persona.py:850` | `public` | rate-limit; public fields only |
| 32 | `GET /api/persona/avatars` | `api/persona.py:867` | `public` | cap `ids` at 50 |
| 33 | `POST /api/public/ask` | `api/public_ask.py:234` | `public` | rate-limit |
| 34 | `GET /api/public/ask` | `api/public_ask.py:243` | `public` | rate-limit |
| 35 | `POST /api/public/search/people` | `api/public_search.py:98` | `public` | rate-limit; Later: respect `discoverability` |
| 36 | `GET /api/public/search/people` | `api/public_search.py:107` | `public` | same |
| 37 | `GET /api/public/openapi.json` | `api/public_search.py:320` | `public` | — |
| 38 | `POST /api/telegram/webhook` | `api/telegram.py:918` | `public` + **Telegram secret header** (§3.1.4) | — |
| 39 | `GET /api/telegram/register` | `api/telegram.py:938` | **remove**. Replace with `scripts/register_telegram_webhook.py` | — |

**How to apply a guard.** Add the dependency to the signature, for example:

```python
@router.delete("/{user_id}/account")
async def purge_account(user_id: str, caller: Caller = Depends(self_only())):
    ...
```

Rate limiting can use `slowapi` or a small Redis token bucket, keyed per IP and per user.

#### 3.1.3 Grep audit after the change
```bash
cd agent-persona/backend && pytest tests/test_route_guards.py -q   # §10.3; fails on any unguarded, unmarked route
```

#### 3.1.4 Telegram webhook secret (F2)
- New env var `TELEGRAM_WEBHOOK_SECRET`: 32+ random URL-safe characters.
- `scripts/register_telegram_webhook.py` calls:
  `POST https://api.telegram.org/bot<TOKEN>/setWebhook {"url": "<ZYND_WEBHOOK_BASE_URL>/api/telegram/webhook", "secret_token": TELEGRAM_WEBHOOK_SECRET}`
- In `telegram_webhook`:

```python
secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
if not (config.TELEGRAM_WEBHOOK_SECRET and hmac.compare_digest(secret, config.TELEGRAM_WEBHOOK_SECRET)):
    raise HTTPException(status_code=401, detail="bad webhook secret")
```

- **Rollout:**
  1. Deploy code that enforces the check only when the env var is set.
  2. Set the env var and run the script.
  3. Confirm updates arrive.

#### 3.1.5 Third-party OAuth "connect code" instead of `?token=` (F6)
- **Today:** the webapp opens `GET /api/oauth/<provider>/authorize?token=<Supabase JWT>`, and `_validate_token(token)` identifies the user (`api/oauth_routes.py:148`).
- **New endpoint:** `POST /api/oauth/connect-code` (guard `user`) returns `{"code": "<32B urlsafe>", "expires_in": 60}`. Store `{code_sha256 → user_id, expires_at}` in the existing pending-state store (`_store_pending_state`, backed by `patch_add_oauth_pending_state.sql`) with kind `connect`.
- **Authorize:** `GET /api/oauth/<provider>/authorize?code=<code>` consumes the code (single use), then proceeds as today.
- **Transition:** accept `token` for two weeks, logging a deprecation warning, then remove it.

### 3.2 zynd-cards: owner spoofing, duplicate route, search scaling

#### 3.2.1 Publish owner comes from the token (F3): `api/onboard.py:234`
```python
@router.post("/{job_id}/publish")
async def publish(job_id: str, body: PublishRequest, authorization: str | None = Header(default=None)):
    owner_email = verify_supabase_jwt(authorization) if authorization else None   # NEXT: zynd_account optional_user
    # body.owner_email is IGNORED (kept in the model only for backward compatibility)
    ...
    handle = await asyncio.to_thread(cards_service.insert_card, card, job.handle_github, job.handle_x,
                                     job.scrape_raw, user_intent, owner_email, body.custom_handle)
```

- An anonymous publish stays allowed and produces an **unowned, claimable** card.
- Log whenever `body.owner_email` is set and differs from the token, to measure attempted abuse.

#### 3.2.2 Remove the duplicate route (F14)
In `api/cards.py`, `refresh_memory` is defined at lines 228 **and** 268. FastAPI serves the first definition. Diff the two bodies, keep the correct one and delete the other.

#### 3.2.3 Search through the HNSW index (F11)
- **Migration** `db/patch_search_rpc.sql`:

```sql
create or replace function public.match_cards(query_embedding vector(1536), match_count int default 200)
returns table (id text, handle text, card jsonb, similarity double precision)
language sql stable as $$
  select c.id, c.handle, c.card, 1 - (c.embedding <=> query_embedding)
    from public.agent_profile_cards c
   where c.status = 'published' and c.embedding is not null
   order by c.embedding <=> query_embedding
   limit match_count;
$$;

create or replace function public.search_cards_fts(q text, match_count int default 200)
returns table (id text, handle text, card jsonb, rank real)
language sql stable as $$
  select c.id, c.handle, c.card, ts_rank_cd(c.search_tsv, websearch_to_tsquery('english', q))
    from public.agent_profile_cards c
   where c.status = 'published' and c.search_tsv @@ websearch_to_tsquery('english', q)
   order by 4 desc
   limit match_count;
$$;
```

- **Code:** in `services/search.py::search_agents`, replace `cards_service.list_published_rows(limit=1000)` with the union of the two candidate sets:
  - `sb.rpc("match_cards", {"query_embedding": query_vec, "match_count": 200})`
  - `sb.rpc("search_cards_fts", {"q": q, "match_count": 200})`

  Keep the existing scoring and filters on that union. When the query is filter-only (no `q`), use an indexed SQL filter query instead of a full scan.

### 3.3 memory-layer: fix the bridge contract and ID canonicalization (F9, F10)

#### 3.3.1 Port `POST /me/findability/declare-batch`
- Copy it from `origin/fix/notion-not-connected-and-test-reliability:app/main.py:407`.
- Request `{"declarations": [{"predicate": str, "value": str}]}`, capped at 50 items (bridge already sends `facts.slice(0, 50)`, `zynd-bridge/src/memory-client.ts:110`).
- Response `{"status": "ok", "declared": [...], "skipped": [{..., "reason": str}]}`.

```python
class DeclareBatchRequest(BaseModel):
    declarations: list[DeclareRequest] = Field(max_length=50)

@app.post("/me/findability/declare-batch")
async def declare_findability_batch(req: DeclareBatchRequest, user_id: str = Depends(current_user)) -> dict:
    from app.services.findability import declare
    declared, skipped = [], []
    for item in req.declarations:
        try:
            await declare(get_pool(), user_id, item.predicate, item.value)
            declared.append({"predicate": item.predicate, "value": item.value})
        except ValueError as exc:
            skipped.append({"predicate": item.predicate, "value": item.value, "reason": str(exc)})
    return {"status": "ok", "declared": declared, "skipped": skipped}
```

#### 3.3.2 Add `GET /me/whoami` (bridge calls it at `zynd-bridge/src/memory-client.ts:143`)
```python
@app.get("/me/whoami")
async def whoami(user_id: str = Depends(current_user)) -> dict:
    row = await get_pool().fetchrow(
        "SELECT id, email, display_name, supabase_user_id FROM users WHERE id = $1", user_id)
    return {"user_id": str(row["id"]), "zynd_uid": row["supabase_user_id"],
            "email": row["email"], "display_name": row["display_name"]}
```

#### 3.3.3 ID canonicalization (F10)
- Cherry-pick `fb34842` ("use auth_user for context/graph endpoints, not path param") onto `main`, and review `origin/fix/canonicalize-user-id-in-auth`.
- Persona should call `/me/context` and `/me/graph` rather than the `/context/{user_id}` style routes.
- Triage the other remote branches and either merge or close each one.

### 3.4 zynd-bridge: contract test and graceful degradation
- **Contract test.** memory's CI publishes `openapi.json`, which FastAPI serves at `/openapi.json` by default. Add `tests/contract.memory.test.ts` asserting that every path bridge calls exists there. The list is centralized in `src/memory-client.ts` as `MEMORY_PATHS`, e.g. `/ingest`, `/me/findability`, `/me/findability/suggestions`, `/me/findability/declare-batch`, `/me/matches`, `/me/whoami`.
- **Graceful degradation.** In `memory-client.ts`, treat a 404 from `declareBatch` / `getWhoami` as "feature unavailable": return an empty result, print a one-line warning, and don't crash `zynd sync`.

### 3.5 Ops (Now)

| Task | Steps |
|---|---|
| **Zynd Account config (aafo)** | 1. Auth → JWT Keys: create an **ECC (P-256)** standby key → rotate so it becomes current. The legacy HS256 key becomes "previously used"; revoke it after 24 h. 2. Providers: enable **Google**, **LinkedIn (OIDC)** and **Email** (magic link / OTP, "Confirm email" on). Don't expose a password UI. 3. URL config: Site URL `https://cards.zynd.ai`. Redirect URLs `https://cards.zynd.ai/**`, `https://persona.zynd.ai/**`, `https://dev.persona.zynd.ai/**`, `http://localhost:3000/**`, `http://localhost:3001/**`. 4. Enable **manual identity linking**. 5. Rename the project "zynd-account" |
| **Staging** | Create a Supabase staging project or branch with identical config. Stage memory and cards on a separate compose project (`api-staging.zynd.ai`) and persona on `dev.persona.zynd.ai` |
| **Prod env audit (F8)** | Record the *names* and *targets* (not the values) for `SUPABASE_URL` and `SUPABASE_JWT_SECRET` in cards, and `SUPABASE_URL`, `PERSONA_ENABLED`, `PERSONA_LOGIN_URL` in memory. Confirm which project cards verifies tokens against today |
| **Existing triggers** | Before adding the Next trigger: `select tgname from pg_trigger where tgrelid = 'auth.users'::regclass and not tgisinternal;` |

---

## 4. NEXT: Zynd Account, connected data, cards app

### 4.1 New repo `zynd-account`

```
zynd-account/
├── sql/
│   ├── 0001_identity.sql          # profiles, memberships, aliases, reservations, reserved words
│   ├── 0002_functions.sql         # handle_new_user trigger, set_handle, adopt_handle, touch_membership, generate_handle
│   ├── 0003_views.sql             # card_public, persona_public, person_public
│   ├── 0004_outbox.sql            # event_outbox, event_deliveries
│   └── 0005_backfill.sql          # profiles for existing users
├── py/zynd_account/               # pip: zynd-account
│   ├── session.py  service.py  fastapi.py  identity.py  keys.py  events.py  relay.py
│   └── tests/
├── ts/                            # npm: @zynd/account
│   └── src/{browser.ts, server.ts, cookies.ts, react.tsx, login.tsx, next/callback.ts, safe-next.ts}
└── README.md
```

#### 4.1.1 SQL: identity (`0001_identity.sql`)
```sql
create extension if not exists citext;

create table if not exists public.profiles (
  id                uuid primary key references auth.users(id) on delete cascade,
  handle            citext unique check (handle::text ~ '^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$'),
  display_name      text,
  avatar_url        text,
  headline          text,
  discoverability   text not null default 'members' check (discoverability in ('off','members','public')),
  claimed_legacy_at timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create table if not exists public.product_memberships (
  user_id          uuid not null references auth.users(id) on delete cascade,
  product          text not null check (product in ('cards','persona','memory','bridge')),
  first_seen_at    timestamptz not null default now(),
  last_seen_at     timestamptz not null default now(),
  onboarding_state jsonb not null default '{}'::jsonb,
  primary key (user_id, product)
);

create table if not exists public.handle_aliases (
  old_handle  citext primary key,
  user_id     uuid not null references auth.users(id) on delete cascade,
  created_at  timestamptz not null default now()
);

-- Handles held by entities that have no owner yet (e.g. unclaimed cards: reserved_by = 'card:<id>').
create table if not exists public.handle_reservations (
  handle       citext primary key,
  reserved_by  text not null,
  created_at   timestamptz not null default now()
);

create table if not exists public.reserved_words (word citext primary key);
insert into public.reserved_words(word) values
  ('admin'),('api'),('app'),('auth'),('login'),('logout'),('settings'),('create'),('directory'),
  ('find'),('search'),('tag'),('p'),('profile'),('persona'),('cards'),('zynd'),('help'),('support'),
  ('about'),('terms'),('privacy'),('security'),('www'),('mail'),('static'),('internal')
on conflict do nothing;

alter table public.profiles            enable row level security;
alter table public.product_memberships enable row level security;
alter table public.handle_aliases      enable row level security;
alter table public.handle_reservations enable row level security;

create policy profiles_read       on public.profiles for select using (true);
create policy profiles_update_own on public.profiles for update using (id = auth.uid()) with check (id = auth.uid());
revoke update on public.profiles from authenticated;
grant  update (display_name, avatar_url, headline, discoverability) on public.profiles to authenticated;

create policy memberships_read_own on public.product_memberships for select using (user_id = auth.uid());
create policy aliases_read         on public.handle_aliases      for select using (true);
-- handle_reservations / reserved_words: no policies → service_role only.
```

#### 4.1.2 SQL: functions (`0002_functions.sql`)
```sql
-- New user → profile row + account.created event.
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  insert into public.profiles (id, display_name, avatar_url)
  values (new.id,
          coalesce(new.raw_user_meta_data->>'full_name', new.raw_user_meta_data->>'name',
                   split_part(new.email, '@', 1)),
          coalesce(new.raw_user_meta_data->>'avatar_url', new.raw_user_meta_data->>'picture'))
  on conflict (id) do nothing;
  insert into public.event_outbox (type, subject, producer, data)
  values ('account.created', new.id, 'zynd-account',
          jsonb_build_object('email_verified', new.email_confirmed_at is not null));
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- Is a handle free for this user?
create or replace function public.handle_is_free(p_handle citext, p_user uuid)
returns boolean language sql stable security definer set search_path = public, pg_temp as $$
  select p_handle::text ~ '^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$'
     and not exists (select 1 from public.reserved_words where word = p_handle)
     and not exists (select 1 from public.profiles where handle = p_handle and id <> p_user)
     and not exists (select 1 from public.handle_aliases where old_handle = p_handle and user_id <> p_user)
     and not exists (select 1 from public.handle_reservations where handle = p_handle);
$$;

-- User-initiated rename (called with the user's JWT).
create or replace function public.set_handle(desired text)
returns citext language plpgsql security definer set search_path = public, pg_temp as $$
declare
  uid uuid := auth.uid();
  h   citext := lower(trim(desired));
  old citext;
begin
  if uid is null then raise exception 'not authenticated' using errcode = '28000'; end if;
  if not public.handle_is_free(h, uid) then raise exception 'handle unavailable' using errcode = '23505'; end if;
  select handle into old from public.profiles where id = uid for update;
  if old is not null and old <> h then
    insert into public.handle_aliases(old_handle, user_id) values (old, uid) on conflict (old_handle) do nothing;
  end if;
  delete from public.handle_aliases where old_handle = h and user_id = uid;   -- reclaiming an old handle
  update public.profiles set handle = h, updated_at = now() where id = uid;
  insert into public.event_outbox (type, subject, producer, data)
  values ('profile.updated', uid, 'zynd-account', jsonb_build_object('handle', h, 'old_handle', old));
  return h;
end $$;
revoke all on function public.set_handle(text) from public, anon;
grant execute on function public.set_handle(text) to authenticated;

-- Service-initiated: give a user a handle if they have none (card claim, backfill).
-- p_release releases a reservation the caller owns (e.g. 'card:<id>').
create or replace function public.adopt_handle(p_user uuid, p_handle text, p_release text default null)
returns citext language plpgsql security definer set search_path = public, pg_temp as $$
declare h citext := lower(trim(p_handle)); cur citext;
begin
  select handle into cur from public.profiles where id = p_user for update;
  if cur is not null then return cur; end if;
  if p_release is not null then
    delete from public.handle_reservations where handle = h and reserved_by = p_release;
  end if;
  if not public.handle_is_free(h, p_user) then
    h := public.generate_handle(h::text, p_user);
  end if;
  update public.profiles set handle = h, updated_at = now() where id = p_user;
  return h;
end $$;

create or replace function public.generate_handle(p_base text, p_user uuid)
returns citext language plpgsql security definer set search_path = public, pg_temp as $$
declare base text := trim(both '-' from regexp_replace(lower(coalesce(p_base,'user')), '[^a-z0-9]+', '-', 'g'));
        cand citext; i int := 0;
begin
  base := left(case when length(base) < 3 then base || '-zy' else base end, 34);
  loop
    cand := case when i = 0 then base else base || '-' || i end;
    exit when public.handle_is_free(cand, p_user);
    i := i + 1;
    if i > 9999 then cand := base || '-' || substr(md5(random()::text), 1, 5); exit; end if;
  end loop;
  return cand;
end $$;

create or replace function public.touch_membership(p_user uuid, p_product text)
returns boolean language sql security definer set search_path = public, pg_temp as $$
  insert into public.product_memberships as m (user_id, product) values (p_user, p_product)
  on conflict (user_id, product) do update set last_seen_at = now()
  returning (xmax = 0);            -- true on first insert
$$;

revoke all on function public.adopt_handle(uuid, text, text), public.generate_handle(text, uuid),
               public.touch_membership(uuid, text), public.handle_is_free(citext, uuid)
  from public, anon, authenticated;
grant execute on function public.adopt_handle(uuid, text, text), public.generate_handle(text, uuid),
                          public.touch_membership(uuid, text) to service_role;
grant execute on function public.handle_is_free(citext, uuid) to authenticated, service_role;
```

#### 4.1.3 SQL: shared read views (`0003_views.sql`)

These views are the contract for cross-product reads (ADR-12). Changing a view's columns requires a version bump (`card_public_v2`).

```sql
create or replace view public.card_public with (security_invoker = true) as
select c.id                                   as card_id,
       c.owner_id                             as zynd_uid,
       coalesce(p.handle::text, c.handle)     as handle,
       c.card->'identity'->>'name'            as name,
       c.card->'identity'->>'headline'        as headline,
       c.card->'identity'->>'location'        as location,
       c.card->'identity'->>'avatar_url'      as avatar_url,
       c.card->'skills'                       as skills,
       c.card->'working_on'                   as working_on,
       c.card->'can_help_with'                as can_help_with,
       c.card->'connect_with'                 as connect_with,
       c.card->'love_talking_about'           as love_talking_about,
       c.published_at
  from public.agent_profile_cards c
  left join public.profiles p on p.id = c.owner_id
 where c.status = 'published';

create or replace view public.persona_public with (security_invoker = true) as
select pa.user_id as zynd_uid, pa.agent_id, pa.name, pa.description, pa.capabilities
  from public.persona_agents pa
 where pa.active;

create or replace view public.person_public with (security_invoker = true) as
select p.id as zynd_uid, p.handle, p.display_name, p.avatar_url, p.headline, p.discoverability,
       cp.card_id, cp.location, cp.skills, cp.working_on,
       pp.agent_id as persona_agent_id, (pp.agent_id is not null) as has_persona
  from public.profiles p
  left join public.card_public    cp on cp.zynd_uid = p.id
  left join public.persona_public pp on pp.zynd_uid = p.id;
```

`security_invoker` means the caller's RLS applies. Backends use `service_role`. Browser reads see whatever the underlying RLS allows (published cards are public per `zynd-cards/db/schema.sql`).

#### 4.1.4 SQL: outbox (`0004_outbox.sql`)

The same DDL is also used in the memory DB.

```sql
create table if not exists public.event_outbox (
  id           bigserial primary key,
  event_id     uuid not null default gen_random_uuid() unique,
  type         text not null,
  version      int  not null default 1,
  subject      uuid,
  producer     text not null,
  data         jsonb not null default '{}'::jsonb,
  occurred_at  timestamptz not null default now()
);
create table if not exists public.event_deliveries (
  event_id        uuid not null references public.event_outbox(event_id) on delete cascade,
  subscriber      text not null,
  delivered_at    timestamptz,
  attempts        int  not null default 0,
  next_attempt_at timestamptz not null default now(),
  last_error      text,
  primary key (event_id, subscriber)
);
create index if not exists event_deliveries_due on public.event_deliveries (next_attempt_at) where delivered_at is null;
alter table public.event_outbox     enable row level security;   -- no policies: service_role only
alter table public.event_deliveries enable row level security;

-- Fan out on insert according to the subscription table.
create table if not exists public.event_subscriptions (type text, subscriber text, primary key (type, subscriber));
create or replace function public.fanout_event() returns trigger language plpgsql as $$
begin
  insert into public.event_deliveries(event_id, subscriber)
  select new.event_id, s.subscriber from public.event_subscriptions s where s.type = new.type;
  perform pg_notify('zynd_events', new.event_id::text);
  return new;
end $$;
create trigger event_outbox_fanout after insert on public.event_outbox for each row execute function public.fanout_event();

insert into public.event_subscriptions values
  ('account.created','memory'), ('account.deleted','cards'), ('account.deleted','memory'),
  ('profile.updated','memory'), ('profile.updated','cards'),
  ('card.published','memory'),  ('card.updated','memory'),
  ('persona.created','memory'), ('persona.created','cards'), ('connection.added','memory')
on conflict do nothing;
```

#### 4.1.5 SQL: backfill (`0005_backfill.sql`, run once)
```sql
insert into public.profiles (id, display_name, avatar_url)
select u.id,
       coalesce(u.raw_user_meta_data->>'full_name', u.raw_user_meta_data->>'name', split_part(u.email,'@',1)),
       coalesce(u.raw_user_meta_data->>'avatar_url', u.raw_user_meta_data->>'picture')
  from auth.users u
on conflict (id) do nothing;

-- After zynd-cards adds owner_id (§4.2.1): reserve every unowned card handle.
insert into public.handle_reservations (handle, reserved_by)
select lower(c.handle), 'card:' || c.id
  from public.agent_profile_cards c
 where c.owner_id is null and c.handle is not null
on conflict do nothing;

-- Give existing persona users a handle.
select public.adopt_handle(p.id, public.generate_handle(p.display_name, p.id))
  from public.profiles p where p.handle is null;
```

#### 4.1.6 Python library `zynd_account` (key modules)

```python
# zynd_account/session.py
import asyncio
from dataclasses import dataclass, field

import jwt
from jwt import PyJWKClient


class AuthError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True)
class ZyndUser:
    id: str                          # zynd_uid
    email: str | None
    provider: str | None
    claims: dict = field(default_factory=dict, repr=False)


class SessionVerifier:
    """Verifies Zynd Account session JWTs locally: ES256 via JWKS, iss/aud pinned."""

    def __init__(self, project_url: str, leeway: int = 30, jwks_ttl: int = 3600):
        self.issuer = project_url.rstrip("/") + "/auth/v1"
        self._jwks = PyJWKClient(self.issuer + "/.well-known/jwks.json", cache_jwk_set=True, lifespan=jwks_ttl)
        self._leeway = leeway

    async def verify(self, token: str) -> ZyndUser:
        try:
            signing_key = await asyncio.to_thread(self._jwks.get_signing_key_from_jwt, token)
            c = jwt.decode(token, signing_key.key, algorithms=["ES256"], audience="authenticated",
                           issuer=self.issuer, leeway=self._leeway,
                           options={"require": ["exp", "iat", "sub", "iss", "aud"]})
        except jwt.ExpiredSignatureError:
            raise AuthError(401, "token_expired", "session expired")
        except jwt.PyJWTError:
            raise AuthError(401, "invalid_token", "invalid session token")
        if c.get("role") != "authenticated" or c.get("is_anonymous"):
            raise AuthError(401, "invalid_token", "anonymous sessions are not accepted")
        email = (c.get("email") or "").strip().lower() or None
        return ZyndUser(id=c["sub"], email=email, provider=(c.get("app_metadata") or {}).get("provider"), claims=c)
```

```python
# zynd_account/identity.py: live check, lifted from memory-layer/app/supabase_auth.py
TRUSTED_PROVIDERS = frozenset({"google", "linkedin_oidc", "email"})

async def fetch_verified_identity(project_url: str, anon_key: str, token: str) -> tuple[str, str] | None:
    """(zynd_uid, verified_email) via GET /auth/v1/user, or None. Use for legacy claims,
    API-key creation and account deletion; never on the hot path."""
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(project_url.rstrip("/") + "/auth/v1/user",
                             headers={"Authorization": f"Bearer {token}", "apikey": anon_key})
    if r.status_code != 200:
        return None
    u = r.json()
    provider = (u.get("app_metadata") or {}).get("provider")
    if not u.get("email") or not u.get("email_confirmed_at") or provider not in TRUSTED_PROVIDERS:
        return None
    return u["id"], u["email"].strip().lower()
```

```python
# zynd_account/service.py
import hashlib, json
from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceClient:
    name: str
    scopes: frozenset[str]


class ServiceAllowlist:
    """SERVICE_CLIENTS='{"persona":{"sha256":["<hex>","<next-hex>"],"scopes":["memory.read","obo"]}}'"""

    def __init__(self, raw: str | None):
        self._by_hash: dict[str, ServiceClient] = {}
        for name, cfg in json.loads(raw or "{}").items():
            client = ServiceClient(name, frozenset(cfg["scopes"]))
            for h in cfg["sha256"]:
                self._by_hash[h.lower()] = client

    def lookup(self, key: str) -> ServiceClient | None:
        return self._by_hash.get(hashlib.sha256(key.encode()).hexdigest())


def service_headers(key: str, on_behalf_of: str | None = None, request_id: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {key}"}
    if on_behalf_of:
        h["X-Zynd-User"] = on_behalf_of
    if request_id:
        h["X-Request-Id"] = request_id
    return h
```

```python
# zynd_account/fastapi.py
from dataclasses import dataclass
from fastapi import Depends, HTTPException, Request


@dataclass(frozen=True)
class Principal:
    user_id: str | None              # zynd_uid acted for
    service: str | None = None
    scopes: frozenset[str] = frozenset()
    credential: str = "session"      # session | service


class ZyndAccount:
    def __init__(self, *, project_url: str, anon_key: str, product: str,
                 service_clients: str | None, supabase_admin=None):
        self.sessions = SessionVerifier(project_url)
        self.services = ServiceAllowlist(service_clients)
        self.product, self._admin = product, supabase_admin
        self._seen: dict[str, float] = {}                 # per-process membership cache (10 min)
        self.project_url, self.anon_key = project_url, anon_key

    async def principal(self, request: Request) -> Principal | None:
        auth = request.headers.get("Authorization", "")
        scheme, _, token = auth.partition(" ")
        token = token.strip() if scheme.lower() == "bearer" else ""
        if not token:
            return None
        if token.startswith("zsk_"):
            client = self.services.lookup(token)
            if not client:
                raise HTTPException(401, "invalid service key")
            obo = request.headers.get("X-Zynd-User")
            if obo and "obo" not in client.scopes:
                raise HTTPException(403, "obo not allowed for this service")
            return Principal(user_id=obo, service=client.name, scopes=client.scopes, credential="service")
        try:
            user = await self.sessions.verify(token)
        except AuthError as e:
            raise HTTPException(e.status, e.message)
        await self._touch(user.id)
        return Principal(user_id=user.id)

    # ---- dependencies -------------------------------------------------------
    def user(self):
        async def dep(request: Request) -> Principal:
            p = await self.principal(request)
            if p is None or p.service is not None or not p.user_id:
                raise HTTPException(401, "sign in required")
            return p
        dep.__zynd_guard__ = True
        return dep

    def optional_user(self):
        async def dep(request: Request) -> Principal | None:
            p = await self.principal(request)
            return p if p and p.service is None else None
        dep.__zynd_guard__ = True
        return dep

    def self_or_service(self, param: str = "user_id", scopes: tuple[str, ...] = ()):
        async def dep(request: Request) -> Principal:
            p = await self.principal(request)
            target = request.path_params.get(param)
            if p is None:
                raise HTTPException(401, "sign in required")
            if p.service:
                if not set(scopes) <= p.scopes or p.user_id != target:
                    raise HTTPException(403, "forbidden")
                return p
            if p.user_id != target:
                raise HTTPException(403, "forbidden")
            return p
        dep.__zynd_guard__ = True
        return dep

    def service(self, *scopes: str):
        async def dep(request: Request) -> Principal:
            p = await self.principal(request)
            if p is None or p.service is None or not set(scopes) <= p.scopes:
                raise HTTPException(403, "service credential required")
            return p
        dep.__zynd_guard__ = True
        return dep

    async def _touch(self, uid: str) -> None:
        """Record product membership (cached 10 min). On first sight, fire on_first_seen."""
        ...
```

`events.py` provides `emit(conn_or_sb, type, subject, data)`, which inserts into `event_outbox` in the caller's transaction. `relay.py` is the delivery loop (§4.10).

#### 4.1.7 TypeScript package `@zynd/account`
```ts
// src/cookies.ts
export function zyndCookieOptions() {
  return {
    domain: process.env.NEXT_PUBLIC_ZYND_COOKIE_DOMAIN || undefined,   // ".zynd.ai" in prod; unset locally
    path: "/",
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
  };
}

// src/browser.ts
import { createBrowserClient } from "@supabase/ssr";
export function createZyndBrowserClient() {
  return createBrowserClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { cookieOptions: zyndCookieOptions() });
}

// src/server.ts
import { cookies } from "next/headers";
import { cache } from "react";
import { createServerClient } from "@supabase/ssr";
export async function createZyndServerClient() {
  const store = await cookies();
  return createServerClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!, {
    cookieOptions: zyndCookieOptions(),
    cookies: {
      getAll: () => store.getAll(),
      setAll: (list) => { try { list.forEach(({ name, value, options }) => store.set(name, value, options)); } catch { /* RSC */ } },
    },
  });
}
export const getZyndUser = cache(async () => {
  const sb = await createZyndServerClient();
  const { data } = await sb.auth.getClaims();            // local JWKS verification
  return data?.claims ? { id: data.claims.sub as string, email: data.claims.email as string | undefined } : null;
});

// src/next/callback.ts: lifted from dashboard/src/app/(site)/auth/callback/route.ts
import { NextRequest, NextResponse } from "next/server";
export async function GET(request: NextRequest) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const next = safeNextPath(request.cookies.get("zynd_next")?.value) ?? safeNextPath(url.searchParams.get("next")) ?? "/";
  if (!code) return NextResponse.redirect(new URL("/login?error=callback", url.origin));
  const pending: { name: string; value: string; options?: Record<string, unknown> }[] = [];
  const sb = createServerClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!, {
    cookieOptions: zyndCookieOptions(),
    cookies: { getAll: () => request.cookies.getAll(), setAll: (l) => { pending.push(...l); } },
  });
  const { error } = await sb.auth.exchangeCodeForSession(code);
  const res = NextResponse.redirect(new URL(error ? "/login?error=callback" : next, url.origin));
  pending.forEach(({ name, value, options }) => res.cookies.set(name, value, options));
  res.cookies.delete("zynd_next");
  return res;
}

// src/safe-next.ts: lifted from dashboard/src/lib/auth/next-cookie.ts
export function safeNextPath(raw: string | null | undefined): string | null {
  if (!raw) return null;
  let v = raw; try { v = decodeURIComponent(raw); } catch { /* keep raw */ }
  return v.startsWith("/") && !v.startsWith("//") && !v.includes("\\") ? v : null;
}

// src/login.tsx
export function ZyndLogin({ providers = ["google", "linkedin_oidc", "email"], next = "/" }: Props) {
  const sb = useMemo(() => createZyndBrowserClient(), []);
  const redirectTo = `${window.location.origin}/auth/callback`;
  const setNext = () => { document.cookie = `zynd_next=${encodeURIComponent(safeNextPath(next) ?? "/")}; path=/; samesite=lax`; };
  const oauth = (provider: "google" | "linkedin_oidc") => { setNext(); sb.auth.signInWithOAuth({ provider, options: { redirectTo } }); };
  const magic = (email: string) => { setNext(); return sb.auth.signInWithOtp({ email, options: { emailRedirectTo: redirectTo } }); };
  /* render buttons + email field */
}
```

`ZyndAccountProvider` / `useZyndAccount` are adapted from `dashboard/src/hooks/useAuth.tsx`. They keep the `knownUserIdRef` de-duplication of repeated `SIGNED_IN` events and drop the developer-key logic.

### 4.2 zynd-cards API (Next)

#### 4.2.1 Migration `db/patch_owner_id.sql`
```sql
alter table public.agent_profile_cards add column if not exists owner_id uuid references auth.users(id) on delete set null;
create index if not exists agent_profile_cards_owner_idx on public.agent_profile_cards(owner_id);
create unique index if not exists agent_profile_cards_one_published_per_owner
  on public.agent_profile_cards(owner_id) where status = 'published' and owner_id is not null;
```

#### 4.2.2 Code changes

| File | Change |
|---|---|
| `config.py` | Add `ZYND_ACCOUNT_URL` (= Zynd Account `SUPABASE_URL`), `SUPABASE_ANON_KEY`, `SERVICE_CLIENTS`, `ZSK_CARDS`, `MEMORY_INTERNAL_URL` (default `http://api:8000`, the compose network). Remove `SUPABASE_JWT_SECRET` (after the dashboard cards routes are gone), `MEMORY_SERVICE_TOKEN`, `MEMORY_REFRESH_INTERVAL_HOURS` |
| `api/auth.py` | Replace with `za = ZyndAccount(project_url=…, product="cards", …)`. Keep `verify_supabase_jwt` behind `LEGACY_DASHBOARD_TOKENS=true` **only** until the dashboard cards UI is removed |
| `api/cards.py` | `GET /cards/mine` → `Depends(za.user())` then `WHERE owner_id = p.user_id`. Every owner check (`stored_owner != email`, lines 145–293) becomes `row.owner_id == p.user_id` |
| `api/onboard.py` | `publish` → `Depends(za.optional_user())`. `owner_id = p.user_id if p else None`. After insert: `emit(card.published)`. If there is an owner, seed memory (§4.2.3). If there is no owner, `insert into handle_reservations(handle,'card:<id>')` |
| `services/cards.py` | `insert_card(..., owner_id)`. New `claim_legacy(uid, verified_email)`: `update agent_profile_cards set owner_id=uid where owner_id is null and lower(owner_email)=verified_email returning id, handle`, then `rpc('adopt_handle', {p_user, p_handle, p_release:'card:'+id})` |
| `main.py` | Remove `memory_refresh_loop` once the event path is proven (§4.10). Add a router `POST /internal/v1/events` guarded by `za.service("events.deliver")` |
| `services/zynd_memory.py` | `fetch_findability(zynd_uid)` → `GET {MEMORY_INTERNAL_URL}/v1/service/findability/{zynd_uid}` with `service_headers(ZSK_CARDS)`. Called from the `findability.changed` consumer |
| First-sight hook | `za.on_first_seen = lambda uid, token: claim_legacy(uid, fetch_verified_identity(token).email)` |

#### 4.2.3 Seeding memory on publish (the user is present, so the user's JWT is forwarded)
```python
SEED_MAP = {
    "working_on": "is_building",
    "can_help_with": "has_expertise_in",
    "love_talking_about": "interested_in",        # new predicate (§4.6.7)
}
def seed_declarations(card) -> list[dict]:
    decl = [{"predicate": pred, "value": v} for field, pred in SEED_MAP.items() for v in (getattr(card, field) or [])]
    if card.identity.location:
        decl.append({"predicate": "is_located_in", "value": card.identity.location})
    for v in card.connect_with or []:
        pred, val = map_connect_with(v)           # enum-map to is_seeking / open_to (memory ENUM_VALUES)
        if pred:
            decl.append({"predicate": pred, "value": val})
    return decl[:50]

httpx.post(f"{MEMORY_INTERNAL_URL}/me/findability/declare-batch",
           json={"declarations": seed_declarations(card), "source": "cards:onboarding"},
           headers={"Authorization": authorization, "X-Request-Id": rid}, timeout=8)
```

Scraped skills and repos go through `POST /me/findability/suggest-batch` as **private suggestions**.

### 4.3 zynd-cards/web (new Next.js app, cards.zynd.ai)

| Source (dashboard) | Destination (`zynd-cards/web/src/app`) |
|---|---|
| `src/app/(site)/create/page.tsx` | `create/page.tsx` |
| `src/app/(site)/p/[handle]/page.tsx`, `profile-auth-actions.tsx`, `edit/page.tsx`, `edit/edit-client.tsx`, `data.json/route.ts` | `p/[handle]/…` (same structure) |
| `src/app/(site)/profile/[id]/page.tsx` | `profile/[id]/page.tsx` |
| `src/app/(site)/directory/page.tsx`, `find/page.tsx`, `search/page.tsx`, `tag/[skill]/page.tsx` | same paths |
| `src/app/agent-card/{layout,page,auth-bar}.tsx` | `page.tsx` (landing) + `components/auth-bar.tsx` |
| `src/lib/cards.ts`, `src/hooks/useMyCard.ts` | `src/lib/cards.ts`, `src/hooks/useMyCard.ts` (token from `useZyndAccount`) |
| `src/lib/auth/post-login.ts` (card intent logic) | `src/lib/post-login.ts` |
| card entries in `src/app/sitemap.ts`, `llms.txt`, `llms-full.txt` | `src/app/sitemap.ts` etc. for `/p/*` |

New files:
- `src/app/login/page.tsx` (`<ZyndLogin/>`)
- `src/app/auth/callback/route.ts` (`export { GET } from "@zynd/account/next/callback"`)
- `src/app/settings/connections` (link to persona's Connections page)
- `src/components/MemorySuggestions.tsx` (owner-only, see §4.6.8)

Handle resolution in `p/[handle]/page.tsx`:
1. Look up `profiles.handle` → owner card.
2. Otherwise, look up an unowned `agent_profile_cards.handle`.
3. Otherwise, look up `handle_aliases` → **301** to the current handle.
4. Otherwise, 404.

### 4.4 agent-persona backend (Next)

| File | Change |
|---|---|
| `config.py` | Add `ZYND_ACCOUNT_URL` (= `SUPABASE_URL`), `SERVICE_CLIENTS` (inbound: `memory`, `cards`), `ZSK_PERSONA`, `MEMORY_URL`. **Remove `MEMORY_LAYER_JWT_SECRET`** |
| `api/auth.py` | `get_current_user` becomes `za.user()` and returns `{"id", "email", "user_metadata"}` for backward compatibility. Remove the 60 s cache |
| `api/guards.py` | Wraps `zynd_account.fastapi`. `_service_name` uses `ServiceAllowlist`. The interim `SUPABASE_SERVICE_KEY` compare is **removed** after memory switches to `zsk_memory` |
| `agent/memory_client.py` | Delete `_make_jwt` (line 75). `headers_for(user_id, request_token=None)` returns `{"Authorization": f"Bearer {request_token}"}` when a user request context exists, otherwise `service_headers(ZSK_PERSONA, on_behalf_of=user_id)`. Switch the path-param calls to `/me/*` |
| `api/internal.py` (**new**) | `/internal/v1/*` router (§6.3). Every route uses `za.service("persona.internal")` + `obo` where acting for a user |
| `api/persona.py` | `DELETE /api/account` (self, live re-auth) replaces `DELETE /{user_id}/account` (the old path is kept for 30 days as an alias). Emits `account.deleted` and waits for acks (§6.5 HLD) |
| Events | Emit `persona.created` on register and `connection.added` on accepted thread. Consume `account.deleted` (no-op if persona is the originator) |
| Relay | Run `python -m zynd_account.relay --db $DATABASE_URL` as pm2 app `relay`. It delivers the **Zynd Account DB** outbox |

### 4.5 agent-persona webapp (Next)

| File | Change |
|---|---|
| `package.json` | Add `@zynd/account`, `@supabase/ssr` |
| `src/lib/supabase.ts` | `getSupabase()` returns a singleton `createZyndBrowserClient()` and runs `migrateLegacySession()` once. The **28 call sites stay unchanged** |
| `src/lib/legacy-session.ts` (**new**) | Read `localStorage["sb-<ref>-auth-token"]`. If there is no cookie session, call `supabase.auth.setSession({access_token, refresh_token})`, then remove the key. Errors are ignored (the user just signs in again) |
| `src/app/LandingClientWrapper.tsx` | Replace the LinkedIn-only `handleOAuth` (line 95) with `<ZyndLogin providers={["google","linkedin_oidc","email"]}/>`. The redirect goes to `/auth/callback` (was `window.location.origin`, line 101) |
| `src/app/auth/callback/route.ts` (**new**) | `export { GET } from "@zynd/account/next/callback"` |
| `src/lib/zynd-oauth.ts` | Unchanged. It remains the OAuth front door (`completeZyndOAuth`) |
| `src/app/dashboard/settings/connections/page.tsx` (**new**) | Status of Claude, ChatGPT, Cursor, bridge, LinkedIn, GitHub, X, Google and Notion connections (from memory `/me/connections-status` + persona `api_tokens`). Connect / disconnect |
| `src/app/dashboard/settings/api-keys/page.tsx` (**new**) | List, create (plaintext shown once, copy button) and revoke via memory `/me/api-keys` |
| `src/app/dashboard/connect/page.tsx` | Becomes "one-click connect": Claude connector URL, ChatGPT GPT link, Cursor install link, `npx @zynd/bridge login` |
| `src/app/p/[userId]/page.tsx` | `redirect(301)` to `https://cards.zynd.ai/p/<handle>` (handle from `person_public`) |
| Onboarding | Pre-fill from `card_public` + memory `/me/findability` |

### 4.6 memory-layer (Next)

#### 4.6.1 Schema (`sql/schema.sql`, idempotent additions)
```sql
alter table users add column if not exists zynd_uid uuid;
create unique index if not exists users_zynd_uid_key on users (zynd_uid);

create table if not exists api_keys (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references users(id) on delete cascade,
  name          text not null,
  prefix        text not null,
  key_hash      text not null unique,
  scopes        text[] not null,
  created_at    timestamptz not null default now(),
  last_used_at  timestamptz,
  expires_at    timestamptz,
  revoked_at    timestamptz
);
create index if not exists api_keys_user_active on api_keys (user_id) where revoked_at is null;

alter table assertions add column if not exists provenance text;          -- e.g. bridge:linkedin, mcp:claude
-- event_outbox / event_deliveries / event_subscriptions: same DDL as §4.1.4
-- processed_events for idempotent consumption:
create table if not exists processed_events (event_id uuid primary key, processed_at timestamptz not null default now());
```

**`zynd_uid` backfill** (script `scripts/backfill_zynd_uid.py`):
1. Export `select id from auth.users` from the Zynd Account DB (service role) into a temp table `aafo_ids` in the memory DB.
2. `update users u set zynd_uid = u.supabase_user_id::uuid from aafo_ids a where u.zynd_uid is null and u.supabase_user_id ~ '^[0-9a-f-]{36}$' and a.id = u.supabase_user_id::uuid;`
3. Rows that remain NULL are xmfj, password or email-only users and are linked lazily (§4.6.2).

#### 4.6.2 Unified credential resolver (`app/main.py::current_user`, `app/mcp_http.py::ZyndTokenVerifier`)

Both call one new function, `app/principal.py::resolve(authorization, x_zynd_user) -> Principal(internal_id, zynd_uid, service, scopes, credential)`:

```python
async def resolve(authorization: str, x_zynd_user: str | None) -> Principal:
    scheme, _, token = authorization.partition(" ")
    token = token.strip() if scheme.lower() == "bearer" else ""
    if not token:
        raise Unauthorized("missing bearer token")
    if token.startswith("zk_"):
        return await _from_api_key(token)                         # §8.2
    if token.startswith("zsk_"):
        client = SERVICES.lookup(token) or raise_unauthorized()
        if x_zynd_user:
            if "obo" not in client.scopes: raise Forbidden("obo not allowed")
            u = await _user_by_zynd_uid(x_zynd_user, create=False) or raise_not_found()
            audit("obo", service=client.name, zynd_uid=x_zynd_user)
            return Principal(u.id, u.zynd_uid, client.name, client.scopes, "service")
        return Principal(None, None, client.name, client.scopes, "service")
    try:
        iss = jwt.decode(token, options={"verify_signature": False}).get("iss")
    except jwt.DecodeError:
        raise Unauthorized("invalid token")
    if iss == ZA.sessions.issuer:                                 # Zynd Account session
        user = await ZA.sessions.verify(token)
        u = await _user_by_zynd_uid(user.id, create=True, session_token=token)   # first-sight link
        return Principal(u.id, u.zynd_uid, None, USER_SCOPES, "session")
    if iss == settings.jwt_issuer:                                # memory's own OAuth token
        sub, iat = verify_access_claims(token)
        u = await _user_by_zynd_uid(sub, create=False) or await _user_by_internal_id(sub)
        if not u or await tokens_revoked(get_pool(), str(u.id), iat):
            raise Unauthorized("session was signed out, please sign in again")
        return Principal(u.id, u.zynd_uid, None, USER_SCOPES, "oauth")
    if settings.enable_dev_bearer and hmac.compare_digest(token, settings.dev_bearer_token):
        return DEV_PRINCIPAL
    raise Unauthorized("invalid token")
```

`_user_by_zynd_uid(uid, create=True, session_token)`:
1. `SELECT … WHERE zynd_uid=$1`. If found, return it.
2. Otherwise do a live `fetch_verified_identity(session_token)` → verified email.
3. `UPDATE users SET zynd_uid=$1 WHERE zynd_uid IS NULL AND lower(email)=$2 RETURNING *` (legacy link).
4. Otherwise `INSERT INTO users(email, display_name, zynd_uid)`.
5. Then POST `/internal/v1/users/{uid}/memberships/memory` to persona (async job).

The obsolete `supabase_user_id` lookup at the end of `current_user` (`app/main.py`, lines 100–125) is deleted.

#### 4.6.3 OAuth server changes (`app/oauth.py`)

| Location | Change |
|---|---|
| `authorize` (line 445) | Always `302 → {ZYND_LOGIN_URL}/?zynd_oauth=<req>`. Include `code_challenge` and `code_challenge_method` in the signed req. Delete the Supabase-direct branch (the Redis `state_id` path) |
| `callback` (line 559) | **Delete** (HTML page for the Supabase-direct flow) |
| `complete` (line 618) | Only the `req` path. `_resolve_user_and_mint_code` (line 575) verifies with `ZA.sessions.verify(supabase_token)` → `_user_by_zynd_uid(create=True)`. Remove `link_user` / `persona_enabled` gating |
| Token issuance (`app/auth.py`) | `issue_access_token(zynd_uid)` / `issue_refresh_token(zynd_uid)`: `sub` is now the `zynd_uid` |
| `config.py` | `zynd_login_url` (env `ZYND_LOGIN_URL`, falls back to `PERSONA_LOGIN_URL`). Remove `dashboard_url` |

Also remove `app/connect.py` (password `/connect`), `/token/exchange` (`app/main.py:151`), and `/me/social-links`' Supabase-token path (replaced by the persona `profile.updated` event).

#### 4.6.4 API keys (`app/api_keys.py`, **new**)

| Endpoint | Guard | Behavior |
|---|---|---|
| `POST /me/api-keys` | Session credential only, plus a live `fetch_verified_identity` | Body `{name (1–60), scopes ⊆ [memory.read, memory.write, people.search], expires_in_days (1–730) or null}`. Max 20 active keys per user. Returns `{id, key, prefix, scopes, expires_at}` with **the key shown once** |
| `GET /me/api-keys` | Session | `[{id, name, prefix, scopes, created_at, last_used_at, expires_at}]` |
| `DELETE /me/api-keys/{id}` | Session | Sets `revoked_at = now()` where `user_id` = caller. Idempotent 204 |

#### 4.6.5 Removing persona's `service_role` key from memory

Replace every direct use of persona tables, then delete `SUPABASE_SERVICE_KEY` from memory's env.

| memory file | Direct access today | Replacement (persona `/internal/v1`, `zsk_memory`) |
|---|---|---|
| `app/services/token_store.py:17` | `api_tokens` read/write (Google, X, LinkedIn, Notion OAuth tokens) | **Token broker:** `GET /internal/v1/users/{uid}/provider-token/{provider}` returns `{access_token, expires_at}` only. Persona refreshes; the refresh token never leaves persona. Scope `tokens.broker` + `obo`. `save_tokens` moves to persona's OAuth callbacks. **Later:** tools run inside persona (§5.5) |
| `app/services/matching.py:225,243` | `persona_agents` names | `POST /internal/v1/people/batch {ids}` → `person_public` rows. Later: denormalized in `people_index` |
| `app/services/meetings.py:20–154` | `dm_threads`, `persona_agents`, `agent_tasks` (insert/update) | `POST /internal/v1/meetings`, `POST /internal/v1/meetings/{task_id}/respond`, `GET /internal/v1/users/{uid}/meetings/pending` |
| `app/services/pages_agent.py:30,85` and `app/main.py:544` | Persona's `published_pages` | `POST /internal/v1/users/{uid}/pages`, `GET /internal/v1/pages/{slug}`. Pages are owned by persona (the webapp renders them sandboxed) |
| `app/tools/brief.py:15–104` | `persona_agents` brief + `brief_todos` | `GET/PATCH /internal/v1/users/{uid}/brief`, `POST /internal/v1/users/{uid}/todos` |
| `app/tools/zynd_network.py:37–134` | `persona_agents` search + REST with the service key | `GET /internal/v1/personas/search?q=`. Later: `/v1/people/search` |
| `app/services/persona.py:30,149` | persona API with the service key + `rest/v1/dm_threads` | Same persona endpoints re-homed under `/internal/v1/users/{uid}/…` with `zsk_memory` + obo. `GET /internal/v1/users/{uid}/connections` |

#### 4.6.6 Findability service endpoint
`GET /v1/service/findability/{zynd_uid}` uses guard `service("findability.read")` and looks up **by `zynd_uid` only** (the email and id matching at `app/main.py:183–208` is removed).

#### 4.6.7 Taxonomy (`app/taxonomy.py`)
- Add `"interested_in"` to `FINDABILITY_PREDICATES` (entity family `concept_topic`).
- Add it to `DECLARE_ENTITY_TYPE`.
- Add it to `CLUSTER_PREDICATES["intent_cluster"]` or a new `interest_cluster`.
- Export the taxonomy as JSON (`/v1/taxonomy`) so bridge can generate its TypeScript copy.

#### 4.6.8 Suggestions and provenance
- **New `POST /me/findability/suggest-batch`:** same body as `declare-batch` plus `source`. It writes `is_public=false`, `source='inferred'` and `provenance=<source>` assertions, which appear in `/me/findability/suggestions`.
- `declare-batch`, `/ingest` and `/me/memory/declare` accept an optional `source`, stored in `assertions.provenance`.
- **Events:** `approve` / `revoke` / `declare` insert `findability.changed` into memory's outbox (in the same transaction as the write).

#### 4.6.9 Event consumer `POST /internal/v1/events` (guard `service("events.deliver")`)
- **`card.published` / `card.updated`:** store `bio` and `projects` text, embed them into the new `user_embeddings` facets (`bio_cluster`, `projects_cluster`), then enqueue a people-index refresh.
- **`profile.updated`:** update `users.display_name` and socials (the display cache).
- **`account.deleted`:** delete the `users` row (cascades) and revoke keys.
- **`persona.created`:** set a `has_persona` flag.

### 4.7 zynd-bridge (Next)

| File | Change |
|---|---|
| `src/cli/index.ts` | New `login` command: default runs `oauthLogin` (existing, line 363); `--api-key <key>` stores the key in the keychain (`src/keychain.ts`) and verifies it via `GET /me/whoami`. `init` calls `login`. `card` shows the real card (`GET https://api.zynd.ai/cards/mine`) plus public facts |
| `src/config.ts:64–81` | Add `ZYND_API_KEY`. **Remove** `MEMORY_LAYER_JWT_SECRET`, `ZYND_JWT_SECRET`, `ZYND_USER_ID`, `ZYND_MEMORY_USER_ID` |
| `src/memory-client.ts` | Remove `jwtSecret` / `userId` / `makeLocalJwt` (lines 15–48). Auth order: API key → OAuth access (with refresh) |
| `src/sync.ts:52,61` | `declareBatch` → `suggestBatch` (private) by default. `zynd sync --publish` keeps `declareBatch`. Send `source: "bridge:<connector>"` |
| `src/types.ts` | Generated `taxonomy.ts` from memory `/v1/taxonomy` |

### 4.8 dashboard (Next): removal list and redirects

**Delete** (the profile-cards feature only):
- `src/app/(site)/create/`, `src/app/(site)/p/`, `src/app/(site)/profile/`, `src/app/(site)/directory/`, `src/app/(site)/find/`, `src/app/(site)/search/`, `src/app/(site)/tag/`
- `src/app/agent-card/`
- `src/app/(site)/authorize/`
- `src/hooks/useMyCard.ts`
- `src/lib/cards.ts`
- the card intent in `src/lib/auth/post-login.ts`
- `lookupMyCardHandle` in `src/app/(site)/auth/callback/route.ts`
- card links in `src/components/Navbar.tsx` and `src/components/dashboard/sidebar.tsx`
- `/p/*` entries in `src/app/sitemap.ts`, `llms.txt`, `llms-full.txt`

**Keep:** registry / A2A agent-card code (`src/app/api/registry/**`, `src/app/api/entities/**`), `(site)/registry`, and developer onboarding.

**`next.config.ts`:**
```ts
async redirects() {
  const C = process.env.NEXT_PUBLIC_CARDS_URL ?? "https://cards.zynd.ai";
  return [
    { source: "/p/:handle",         destination: `${C}/p/:handle`,         permanent: true },
    { source: "/p/:handle/:rest*",  destination: `${C}/p/:handle/:rest*`,  permanent: true },
    { source: "/create",            destination: `${C}/create`,            permanent: true },
    { source: "/agent-card",        destination: `${C}/`,                  permanent: true },
    { source: "/directory",         destination: `${C}/directory`,         permanent: true },
    { source: "/find",              destination: `${C}/find`,              permanent: true },
    { source: "/search",            destination: `${C}/search`,            permanent: true },
    { source: "/tag/:skill",        destination: `${C}/tag/:skill`,        permanent: true },
    { source: "/profile/:id",       destination: `${C}/profile/:id`,       permanent: true },
  ];
}
```

### 4.9 Infra (Next)

| Item | Change |
|---|---|
| DNS | `cards.zynd.ai` → Vercel |
| Caddy (`memory-layer/Caddyfile`, moving to `zynd-infra` later) | Add `handle_path /internal/memory/* { reverse_proxy api:8000 }` and `handle_path /internal/cards/* { reverse_proxy cards:8000 }`. Both are reachable only with a `zsk_` bearer (checked by the apps). Inside compose, cards → memory uses `http://api:8000` directly |
| CORS | memory `cors_origins` + cards: add `https://cards.zynd.ai`. Remove `https://www.zynd.ai` from memory after `/authorize` is gone |
| Secrets | Generate `zsk_persona`, `zsk_cards` and `zsk_memory` (§8.2). Put each plaintext only in its owner's env and the hashes in the receivers' `SERVICE_CLIENTS` |
| Images | Each service builds and pushes its own image (GHCR). Compose references `image:` tags, not sibling repo paths (fixes F15) |

### 4.10 Events: relay and consumers

```python
# zynd_account/relay.py (runs per producer DB)
async def run(dsn: str, subscribers: dict[str, str], key: str):
    conn = await asyncpg.connect(dsn)
    await conn.add_listener("zynd_events", lambda *_: wake.set())
    while True:
        rows = await conn.fetch("""
            SELECT d.event_id, d.subscriber, o.type, o.version, o.subject, o.producer, o.data, o.occurred_at
              FROM event_deliveries d JOIN event_outbox o USING (event_id)
             WHERE d.delivered_at IS NULL AND d.next_attempt_at <= now()
             ORDER BY o.id LIMIT 100
             FOR UPDATE OF d SKIP LOCKED""")
        for r in rows:
            try:
                resp = await http.post(subscribers[r["subscriber"]], json=envelope(r),
                                       headers={**service_headers(key), "X-Event-Id": str(r["event_id"])}, timeout=10)
                resp.raise_for_status()
                await conn.execute("UPDATE event_deliveries SET delivered_at=now() WHERE event_id=$1 AND subscriber=$2",
                                   r["event_id"], r["subscriber"])
            except Exception as e:
                await conn.execute("""UPDATE event_deliveries SET attempts=attempts+1, last_error=$3,
                        next_attempt_at = now() + least(interval '1 hour', interval '2 seconds' * power(2, attempts))
                        WHERE event_id=$1 AND subscriber=$2""", r["event_id"], r["subscriber"], str(e)[:500])
        await wait_for(wake, timeout=2)
```

The loop is shown simplified: in production, claim the rows in one short transaction and deliver outside it.

- **Consumer rule:** `INSERT INTO processed_events(event_id) ON CONFLICT DO NOTHING RETURNING event_id`. If nothing is returned, the event was already processed: reply 202. Otherwise enqueue an arq job and reply 202.
- **Dead letter:** after 24 h of attempts the delivery is marked `last_error='dead'` and an alert fires.

**Removing the cron:** `zynd-cards/main.py:32` (`memory_refresh_loop`) can be deleted once `findability.changed` deliveries have run for 7 days with zero dead letters.

---

## 5. LATER: people search, consent, consolidation

### 5.1 People search (memory-layer)

#### 5.1.1 Schema
```sql
alter table user_embeddings add column if not exists embedding_model text not null default 'text-embedding-3-small';
-- One partial HNSW index per facet so filtered ANN returns full result pages:
create index if not exists ue_hnsw_full    on user_embeddings using hnsw (embedding vector_cosine_ops) where cluster_type = 'full_context';
create index if not exists ue_hnsw_intent  on user_embeddings using hnsw (embedding vector_cosine_ops) where cluster_type = 'intent_cluster';
create index if not exists ue_hnsw_skill   on user_embeddings using hnsw (embedding vector_cosine_ops) where cluster_type = 'skill_cluster';
create index if not exists ue_hnsw_place   on user_embeddings using hnsw (embedding vector_cosine_ops) where cluster_type = 'place_cluster';
create index if not exists ue_hnsw_bio     on user_embeddings using hnsw (embedding vector_cosine_ops) where cluster_type = 'bio_cluster';
create index if not exists ue_hnsw_proj    on user_embeddings using hnsw (embedding vector_cosine_ops) where cluster_type = 'projects_cluster';

create table if not exists people_index (
  user_id            uuid primary key references users(id) on delete cascade,
  zynd_uid           uuid unique,
  handle             text,
  display_name       text,
  headline           text,
  avatar_url         text,
  location           text,
  open_to            text[] not null default '{}',
  seeking            text[] not null default '{}',
  affiliations       text[] not null default '{}',
  has_persona        boolean not null default false,
  discoverability    text not null default 'members',
  public_fact_count  int not null default 0,
  last_active_at     timestamptz,
  search_tsv         tsvector,
  updated_at         timestamptz not null default now()
);
create index if not exists people_index_tsv     on people_index using gin (search_tsv);
create index if not exists people_index_open_to on people_index using gin (open_to);
create index if not exists people_index_seeking on people_index using gin (seeking);

create table if not exists people_edges (          -- graph signals (mutuals, connections)
  a uuid not null, b uuid not null, kind text not null,     -- linkedin | persona_connection | same_affiliation
  primary key (a, b, kind)
);
create table if not exists people_blocks (user_id uuid, blocked uuid, primary key (user_id, blocked));
```

#### 5.1.2 Index maintenance (arq job `refresh_person(user_id)`, debounced 60 s per user)
1. `recompute_user_embeddings(pool, user_id)` (existing, `app/services/matching.py:46`, public facts only), plus the `bio` and `projects` facets from the stored card text.
2. Upsert the `people_index` row:
   - `search_tsv = setweight(to_tsvector(name||' '||handle),'A') || setweight(to_tsvector(headline),'B') || setweight(to_tsvector(public facts + skills + affiliations),'C')`
   - `open_to` and `seeking` from public enum facts
   - `public_fact_count`
3. Triggered by `facts.approved`, `findability.changed`, `card.*`, `profile.updated`, `persona.created`, `connection.added`.

#### 5.1.3 Query vector on the caller's side (private data allowed, never stored)
```python
async def query_vector(pool, user_id: str, facet: str) -> list[float]:
    rows = await pool.fetch("""
        SELECT e.embedding, a.confidence FROM assertions a JOIN entities e ON e.id = a.object_entity_id
         WHERE a.user_id = $1 AND a.predicate = ANY($2::text[]) AND a.valid_until IS NULL
           AND a.gate IS NULL                       -- never use health/politics/immigration facts
           AND e.embedding IS NOT NULL
         ORDER BY a.confidence DESC LIMIT 200""", user_id, list(CLUSTER_PREDICATES[facet]))
    return _weighted_average(rows)                   # existing helper, matching.py:32
```

#### 5.1.4 Hybrid SQL with Reciprocal Rank Fusion (k = 60)
```sql
-- $1 query vector, $2 query text, $3 facet, $4 caller user_id, $5 min public facts,
-- $6 location filter (nullable), $7 open_to filter (nullable text[]), $8 limit
with vec as (
  select user_id, row_number() over (order by dist) as r from (
    select ue.user_id, ue.embedding <=> $1::vector as dist
      from user_embeddings ue
     where ue.cluster_type = $3
     order by ue.embedding <=> $1::vector
     limit 100) t
),
kw as (
  select user_id, row_number() over (order by rank desc) as r from (
    select pi.user_id, ts_rank_cd(pi.search_tsv, websearch_to_tsquery('english', $2)) as rank
      from people_index pi
     where $2 <> '' and pi.search_tsv @@ websearch_to_tsquery('english', $2)
     order by rank desc
     limit 100) t
),
fused as (
  select user_id, sum(1.0 / (60 + r)) as rrf
    from (select * from vec union all select * from kw) s
   group by user_id
)
select pi.*, f.rrf
  from fused f
  join people_index pi using (user_id)
 where pi.user_id <> $4
   and pi.discoverability <> 'off'
   and pi.public_fact_count >= $5
   and ($6::text   is null or pi.location ilike '%' || $6 || '%')
   and ($7::text[] is null or pi.open_to && $7)
   and not exists (select 1 from people_blocks b where (b.user_id = $4 and b.blocked = pi.user_id)
                                                   or (b.user_id = pi.user_id and b.blocked = $4))
 order by f.rrf desc
 limit $8;
```

**Re-scoring in Python** after the SQL:

```
score = rrf + 0.02 · mutuals (cap 5) + 0.01 · shared_affiliations + 0.01 · has_persona + recency_decay
```

Then an optional LLM rerank of the top 50 → 10, producing `reasons[]` **from the candidate's public facts only**.

#### 5.1.5 Complementary matching (based on memory's `ENUM_VALUES`)
| Caller `is_seeking` | Candidate must have |
|---|---|
| `co_founder` | `open_to: co_founder` |
| `being_mentored` | `open_to: mentoring_others` |
| `mentoring` | `open_to: being_mentored` |
| `early_users` | `open_to: early_user_testing` |
| `technical_feedback`, `peer_review` | `open_to: peer_review` |
| `collaboration` | `open_to: collaboration` |
| `investment` | vector search on the text "angel investor, VC, fundraising" over `skill_cluster` |

This is implemented as a filter on `people_index.open_to` combined with vector search on `intent_cluster`.

#### 5.1.6 Query parsing
- Model: a small LLM (existing DeepSeek or OpenRouter setup).
- Output: JSON `{"text": str, "facet": "full_context|intent_cluster|skill_cluster|place_cluster|bio_cluster|projects_cluster", "location": str|null, "open_to": [..]|null, "seeking": [..]|null}`.
- Cache in Redis by `sha256(q)` for 24 h.
- On failure, fall back to `{"text": q, "facet": "full_context"}`.

#### 5.1.7 Limits
| Caller | Limit |
|---|---|
| Anonymous | 10 req/min/IP. `discoverability='public'` only. Max 10 results |
| User | 60 req/min |
| `zk_` with `people.search` | 30 req/min |
| All callers | `limit` ≤ 50. Cursor pagination up to 200 results total. No vectors in responses |

#### 5.1.8 Callers
- MCP `find_people` / `find_similar_users` (`app/mcp_http.py:331,340`) call the same service functions.
- The cards directory, `/find` and `/search` call `/v1/people/search`.
- The persona People page calls `/v1/people/similar?to=me`, plus the external tier (QuickEnrich, `backend/services/people_suggestions.py`) labeled `source: "external"`.

### 5.2 Consent inbox and digest
- cards web + persona: an `Inbox` component listing `/me/findability/suggestions` grouped by `provenance`, with approve / hide / edit actions.
- Weekly job in memory: users with ≥ 3 new suggestions get an email (Supabase SMTP or Resend) or a Telegram message (persona `telegram_notify`).

### 5.3 Ingestion worker (consolidated scraping)
- Move `zynd-cards/scraping/{github,linkedin,x,website,resume}.py` and `agent-persona/backend/services/{linkedin_scraper,twitter_scraper,github_sync}.py` into a memory worker queue `ingest:<source>`.
- **Outputs:** evidence to cards (`/internal/cards/v1/evidence/{uid}`), facts to memory as suggestions.
- Bridge keeps only its local connectors (`linkedin-network`, `linkedin-connections`, `obsidian`, `mem0`, `zep`).

### 5.4 Privacy center and account deletion
- persona `DELETE /api/account` (live re-auth) emits `account.deleted`. Cards deletes or anonymizes the user's cards; memory deletes the user (cascade) and revokes keys. Persona deletes the `auth.users` row after all subscribers ack, or after 24 h.
- `GET /me/export` on each service, zipped by persona.

### 5.5 Run third-party tools inside persona (removes the token broker)
- memory MCP Google/X/LinkedIn/Notion tools (`app/mcp_http.py:676–871`) proxy to persona `POST /internal/v1/users/{uid}/tools/{name}`.
- Third-party OAuth tokens then never leave persona.

### 5.6 Legacy cleanup
| Remove | Where |
|---|---|
| `owner_email` as an authority (keep as history), `LEGACY_DASHBOARD_TOKENS`, `verify_supabase_jwt` | zynd-cards |
| `users.supabase_user_id`, `users.password_hash`, `app/passwords.py`, `enable_dev_bearer` in prod, `persona_enabled`, `dashboard_url`, `memory_service_token` | memory-layer |
| `/{user_id}/account` alias, `?token=` OAuth connect, the interim service-key compare in `guards.py` | agent-persona |
| `jwtSecret` paths | zynd-bridge |

### 5.7 Least-privilege DB role for cards
- Create a Postgres role `svc_cards` with rights on `agent_profile_cards`, `x_*`, `event_outbox` (INSERT), `handle_reservations`, the views, and EXECUTE on `adopt_handle` / `touch_membership`.
- Switch cards from supabase-py with `service_role` to `asyncpg` using `svc_cards` over the Supavisor pooler.

### 5.8 Repo structure
- **`zynd-infra`:** Caddyfile, compose, deploy scripts, env templates.
- **Later:** a monorepo `zynd` with `apps/{cards-web,persona-web}`, `services/{cards,persona,memory}`, `packages/{account-py,account-ts}` and `cli/bridge`, using pnpm + uv workspaces.

---

## 6. API specifications (new or changed)

### 6.1 memory-layer

**`GET /me/whoami`** (user, OAuth or `zk_`) → 200
```json
{ "user_id": "0b6…", "zynd_uid": "9f2…", "email": "a@b.com", "display_name": "Ada" }
```

**`POST /me/findability/declare-batch`** (user, OAuth or `zk_` with `memory.write`)
```json
{ "declarations": [{ "predicate": "is_building", "value": "pgvector tooling" }], "source": "cards:onboarding" }
```
→ 200
```json
{ "status": "ok", "declared": [{ "predicate": "is_building", "value": "pgvector tooling" }], "skipped": [] }
```
422 if more than 50 items.

**`POST /me/findability/suggest-batch`**: same shape. Items become private suggestions.

**`POST /me/api-keys`** (session only)
```json
{ "name": "MacBook bridge", "scopes": ["memory.read", "memory.write"], "expires_in_days": 180 }
```
→ 201
```json
{ "id": "7c1…", "key": "zk_live_3fQ…", "prefix": "zk_live_3fQx", "scopes": ["memory.read","memory.write"], "expires_at": "2027-03-22T10:00:00Z" }
```
Errors: 401 (not a session credential), 409 (`too_many_keys`, more than 20 active), 422.

**`GET /v1/service/findability/{zynd_uid}`** (`zsk_cards`, `findability.read`) → `{ "connected": true, "facts": [{ "predicate": "…", "object": "…", "confidence": 0.97 }] }`

**`POST /internal/v1/events`** (`zsk_*`, `events.deliver`). Header `X-Event-Id`. Body = envelope → 202.

**`GET /v1/people/search`** (Later)

Query parameters: `q`, `location?`, `open_to?` (comma-separated), `facet?`, `limit≤50`, `cursor?`.

→ 200
```json
{
  "results": [{
    "handle": "ada", "name": "Ada L.", "avatar_url": "…", "headline": "Building agent infra",
    "card_url": "https://cards.zynd.ai/p/ada", "has_persona": true,
    "score": 0.42, "reasons": ["Both building AI agents", "Both in Bangalore"], "mutuals": 3
  }],
  "external": [{ "name": "…", "linkedin_url": "…", "source": "external", "invite": true }],
  "next_cursor": "eyJvIjoxMH0"
}
```

**`GET /v1/people/similar`** (Later)

Query parameters: `to` (`me` or a handle), `facet?`, `limit?`. The response has the same shape as search.

### 6.2 zynd-cards

| Endpoint | Change |
|---|---|
| `POST /onboard/{job_id}/publish` | Guard `optional_user`. `owner_email` in the body is ignored. Response unchanged (`card.model_dump`) |
| `GET /cards/mine` | Guard `user`. Returns the caller's card (by `owner_id`) or 404 |
| `PATCH /cards/by-handle/{handle}`, `POST …/refresh-{linkedin,github,memory}` | Guard `user` + `owner_id == caller` |
| `POST /internal/v1/events` | Guard `service("events.deliver")` |
| `GET /internal/v1/cards/by-user/{zynd_uid}` | Guard `service("persona.internal")` |

### 6.3 agent-persona `/internal/v1` (guard `service("persona.internal")`; `obo` required where a user is acted for)

| Method and path | Replaces | Body / response |
|---|---|---|
| `GET /internal/v1/users/{uid}/persona` | `/api/persona/{uid}/status` | `{active, agent_id}` |
| `POST /internal/v1/users/{uid}/persona` | `/api/persona/register` | `PersonaRegisterRequest` minus `user_id` |
| `PUT /internal/v1/users/{uid}/profile` | `/api/persona/{uid}/profile` | `{profile}` |
| `GET/PATCH /internal/v1/users/{uid}/brief` | memory `tools/brief.py` direct writes | `{content}` |
| `POST /internal/v1/users/{uid}/todos` | memory `brief_todos` insert | `{title}` |
| `POST /internal/v1/users/{uid}/threads` | `/api/persona/{uid}/threads` | `ThreadCreateRequest` |
| `POST /internal/v1/users/{uid}/agent-send` | `/api/persona/{uid}/agent-send` | `AgentChannelSend` |
| `GET /internal/v1/users/{uid}/connections` | memory PostgREST `dm_threads` | `[{thread_id, peer_agent_id, peer_name, status}]` |
| `POST /internal/v1/meetings` · `POST /internal/v1/meetings/{task_id}/respond` · `GET /internal/v1/users/{uid}/meetings/pending` | memory `services/meetings.py` direct writes | as `/api/meetings` |
| `GET /internal/v1/users/{uid}/provider-token/{provider}` | memory `token_store.py` | `{access_token, expires_at}` (scope `tokens.broker`) |
| `POST /internal/v1/users/{uid}/pages` · `GET /internal/v1/pages/{slug}` | memory `pages_agent.py` | `{slug, url}` |
| `POST /internal/v1/people/batch` | memory `matching.py:243` | `{ids:[…]}` → `person_public` rows |
| `GET /internal/v1/personas/search?q=` | memory `tools/zynd_network.py` | persona search rows |
| `POST /internal/v1/users/{uid}/memberships/{product}` | — | `{first_seen: bool}` |
| `POST /internal/v1/events` | — | envelope → 202 |

---

## 7. Configuration matrix

| Service | Add | Rename | Remove |
|---|---|---|---|
| **zynd-cards API** | `ZYND_ACCOUNT_URL`, `SUPABASE_ANON_KEY`, `SERVICE_CLIENTS` (`memory`, `persona`), `ZSK_CARDS`, `MEMORY_INTERNAL_URL`, `LEGACY_DASHBOARD_TOKENS` (temporary) | — | `SUPABASE_JWT_SECRET`, `MEMORY_SERVICE_TOKEN`, `MEMORY_REFRESH_INTERVAL_HOURS` |
| **zynd-cards web** | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (Zynd Account), `NEXT_PUBLIC_ZYND_COOKIE_DOMAIN=.zynd.ai`, `NEXT_PUBLIC_CARDS_API_URL`, `NEXT_PUBLIC_MEMORY_API_URL`, `NEXT_PUBLIC_PERSONA_URL` | — | — |
| **persona backend** | `SERVICE_CLIENTS` (`memory`, `cards`), `ZSK_PERSONA`, `TELEGRAM_WEBHOOK_SECRET`, `MEMORY_URL`, `EVENT_SUBSCRIBERS` (relay) | — | `MEMORY_LAYER_JWT_SECRET` |
| **persona webapp** | `NEXT_PUBLIC_ZYND_COOKIE_DOMAIN`, `NEXT_PUBLIC_CARDS_URL` | — | — |
| **memory-layer** | `SERVICE_CLIENTS` (`persona`, `cards`), `ZSK_MEMORY`, `PERSONA_INTERNAL_URL`, `EVENT_SUBSCRIBERS` | `PERSONA_LOGIN_URL` → `ZYND_LOGIN_URL` | `SUPABASE_SERVICE_KEY` (after §4.6.5), `MEMORY_SERVICE_TOKEN`, `DASHBOARD_URL`, `PERSONA_ENABLED`; **rotate** `JWT_SECRET` |
| **zynd-bridge** | `ZYND_API_KEY` | — | `MEMORY_LAYER_JWT_SECRET`, `ZYND_JWT_SECRET`, `ZYND_USER_ID`, `ZYND_MEMORY_USER_ID` |
| **dashboard** | `NEXT_PUBLIC_CARDS_URL` | — | cards-only uses of `NEXT_PUBLIC_API_URL` |

**`SERVICE_CLIENTS` examples**

memory receives:
```json
{"persona":{"sha256":["<h1>"],"scopes":["memory.read","memory.write","obo","events.deliver"]},
 "cards":{"sha256":["<h2>"],"scopes":["findability.read","memory.write","obo","events.deliver"]}}
```

persona receives:
```json
{"memory":{"sha256":["<h3>"],"scopes":["persona.internal","tokens.broker","obo","events.deliver"]},
 "cards":{"sha256":["<h4>"],"scopes":["persona.internal","events.deliver"]}}
```

cards receives:
```json
{"memory":{"sha256":["<h3>"],"scopes":["events.deliver"]},
 "persona":{"sha256":["<h1>"],"scopes":["persona.internal","events.deliver"]}}
```

---

## 8. Algorithms

### 8.1 Credential resolution order
The order is `zk_` → `zsk_` (+obo) → JWT by `iss` (Zynd Account ES256 → memory HS256) → dev bearer (non-prod) → 401. See §4.6.2 and HLD §5.1.

### 8.2 Key generation and verification
```python
import hashlib, secrets
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

def new_key(prefix: str) -> tuple[str, str, str]:
    body = "".join(secrets.choice(ALPHABET) for _ in range(43))        # ≈ 256 bits
    key = prefix + body
    return key, hashlib.sha256(key.encode()).hexdigest(), key[: len(prefix) + 4]

async def _from_api_key(key: str) -> Principal:
    row = await pool.fetchrow("""
        SELECT k.id, k.scopes, u.id AS uid, u.zynd_uid, k.last_used_at
          FROM api_keys k JOIN users u ON u.id = k.user_id
         WHERE k.key_hash = $1 AND k.revoked_at IS NULL
           AND (k.expires_at IS NULL OR k.expires_at > now())""",
        hashlib.sha256(key.encode()).hexdigest())
    if not row:
        raise Unauthorized("invalid or revoked API key")
    if not row["last_used_at"] or row["last_used_at"] < utcnow() - timedelta(minutes=1):
        asyncio.create_task(pool.execute("UPDATE api_keys SET last_used_at = now() WHERE id = $1", row["id"]))
    return Principal(row["uid"], row["zynd_uid"], None, frozenset(row["scopes"]), "api_key")
```

- SHA-256 (not bcrypt) is correct here: the key carries 256 bits of randomness, so brute force isn't feasible, and a fast hash allows an indexed lookup.
- Register the regexes `zk_(live|test)_[0-9A-Za-z]{43}` and `zsk_live_[a-z]+_[0-9A-Za-z]{43}` with GitHub secret scanning.

**Generating a service key** (ops):
```bash
python -c "from zynd_account.keys import new_key; k,h,_=new_key('zsk_live_persona_'); print(k); print(h)"
```

### 8.3 Handle normalization and assignment
1. Normalize with `lower(trim(x))`. Allowed pattern: `^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$`.
2. A handle is free only when it is not in `reserved_words`, not held by another profile, not another user's alias, and not reserved. (`handle_is_free`, §4.1.2)
3. Collisions get suffixes `-1…-9999`, then a random fallback (`generate_handle`).

### 8.4 Legacy claim (runs once per product, on first sight)
- **cards:**
  ```sql
  update agent_profile_cards set owner_id=$uid where owner_id is null and lower(owner_email)=$verified returning id, handle
  ```
  Then, for each returned card: `adopt_handle($uid, handle, 'card:'||id)`.
- **memory:** `_user_by_zynd_uid(create=True)` (§4.6.2).
- The verified email always comes from a **live** `/auth/v1/user` call, never from JWT claims alone.

### 8.5 Debouncing
Per-user debounce uses Redis `SET debounce:<job>:<uid> 1 NX EX 60`. If the key was set, enqueue the arq job with `_defer_by=60`; otherwise skip.

### 8.6 Reciprocal Rank Fusion
`rrf(d) = Σ_lists 1 / (60 + rank_list(d))`. Lists: vector top 100 and keyword top 100. Ties are broken by `public_fact_count`.

---

## 9. Migration runbook and rollback

### 9.1 Now
| # | Step | Verify | Rollback |
|---|---|---|---|
| N1 | Deploy persona `guards.py` + route guards (interim service-key compare) | `test_route_guards.py` green. Memory → persona calls still 200 (they send the service key). UI smoke test | Revert the deploy (not advisable). Guards per router can be feature-flagged |
| N2 | Telegram: deploy an optional check → set the secret → run the register script → enforce | A bot message round-trip works. A forged POST gets 401 | Unset the env var |
| N3 | cards publish owner fix + duplicate route + search RPCs | Publishing with a forged `owner_email` gives `owner_email` = token email or NULL. Search returns results beyond 1,000 cards | Revert |
| N4 | memory `declare-batch` + `whoami` + `fb34842` | Bridge contract test green. `zynd sync` declares facts | Revert |
| N5 | Supabase ES256 rotation + provider config + staging | JWKS lists an EC key. Tokens have `alg: ES256` | Rotate back to HS256 (standby) |

### 9.2 Next (strict order)
| # | Step | Verify | Rollback |
|---|---|---|---|
| X1 | `zynd-account` SQL 0001–0004 on staging, then prod | Tables and functions exist. Trigger fires on a test signup | Drop the new objects |
| X2 | cards `patch_owner_id.sql` → `0005_backfill.sql` | Every aafo user has a profile. Unowned card handles are reserved | Truncate reservations / profiles backfill |
| X3 | Publish `zynd-account` py/ts 0.1.0 | Package test suites pass | — |
| X4 | memory schema + `zynd_uid` backfill + resolver (accepts old and new) + persona's old HS256 JWTs still accepted | Auth metrics show `credential_type` distribution. No 401 spike | Flag `RESOLVER_V2=false` |
| X5 | persona backend: `za`, `/internal/v1/*`, `zsk_persona`, memory client switch, relay | Memory logs show no self-minted persona JWTs. obo audit lines appear | Flag `MEMORY_AUTH_MODE=legacy` |
| X6 | memory: `zsk_memory` → persona internal endpoints (§4.6.5), token broker, events | No `SUPABASE_SERVICE_KEY` reads in logs for 7 days → **remove the env var** | Re-add the env var (code path kept for one release) |
| X7 | cards API: `za`, `owner_id`, claim, `zsk_cards`, events, `LEGACY_DASHBOARD_TOKENS=true` | `/cards/mine` works with Zynd Account tokens and legacy dashboard tokens | Flag |
| X8 | Exit gate: **rotate memory `JWT_SECRET`** (invalidates self-minted tokens; memory's own OAuth tokens are re-issued on refresh) | AI clients reconnect via refresh. Bridge re-login where needed | — |
| X9 | cards.zynd.ai launch → persona webapp cookie SSO + unified login → bridge 0.2 → dashboard removal + 301s → `LEGACY_DASHBOARD_TOKENS=false` | End-to-end suite §10.4 green. Search Console shows 301s | Dashboard flag re-enables the old routes |
| X10 | Remove memory `/connect`, `/oauth/callback`, `/token/exchange`, dashboard `/authorize` | One login entry point | Revert |

### 9.3 Later
Each item in §5 ships behind its own flag, using the same pattern: dual-run, verify, then remove the old path.

---

## 10. Test plan

### 10.1 Unit tests
| Package / repo | Cases |
|---|---|
| `zynd_account` (py) | ES256 valid → ok. Expired → 401 `token_expired`. Wrong `iss` → 401. HS256-signed → 401. `role != authenticated` or `is_anonymous` → 401. Unknown `kid` → JWKS refetch. `zsk_` unknown → 401. `zsk_` + `X-Zynd-User` without `obo` → 403. `self_or_service` mismatch → 403. `touch_membership` first-sight flag |
| SQL (pgTAP or pytest + psycopg) | `handle_is_free` rules. `set_handle` writes an alias and an event. `adopt_handle` releases the matching reservation only. `generate_handle` suffixes. The trigger creates a profile |
| memory | Resolver matrix (6 credential types × valid/invalid). API keys: create → use → revoke → 401. Expiry. 20-key cap. `declare-batch` caps at 50 and skips invalid predicates. `suggest-batch` is private |
| cards | Publish ignores `body.owner_email`. Claim sets `owner_id` only for verified email matches. `match_cards` ordering |
| persona | Every guard type. `ensure_actor`. Thread/task participant checks. Telegram secret |
| bridge | `login --api-key` stores to the keychain. A 404 on optional endpoints degrades gracefully. Contract test |

### 10.2 Contract tests
- memory CI exports `openapi.json` as an artifact.
- bridge, cards and persona CI download it and assert that every path and method they call exists (lists live in `memory-client.ts`, `services/zynd_memory.py` and `agent/memory_client.py`).
- The same applies to persona's `/internal/v1` OpenAPI, consumed by memory and cards.

### 10.3 Security probes
**Static: every route must declare auth** (`agent-persona/backend/tests/test_route_guards.py`; the same pattern applies to cards and memory):

```python
from fastapi.routing import APIRoute
from main import app

def _deps(dependant):
    for d in dependant.dependencies:
        yield d.call
        yield from _deps(d)

def test_every_route_declares_auth():
    missing = []
    for r in app.routes:
        if not isinstance(r, APIRoute):
            continue
        guarded = any(getattr(c, "__zynd_guard__", False) for c in _deps(r.dependant))
        public = getattr(r.endpoint, "__zynd_public__", False)
        if not (guarded or public):
            missing.append(f"{','.join(sorted(r.methods))} {r.path}")
    assert not missing, "Routes without an auth declaration:\n" + "\n".join(missing)
```

**Dynamic** (`scripts/probe.py`, runs in CI against staging): for every non-public route, call it with:
1. no token → expect 401
2. user B's token against user A's resource → expect 403
3. a `zsk_` key with the wrong scope → expect 403

Report and fail on any 2xx.

### 10.4 End-to-end (staging)
1. Google signup on cards → `profiles` row, `cards` membership, card `owner_id`, memory seeded with declared facts.
2. Open persona → no login, same `auth.users.id`, `persona` membership, pre-filled onboarding.
3. Claude MCP OAuth → no second login. `remember` → fact appears in persona Memory and in card suggestions → approve → card updates in < 60 s.
4. API key → `zynd login --api-key` → `zynd sync` → suggestions land with `provenance=bridge:*`. Revoke → 401.
5. Legacy: a card published through the zynd.ai Google login is claimed on the first cards login with the same email. The handle is adopted.
6. A magic link with an email already registered via LinkedIn → same user.
7. Account deletion → cards anonymized, memory user gone, keys revoked, `auth.users` row deleted.
8. Negative checks: F1–F3 probes, `zsk_cards` on `/ingest` → 403, persona without `obo` → 403.
9. Later: people search returns only discoverable users, reasons contain only public facts, and anonymous callers see only `public` users.

### 10.5 Commands
```bash
# memory-layer
cd memory-layer && uv run pytest -q            # full (needs docker for integration tests)
# zynd-cards
cd zynd-cards && pytest -q
# agent-persona backend
cd agent-persona/backend && pytest -q
# zynd-bridge
cd zynd-bridge && npm test
# zynd-account
cd zynd-account/py && uv run pytest -q && cd ../ts && pnpm test
```

---

## 11. Appendix: verified code references

| Reference | What |
|---|---|
| `agent-persona/backend/api/persona.py:195,200,296,331,342,446,459,474,496,659,699,711,747,812,850,867` | Persona routes without auth (§3.1.2) |
| `agent-persona/backend/api/meetings.py:33–41` | `ProposalCreate.actor_user_id` / `ProposalRespond.actor_user_id` taken from the body |
| `agent-persona/backend/api/telegram.py:918,938` | Webhook without a secret check; public `/register` |
| `agent-persona/backend/api/oauth_routes.py:140–151` | `?token=` JWT in the query string |
| `agent-persona/backend/agent/memory_client.py:75` | `_make_jwt` using the shared HS256 secret |
| `agent-persona/backend/db/schema.sql` (`dm_threads`, `agent_tasks`) | Participant columns |
| `agent-persona/webapp/src/lib/api.ts:15–28` | Bearer token attached on every call |
| `agent-persona/webapp/src/app/LandingClientWrapper.tsx:95–101` | LinkedIn-only login, `redirectTo: origin` |
| `zynd-cards/api/onboard.py:29,234` | `owner_email` taken from the body |
| `zynd-cards/api/cards.py:228,268` | Duplicate `refresh-memory` |
| `zynd-cards/services/search.py:37`, `services/cards.py:455` | Python scan over ≤ 1,000 cards |
| `zynd-cards/main.py:32` | 6-hour memory refresh loop |
| `memory-layer/app/main.py:151,183,211,292,378,449,528,544` | `/token/exchange`, findability-by-email, social links, path-param user checks, page CSP, pages via service key |
| `memory-layer/app/oauth.py:445,559,575,618` | authorize, callback, mint code, complete |
| `memory-layer/app/services/{token_store,matching,meetings,pages_agent,persona}.py`, `app/tools/{brief,zynd_network}.py` | Direct persona-table access via `supabase_service_key` |
| `memory-layer/app/services/matching.py:46,128` | Public-only facet vectors; text-query search |
| `memory-layer/app/taxonomy.py:66–90` | `FINDABILITY_PREDICATES`, `CLUSTER_PREDICATES` |
| `origin/fix/notion-not-connected-and-test-reliability:app/main.py:407` | `declare-batch` (not on main) |
| `zynd-bridge/src/memory-client.ts:24,110,143` | Local JWT fallback, `declare-batch`, `whoami` |
| `zynd-bridge/src/config.ts:64–81` | Legacy env vars |
| `dashboard/src/app/(site)/auth/callback/route.ts`, `src/hooks/useAuth.tsx`, `src/lib/auth/next-cookie.ts` | Code lifted into `@zynd/account` |
