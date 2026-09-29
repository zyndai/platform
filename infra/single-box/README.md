# infra/single-box: whole monorepo on one box, reached by IP:port

The repo's other `infra/` folders describe two boxes with domains
(`persona-box` = pm2, `api-box` = compose + Caddy). This folder runs **every**
service on one Ubuntu box with no domains, over plain HTTP on ports.
First used on `169.58.17.193` (2026-09-29).

| Port | What | Runs as |
|---|---|---|
| 3000 | persona-web, and persona-api under `/api/*` | host Caddy -> pm2 `web` (:3001) + pm2 `api` (:8000) |
| 3002 | cards-web | pm2 `cards-web` |
| 8001 | memory API | Docker (`api`) |
| 8090 | memory MCP (`/mcp`) | Docker (`mcp`) |
| 8002 | cards-api | Docker (`cards`) |

Memory's Postgres (pgvector) and Redis are Docker-internal only. The worker has
no port. persona-api's own :8000 stays on localhost.

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
for p in 3000 3002 8001 8002 8090; do sudo ufw allow in $p/tcp; sudo ufw allow out $p/tcp; done
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

Deliberate choices, same as the live dev channel (persona-api `CLAUDE.md`):

- `ZYND_WEBHOOK_BASE_URL` and the OAuth redirect URIs **stay on prod**
  (`persona.zynd.ai`). At startup persona-api re-points registry entities at
  that base URL, so a second instance must not claim it.
- No `TELEGRAM_BOT_TOKEN`: only prod may own the bot's webhook.
- No `NEXT_PUBLIC_GA_ID` (no analytics from a test box), no dev-bearer keys on
  memory.
- cards-api runs against aafo's `cards` schema (`SUPABASE_DB_SCHEMA=cards`),
  trusting aafo's issuer; the tables are empty until the cards cutover.

## Limits of IP:port access

- Sign-in (Supabase OAuth) and the OAuth "connect" flows redirect to the
  Supabase / provider-registered URLs. `http://<ip>:3000/**` and
  `http://<ip>:3002/**` are not in aafo's Auth redirect list, and the provider
  callbacks point at prod, so browser login will not complete here until a
  human adds them (or real domains are pointed at the box).
- Everything is plain HTTP.
