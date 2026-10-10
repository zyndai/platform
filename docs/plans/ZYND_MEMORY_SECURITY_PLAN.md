# ZYND Memory Layer — Security Hardening Plan

> **Status:** proposed — not implemented. Human review required before any
> schema or prod change (AGENTS.md §6: this touches auth, the shared identity
> model, and a prod JWT secret rotation).
>
> **Scope:** `services/memory` (its own Postgres + pgvector DB) and the
> `services/cards-api` bridge into it. Memory's schema is *not* in
> `packages/db` — it lives in `services/memory/sql/schema.sql` (idempotent
> `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE … ADD COLUMN IF NOT EXISTS`).
> Anything that says "migration" here means an idempotent edit to that file,
> rehearsed on a throwaway Postgres before being applied to memory's DB.

This plan addresses seven security issues found in the memory layer's token
issuance and verification. They fall into three themes:

| # | Theme | Issue | Severity |
|---|---|---|---|
| 1 | Mint trust boundary | cards-connect mints a token for any email; trusts the body after only `MEMORY_SERVICE_TOKEN` matches — **resolved by removing the cards MCP surface** | Critical |
| 2 | Secret management | `JWT_SECRET` has a hardcoded default | Critical |
| 3 | Revocation | Personal token is 90 days and minting again does not revoke the old one; same-second disconnect bug | High |
| 4 | Revocation | Opaque OAuth tokens skip `tokens_revoked_at` | High |
| 5 | Constant-time | `findability` / `suggestions` / `approve` / `revoke` compare the service token with `!=` | Medium |
| 6 | Identity key | Email is the account key; `ON CONFLICT (email)` lets one Supabase user overwrite another's `supabase_user_id` | Critical |
| 7 | Token scoping | Token not bound to a server; "never hits the browser" docs are false — **resolved by removing the cards MCP surface** | High |

---

## Guiding design: one audience, one version

Issue 1 and 7 are solved by **removing the cards MCP surface** (see Issue 7's
"Decided" note). Issue 3 is solved by the token-version primitive below, plus
the audience claim as defense-in-depth:

1. **Audience (`aud`)** — every `zynd` JWT carries `aud: "zynd"`; the REST API
   (`app/main.py:current_user`) and the main MCP server (`app/mcp_http.py`)
   accept only that audience. The cards MCP server (`app/cards_mcp.py`) is
   deleted outright, so there is no cards audience to enforce — no cards-only
   token is ever minted. This makes the single remaining token surface
   unambiguous and stops a leaked token from working on a second surface.

2. **Token version (`ver`)** — `users.token_version` is a per-user integer
   counter. Every long-lived personal token embeds the version it was minted
   at. Minting a new personal token increments the version, which instantly
   invalidates every older long-lived token for that user. Disconnect
   increments the version *and* sets `tokens_revoked_at`. Because a version is
   an integer (not a timestamp), the "minted in the same second as sign-out"
   hole disappears entirely for these tokens.

Short-lived OAuth access/refresh tokens (1 h / 30 d) stay governed by the
`tokens_revoked_at` watermark, unchanged in shape.

---

## Issue 2 — `JWT_SECRET` hardcoded default  *(do this first; it unblocks 1/3/7)*

**Root cause** — `services/memory/app/config.py:38`:

```python
jwt_secret: str = "dev-jwt-secret-change-me-in-production-0123456789"
```

If the MCP container boots without `JWT_SECRET`, the server silently uses this
well-known value and will accept anyone's forged token. The same value is
shipped in `services/memory/.env.example:23`.

**Fix**

- `config.py`: change the default to `jwt_secret: str = ""` and add
  `environment: str = "development"` (env `ENVIRONMENT`, default
  `"development"`).
- Add a pydantic model validator (or an explicit check at app import) that
  refuses to start when `environment == "production"` and any of these hold:
  `jwt_secret` is empty, equals the known dev value, or is shorter than 32
  chars.
- `services/memory/.env.example`: remove the literal dev secret; replace with
  `JWT_SECRET=` and a comment that prod must set a strong random value
  (`openssl rand -hex 32`).
- `services/memory/tests/conftest.py`: set `os.environ["JWT_SECRET"]` to a test
  value before any app module import (tests currently rely on the default).

**Prod action (human)** — rotate memory's `JWT_SECRET` to a fresh random value
and update persona-api's `MEMORY_LAYER_JWT_SECRET` to match. This rotation is
also the clean cut-over that invalidates every legacy token, which is what lets
the audience enforcement below go live without a legacy-token compatibility
shim.

**Out of scope but note**: `oauth_client_secret = "zynd-oauth-secret"` and
`deployer_oauth_client_secret = "change-me-deployer-oauth-secret"` have the
same problem; they are used only with a confidential-client check, but should
get the same "non-default or refuse to boot in prod" treatment.

---

## Issue 5 — constant-time service-token compare

**Root cause** — `services/memory/app/main.py`:

- `service_findability` (line 223): `token != settings.memory_service_token`
- `_service_caller` (lines 285): `token != settings.memory_service_token`

`cards_connect` (line 258) already uses `hmac.compare_digest`. The three other
service routes leak timing.

**Fix**

Add one helper and use it everywhere:

```python
def _valid_service_token(token: str) -> bool:
    return bool(settings.memory_service_token) and hmac.compare_digest(
        token, settings.memory_service_token)
```

Replace the `!=` comparisons in `service_findability` and `_service_caller`.
Keep the empty-token fast-fail behind the `bool(...)` guard (returning `False`
early is fine; there is no secret to leak when it is unset).

---

## Issue 4 — opaque OAuth tokens skip revocation

**Root cause** — `services/memory/app/mcp_http.py:222-238`. The JWT path checks
`tokens_revoked`; the opaque fallback only checks `expires_at > NOW()` and never
consults `tokens_revoked_at`.

**Fix**

Resolve the user's watermark in the same query and reject a revoked token:

```sql
SELECT t.user_id, t.scopes, t.created_at, u.tokens_revoked_at
  FROM oauth_access_tokens t
  JOIN users u ON u.id = t.user_id
 WHERE t.token = $1 AND t.expires_at > NOW()
```

Then in `verify_token`, if `tokens_revoked_at is not None and created_at <=
tokens_revoked_at`, return `None`.

**Note** — `oauth_access_tokens` is currently a dormant fallback (the `/token`
endpoint only issues JWTs), but the hole is real if opaque issuance is ever
enabled, so this is defense-in-depth.

---

## Issue 1 — cards-connect mints for any email  *(resolved by surface removal)*

**Root cause** — `services/memory/app/main.py:241-276`. `cards_connect` accepts
`email` / `supabase_user_id` from the JSON body and trusts them once
`MEMORY_SERVICE_TOKEN` matches. It calls `issue_personal_token`, which mints the
*full* persona MCP token. A bug in cards-api — or a stolen service token — mints
a 90-day full-privilege token for any account.

**Resolution — remove the mint path entirely.** Rather than harden
`cards-connect`, delete the whole cards MCP surface (see Issue 7 "Decided").
`/v1/service/cards-connect` and its caller `connect_mcp_sync` are removed, so
the "mint a token for any email" primitive no longer exists in the codebase. No
cards token is ever minted; there is no longer a path for a stolen
`MEMORY_SERVICE_TOKEN` to produce a full persona MCP token.

Fact review (`suggestions` / `approve` / `revoke`) and `/v1/service/disconnect`
are *not* a token-mint path and remain as service-to-service calls.

---

## Issue 7 — token bound to a server / misleading docs

**Root cause** — `app/auth.py` issues one `typ: "access"` token for everything,
and every verifier accepts it, so the same token works on the REST API and both
MCP servers. Separately, `services/cards-api/services/zynd_mcp.py:6-8` and
`services/cards-api/api/mcp.py:8-10` claim "the personal MCP token never enters
the browser", but `mcp_connect` returns the token to the dashboard for the user
to paste.

**Decided: remove the cards MCP server from this repo.** The cards MCP server
(`services/memory/app/cards_mcp.py`) is the whole reason a cards-only token
surface exists, and it is the surface that turns a leaked cards credential into
a memory-write path. Per the review that produced these findings, the cards MCP
server will be **removed from the repo** rather than hardened. This changes the
resolution of Issues 1 and 7:

- `cards-connect` (`/v1/service/cards-connect`) and the `connect_mcp_sync`
  bridge in cards-api are deleted, not fixed. No cards token is minted at all.
- `issue_cards_token` / `aud: "cards-mcp"` is therefore **dropped** from scope.
- `app/cards_mcp.py`, its test `test_cards_mcp.py`, and the cards-api
  `/cards/mcp/*` routes (`api/mcp.py`) plus `services/zynd_mcp.py`
  `connect_mcp_sync` are removed. Fact review (`suggestions` / `approve` /
  `revoke`) stays — it is a service-to-service path, not a paste credential —
  so `services/zynd_mcp.py`'s review helpers and the memory-side
  `/v1/service/suggestions` / `approve` / `revoke` / `disconnect` remain.

**Remaining fix — bind `zynd` tokens to their audience.** After the cards MCP
server is gone there is one token surface, but we still add an explicit
audience for defense-in-depth:

1. Add an `aud` claim to every token in `app/auth.py`:
   - `issue_access_token` / `issue_refresh_token` → `aud: "zynd"`.
   - `issue_personal_token` → `aud: "zynd"` (persona/ChatGPT, full privilege).
2. Enforce the audience at each verifier:
   - `app/main.py:current_user` — accept `aud == "zynd"` only (REST).
   - `app/mcp_http.py:ZyndTokenVerifier` — accept `aud == "zynd"` only.
   - Legacy tokens with no `aud` default to `"zynd"` until the `JWT_SECRET`
     rotation (Issue 2) invalidates them; after rotation the default shim can
     be removed.
3. Correct the false doc comments in the cards-api files (the token was, until
   removal, returned to the dashboard as a paste credential).

---

## Issue 3 — one stolen token is not one session

**Root cause** — `issue_personal_token` (`app/auth.py:59`) is a pure 90-day JWT
with no per-token identity. Minting again produces a second, equally valid
token. Disconnect (`app/services/sessions.py`) is a timestamp watermark floored
to whole seconds, and `tokens_revoked` uses `issued_at < int(revoked_at)` — so
a token minted in the same second as sign-out still passes.

**Fix**

1. **Version counter** — `services/memory/sql/schema.sql`:

   ```sql
   ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version int NOT NULL DEFAULT 0;
   ```

   Every long-lived personal/cards token embeds `ver = token_version`. Minting
   becomes DB-aware:

   ```sql
   UPDATE users SET token_version = token_version + 1 WHERE id = $1
   RETURNING token_version
   ```

   …and that returned value goes into the token. Verifiers fetch
   `token_version` and reject any token whose `ver` differs. Minting a new
   long-lived token therefore revokes every prior long-lived token for that
   user (only the latest paste credential is valid).

2. **Disconnect revokes everything** — `app/services/sessions.py:
   revoke_user_tokens` bumps `token_version` *and* sets `tokens_revoked_at`.
   The MCP `disconnect` tool and `/v1/service/disconnect` already call this;
   no route changes.

3. **Fix the same-second watermark** — change `tokens_revoked` to reject any
   token issued at or before the revocation instant:

   ```python
   return issued_at <= int(revoked_at.timestamp())
   ```

   This only governs the 1 h OAuth access / 30 d refresh tokens now (personal/
   cards are version-gated), so the rare "re-login in the same second" false
   positive is acceptable — the worst case is one extra re-login.

**Trade-off to confirm** — a single `token_version` means a user can hold only
one active long-lived credential at a time (the persona MCP personal token,
now that the cards MCP surface is gone). If they mint a second, the first dies.
That is exactly the "one token = one session" property this issue asks for;
flag if product wants concurrent credentials, which would need a per-audience
version instead.

---

## Issue 6 — email is the account key

**Root cause** — `users.email` is `UNIQUE` (`schema.sql:9`) but
`users.supabase_user_id` is not (`schema.sql:75`). The mint paths upsert with
`ON CONFLICT (email)`:

- `/token/exchange` (`main.py:194-199`) and `_resolve_user_and_mint_code`
  (`oauth.py:588-593`): `DO UPDATE SET supabase_user_id = EXCLUDED.supabase_user_id`
  — a different Supabase user with the same email overwrites the link and takes
  the account.
- `cards_connect` (`main.py:268-274`): `COALESCE` — removed with the cards MCP
  surface (Issue 1), so this specific path disappears; the `/token/exchange` /
  `_resolve_user_and_mint_code` upserts are the ones that remain and must be
  fixed.

**Fix**

1. **Make `supabase_user_id` the authoritative key once present** —
   `schema.sql`:

   ```sql
   CREATE UNIQUE INDEX IF NOT EXISTS users_supabase_user_id_key
     ON users (supabase_user_id) WHERE supabase_user_id IS NOT NULL;
   ```

2. **Resolve by `sub` first, email second.** In every mint/resolve path,
   look up `WHERE supabase_user_id = $sub`; only fall back to email for legacy
   rows that have no `sub` (xmfj cards users before the aafo cutover).

3. **Never overwrite a linked `sub`.** On upsert, if the row already has a
   non-null `supabase_user_id` that differs from the verified one, treat it as
   a distinct identity (create a separate memory user or reject with a clear
   "account conflict" error) — do not silently merge or take over.

   Concretely, replace the `ON CONFLICT (email)` upserts with a resolve-then-
   update/insert sequence keyed on `sub`, and drop the `supabase_user_id =
   EXCLUDED.supabase_user_id` overwrite.

**Interaction with the in-flight migration** — this is the most delicate change
because it touches the email-dedup semantics the aafo cutover currently relies
on (xmfj users have no aafo `sub` yet). Keep email as a secondary/legacy key
for rows with `supabase_user_id IS NULL`, but never let email override an
existing `sub` link. This needs the memory owner in the loop (`AGENTS.md §4/§6`).

---

## Files touched

| File | Change |
|---|---|
| `services/memory/app/config.py` | `jwt_secret=""`, add `environment`, boot guard |
| `services/memory/app/auth.py` | `aud` claim; `ver` claim; audience-aware decode |
| `services/memory/app/main.py` | `_valid_service_token`; **remove** `/v1/service/cards-connect`; sub-first resolve |
| `services/memory/app/mcp_http.py` | enforce `aud:"zynd"`; opaque-token revocation check |
| `services/memory/app/cards_mcp.py` | **delete file** |
| `services/memory/app/oauth.py` | sub-first resolve; no `sub` overwrite |
| `services/memory/app/services/sessions.py` | bump `token_version`; `<=` watermark |
| `services/memory/sql/schema.sql` | `token_version` column; partial unique index on `supabase_user_id` |
| `services/memory/.env.example` | remove dev secret; document prod secret |
| `services/memory/tests/conftest.py` | set `JWT_SECRET` for tests |
| `services/memory/tests/test_cards_mcp.py` | **delete file** |
| `services/cards-api/api/mcp.py` | **remove** `/mcp/connect` + `/mcp/disconnect` (keep review routes); fix doc comments |
| `services/cards-api/services/zynd_mcp.py` | **remove** `connect_mcp_sync` (keep review helpers); fix doc comments |

## Tests

Add/extend in `services/memory/tests/` (run `cd services/memory && uv run pytest -q -m "not integration"`):

- `test_cards_connect.py` — **delete** (cards-connect route is removed).
- `test_cards_mcp.py` — **delete** (cards MCP server removed).
- `test_security_fixes.py` / new `test_audience.py` — a `zynd` token is accepted
  by `current_user` and `ZyndTokenVerifier`; tokens with a foreign/unknown `aud`
  are rejected.
- `test_sessions.py` — same-second disconnect now revokes (version + `<=`);
  minting a new long-lived token revokes the prior one (version bump).
- `test_mcp_http.py` — opaque token with `tokens_revoked_at` set is rejected.
- `test_auth.py` / `test_oauth.py` — update any test that relied on the
  hardcoded `jwt_secret` default (conftest now injects a test secret).
- cards-api: remove `mcp_connect`/`mcp_disconnect` coverage from
  `test_mcp_connector.py`; keep `test_zynd_memory.py` review-helper tests.

## Rollout order

1. Issue 2 (config + boot guard) — safe, no behavior change except prod boot
   requirement. Ship config + tests.
2. Issue 5 (constant-time) — trivial, ship with 1.
3. Issue 4 (opaque revocation) — defense-in-depth, ship with 1.
4. **Remove the cards MCP server** (Issue 1/7): delete
   `services/memory/app/cards_mcp.py`, `/v1/service/cards-connect`, cards-api's
   `connect_mcp_sync` + `/cards/mcp/connect`/`/disconnect`, and the related
   tests. This is a surface removal, not a fix — no token is minted for cards
   at all, which eliminates the "full persona MCP for any email" blast radius.
   Fact review (`suggestions`/`approve`/`revoke`) and `/v1/service/disconnect`
   remain as service-to-service paths.
5. Schema prep (Issue 3 + 6): add `token_version` column and the partial unique
   index on `supabase_user_id` — both expand-only and idempotent. Rehearse on
   throwaway Postgres, then apply to memory's DB (human, §6).
6. Audience + version (Issues 3/7): add `aud` to `zynd` tokens and `ver` to
   long-lived tokens; sub-first resolve. No cards audience is needed (cards MCP
   is gone). Legacy tokens still default to `zynd`.
7. **Rotate `JWT_SECRET`** (human, §6) — invalidates all legacy tokens; remove
   the no-`aud` default shim afterwards.

## Rollback

- Issue 2: re-set `JWT_SECRET` to the previous value and redeploy; the boot
  guard only fails closed when prod `ENVIRONMENT` is set.
- Issue 3/7: `token_version` and `aud` are additive. To roll back, revert the
  code and the version check; the `token_version` column can stay (unused) or
  be dropped later (expand-only discipline: drop in a later migration).
- Issue 6: the partial unique index is additive; rolling back the resolve logic
  restores email-keyed behavior. The index itself may block future conflicting
  inserts — drop it only after confirming no code depends on it.

## Human sign-offs required (AGENTS.md §6)

- Memory's own Postgres schema change (token_version + unique index).
- Prod `JWT_SECRET` rotation + updating `MEMORY_LAYER_JWT_SECRET` in persona-api.
- Confirming the **cards MCP server removal** (Issues 1/7) with the cards owner
  — the `/cards/mcp/*` UI surface and the "Connect MCP" flow are being retired,
  not replaced; fact review (`suggestions`/`approve`/`revoke`) stays.
- Confirming the "one active long-lived credential per user" product trade-off
  (Issue 3) and the email↔sub identity semantics (Issue 6) with the memory and
  cards owners, since both touch the aafo cutover in progress.
