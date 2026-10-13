# S11 — Public Cards MCP: implementation status audit

**Verdict: product surface shipped (`458e00a`); gap-closure (rate-limit tests, Cache-Control, discovery flag) applied after this audit.**

Earlier plan `.kilo/plans/1791791233059-s11-public-cards-mcp.md` status header was refreshed to point here.

---

## Evidence in repo

| Ticket item | Status | Where |
|---|---|---|
| FastMCP `cards_public_mcp.py` | Done | `services/memory/app/cards_public_mcp.py` |
| Mount `/cards-public-mcp` (no auth) | Done | `services/memory/app/mcp_http.py` merges second FastMCP when flag on |
| `FEATURE_S11_PUBLIC_MCP` | Done (default **false**) | `services/memory/app/config.py` → `feature_s11_public_mcp` |
| Tools: `search_people`, `get_card`, `ask_card`, `request_intro` stub | Done | same module + tests |
| Resource `zynd://card/{handle}` | Done | `@mcp.resource` |
| Prompt `find-people` | Done | `@mcp.prompt` |
| Thin HTTP wrapper over cards-api | Done | `/ask`, `/v1/agents/search`, `/cards/.../view`, `POST /v1/chat/{handle}` |
| Claimed-only default / `include_unclaimed` | Done | passed through to cards-api; contact strip for unclaimed |
| Rate limit IP\|UA token bucket | Done (code) | `RateLimitMiddleware` → 429 JSON |
| `get_card` TTL cache | Done (in-process) | `s11_get_card_cache_ttl_seconds` (default 60s) |
| Response size caps | Done | `s11_max_response_bytes` |
| `agent_fetch` (tool + coarse category, no full query) | Done | POST `/events` best-effort |
| Caddy `/cards-public-mcp*` | Done | `infra/api-box/Caddyfile`, `infra/single-box/Caddyfile` |
| Compose: mcp → cards | Done | `depends_on: cards`, `CARDS_API_BASE_URL` |
| `/for-ai`, `llms.txt`, `agents.txt` advertise MCP | Done | `apps/cards-web` |
| Unit tests (mocked cards-api) | Done | `services/memory/tests/test_cards_public_mcp.py` |
| Host = memory (locked decision) | Done | not cards-api |

Do **not** confuse with: `cards-api/api/mcp.py` (JWT fact-review REST), memory `/mcp` (OAuth personal tools), persona QuickEnrich `search_people*`.

---

## Acceptance criteria

| Criterion | Met? | Notes |
|---|---|---|
| No-cred `search_people` → claimed cards + `match_reasons` / `fresh_as_of` / `cite_as` | Yes (code + unit test) | Live E2E not re-verified in this session (shell probe blocked) |
| Unclaimed only with `include_unclaimed=true`; no contact | Yes (code + unit test) | |
| Rate limit clear error | Yes (middleware) | **No dedicated unit/load test** |
| p95 latency target | **No** | Ticket: set after baseline — not done |
| Golden-prompt / "when to use" tool descriptions | Partial | Descriptions include "WHEN TO USE"; shared S09 eval harness **not** wired |
| `request_intro` stub | Yes | |
| Personal `/mcp` OAuth unchanged | Yes (by design) | Separate FastMCP instance |

---

## Gaps closed in follow-up

1. **HTTP `Cache-Control`** — middleware sets header on public MCP responses; `get_card` payload includes `cache_control` (`public, max-age=N` / `no-store`).
2. **Rate-limit unit tests** — `TestClient` coverage for 429, personal `/mcp` skip, Cache-Control on OK.
3. **Discovery gated** — `/for-ai`, `llms.txt`, `agents.txt` only advertise when `NEXT_PUBLIC_FEATURE_S11_PUBLIC_MCP=true`.
4. **Stale plan** — `1791791233059-s11-public-cards-mcp.md` status refreshed.

## Still optional / out of scope

- p95 latency baseline + load harness
- S09 shared eval harness (package not built)
- Dedicated health / `/.well-known` MCP registry listing
- Confirm prod `FEATURE_S11_PUBLIC_MCP` in memory `.env.prod` (live GET 405 was a strong signal)

Out of scope: S12 intros, search-quality retuning, weakening personal `/mcp` auth.
