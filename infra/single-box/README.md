# infra/single-box: whole monorepo on one box

The repo's other `infra/` folders describe two boxes with domains
(`persona-box` = pm2, `api-box` = compose + Caddy). This folder runs **every**
service on one Ubuntu box: host Caddy serves five HTTPS domains, and the
backends are also reachable directly by IP:port.
First used on `169.58.17.193` (2026-09-29).

| Domain | What | Behind Caddy |
|---|---|---|
| `persona.zynd.ai` | persona-web; `/api/*` -> persona-api (same rule as the live persona box) | pm2 `web` :3001, pm2 `api` :8000 |
| `persona.api.zynd.ai` | persona-api | pm2 `api` :8000 |
| `cards.zynd.ai` | cards-web | pm2 `cards-web` :3002 |
| `cards.api.zynd.ai` | cards-api | Docker `cards` :8002 |
| `api.zynd.ai` | memory API; `/mcp*` -> MCP; legacy `/cards* /ask* /onboard* /v1*` -> cards-api (as in `infra/api-box/Caddyfile`) | Docker `api` :8001, `mcp` :8090 |

Direct ports (plain HTTP, open in ufw): 8001 memory, 8090 memory MCP, 8002
cards-api, 3002 cards-web, 3000 persona (`/api/*` -> backend, rest -> web).
Memory's Postgres (pgvector) and Redis are Docker-internal only. The worker
has no port. persona-api's own :8000 stays on localhost.

Certificates: Caddy issues them itself once a name's A record points at the
box and ports 80/443 are open. Until then the HTTPS names don't work; after
pointing DNS, `sudo systemctl reload caddy` retries issuance immediately.

## Bring-up

Needs Docker + compose plugin, Node 22, pm2, python3-venv, Caddy (all from apt /
NodeSource). Checkout at `/home/ubuntu/zynd-platform`, owned by `ubuntu`.

```bash
# 1. env files (all gitignored; see "Env" below)
# 2. containers: memory stack + cards-api
docker compose -p zynd -f infra/api-box/docker-compose.prod.yml \
  -f infra/single-box/docker-compose.override.yml \
  --env-file ~/.zynd-box/compose.env up -d --build postgres redis api worker mcp cards
# 3. web apps (NEXT_PUBLIC_* are baked in at build time)
(cd apps/persona-web && npm ci && npm run build)
(cd apps/cards-web && npm ci && npm run build)
# 4. persona-api venv
python3 -m venv services/persona-api/.venv && services/persona-api/.venv/bin/pip install -r services/persona-api/requirements.txt
# 5. Caddy + pm2
sudo install -m644 infra/single-box/Caddyfile /etc/caddy/Caddyfile && sudo systemctl restart caddy
pm2 start infra/single-box/ecosystem.config.js --only web,cards-web && pm2 save
# 6. firewall (SSH first, then the service ports, in and out)
sudo ufw allow in 22/tcp
for p in 80 443 3000 3002 8001 8002 8090; do sudo ufw allow in $p/tcp; sudo ufw allow out $p/tcp; done
sudo ufw enable
```

Docker publishes 8001/8002/8090 through its own iptables chain, which bypasses
ufw's INPUT rules; publishing them in the override is what exposes them. A
provider-level (cloud) firewall, if any, is separate from ufw.

**persona-api is started separately**: `pm2 start infra/single-box/ecosystem.config.js --only api`.
It refuses to boot without the Zynd developer keypair at
`~/.zynd/developer.json` (or `ZYND_DEVELOPER_KEYPAIR_PATH`) because it
re-derives every active persona's key on startup. Use the same key the live
persona boxes use, or every derived key is wrong.

## Update

```bash
git pull
docker compose ... up -d --build            # same command as above
(cd apps/persona-web && npm run build) && (cd apps/cards-web && npm run build)
pm2 restart api web cards-web               # name apps; not `restart all`
```

## Env

Per-service env files, none committed: `services/memory/.env.prod`,
`services/cards-api/.env.prod`, `services/persona-api/.env`,
`apps/persona-web/.env.local`, `apps/cards-web/.env.local`, plus
`~/.zynd-box/compose.env` (`POSTGRES_PASSWORD`) and `~/.zynd-box/shared.env`
(the generated `JWT_SECRET` / `MEMORY_SERVICE_TOKEN` shared across services).

Cross-service values that must match: persona-api `MEMORY_LAYER_JWT_SECRET` =
memory `JWT_SECRET`; cards-api `MEMORY_SERVICE_TOKEN` = memory
`MEMORY_SERVICE_TOKEN`. On this box cards-api reaches memory over the compose
network (`MEMORY_LAYER_URL=http://api:8000`); persona-api over
`http://127.0.0.1:8001`.

Where the domains go (server-side env, none committed). The web values are
baked in at build time: rebuild and `pm2 restart web cards-web` after changing.

| File | Values |
|---|---|
| `apps/persona-web/.env.local` | `NEXT_PUBLIC_API_URL=https://persona.api.zynd.ai`, `NEXT_PUBLIC_MEMORY_API_URL` and `NEXT_PUBLIC_ZYND_API_URL=https://api.zynd.ai`, `NEXT_PUBLIC_PAGE_BASE_URL` and `NEXT_PUBLIC_SITE_URL=https://persona.zynd.ai` |
| `apps/cards-web/.env.local` | `NEXT_PUBLIC_API_URL=https://cards.api.zynd.ai`, `NEXT_PUBLIC_ZYND_API_URL=https://api.zynd.ai`, `NEXT_PUBLIC_SITE_URL=https://cards.zynd.ai` |
| `services/persona-api/.env` | `FRONTEND_URL` and `PUBLIC_PAGE_BASE_URL=https://persona.zynd.ai` (`FRONTEND_URL` is the only CORS origin) |
| `services/cards-api/.env.prod` | `FRONTEND_URL` and `SITE_BASE_URL=https://cards.zynd.ai`, `API_BASE_URL=https://cards.api.zynd.ai` |
| `services/memory/.env.prod` | `PUBLIC_BASE_URL=https://api.zynd.ai`, `MCP_PUBLIC_BASE_URL=https://api.zynd.ai/mcp`, `CORS_ORIGINS=https://persona.zynd.ai,https://cards.zynd.ai` |

Deliberate choices, same as the live dev channel (persona-api `CLAUDE.md`):

- `ZYND_WEBHOOK_BASE_URL` and the OAuth redirect URIs **stay on prod**
  (`persona.zynd.ai`). At startup persona-api re-points registry entities at
  that base URL, so a second instance must not claim it.
- No `TELEGRAM_BOT_TOKEN`: only prod may own the bot's webhook.
- No `NEXT_PUBLIC_GA_ID` (no analytics from a test box), no dev-bearer keys on
  memory.
- cards-api runs against aafo's `cards` schema (`SUPABASE_DB_SCHEMA=cards`),
  trusting aafo's issuer; the tables are empty until the cards cutover.

## Cutover caveats

- `persona.zynd.ai` and `api.zynd.ai` currently belong to the live boxes.
  Pointing them here is a prod cutover: this box's memory Postgres is a fresh,
  empty database, so users' memory data and MCP client grants stay on the old
  api box until they are migrated. cards data is still on xmfj (cards-api here
  reads aafo's empty `cards` schema).
- Sign-in uses aafo's Auth redirect list: `persona.zynd.ai/**` and
  `cards.zynd.ai/**` are already in it; the web apps are built against the
  domains, so they don't work from a bare IP.
