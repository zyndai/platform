# Monitoring

Metrics, logs, dashboards and alerts for the single box (prod and dev together). The
stack lives in `infra/observability/`; its README has the reference detail (labels,
every alert, the gotchas). This page is the operator's guide: where to look when
something is wrong, and how to extend it.

## What you get

| | Tool | Keeps |
|---|---|---|
| Metrics | Prometheus (box, containers, pm2, the two APIs, Caddy, uptime probes) | 30 days |
| Logs | Loki, fed by Alloy (Docker, pm2 and Caddy's access log) | 14 days |
| Dashboards | Grafana, folder "Zynd" | — |
| Alerts | 23 Prometheus rules | — |

Every metric and log line carries `project` and `env`, so one dropdown filters
both. `project` is `cards-api`, `memory-api`, `mcp`, `worker`, `chatgpt-plugin`,
`claude-plugin`, `postgres`, `redis`, `cards-web`, `persona-api`, `persona-web`,
`caddy`, `box` or `monitoring`; `env` is `prod`, `dev`, `shared` or `test`.

## Open it

Two public URLs, both on this box behind host Caddy with a Let's Encrypt certificate
(`infra/single-box/Caddyfile`). Each needs an A record pointing at the box.

| URL | What | Login |
|---|---|---|
| **https://monitor.zynd.ai** | Grafana: dashboards, **Explore** (Prometheus and Loki queries), alerts | Grafana's own accounts |
| **https://metrics.zynd.ai** | Prometheus UI and query API (Status -> Targets, `/alerts`, raw PromQL) | HTTP basic auth, user `prometheus` |

**By IP**, before DNS exists and as a fallback after: the same two tools on their own HTTPS
ports, with self-signed certificates (Caddy's internal CA), so the browser warns once.

| URL | What | Login |
|---|---|---|
| **https://169.58.17.193:3443** | Grafana | Grafana's own accounts |
| **https://169.58.17.193:9443** | Prometheus | basic auth, as above |

The ports must be allowed in ufw by hand: `sudo ufw allow 3443/tcp && sudo ufw allow 9443/tcp`
(better: `sudo ufw allow from <your IP> to any port 3443,9443 proto tcp`). To check that the
warning is for this box's own CA, compare the **root** certificate's SHA-256 in the browser's
certificate viewer with `DF:6B:3C:DF:43:33:9A:54:65:AF:B6:41:6F:25:86:68:06:56:B6:ED:AD:22:E3:15:63:F3:A5:75:49:23:06:C3`
(CN "Caddy Local Authority - 2026 ECC Root", valid to 2036, from
`/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt`). The server certificate
itself is renewed about every 12 hours, so its fingerprint is not stable; to remove the warning,
trust that root on your machine.

Loki stays on loopback; search logs through Grafana's Explore. The tunnel is the fallback
if a public name is down:

```bash
ssh -L 3030:127.0.0.1:3030 -L 9090:127.0.0.1:9090 <user>@<box>   # localhost:3030, localhost:9090
```

**Grafana accounts:** one named account per person (Administration -> Users and access),
not a shared `admin`. The first-run `admin` password is `GRAFANA_ADMIN_PASSWORD` in
`~/.zynd-obs/.env` on the box; change it in Grafana, after which that value is stale.
Give most people the Viewer role: **a Viewer can still search every log line**, and the
logs hold user emails (in request paths such as `/v1/service/findability/<email>`),
client IPs and OAuth query strings, so keep the account list short.

### Public URLs

**metrics.zynd.ai credentials.** Prometheus has no login, so Caddy asks for one. The
bcrypt hash is in `/etc/caddy/metrics-basicauth.conf` on the box (`root:caddy`, 640, not in
git, imported by the Caddyfile); the password is in `~ubuntu/.zynd-obs/.metrics-password`
as `user:password`. To change it:

```bash
PW=$(openssl rand -base64 24 | tr -d '=+/' | cut -c1-28)
printf 'basicauth {\n\tprometheus %s\n}\n' "$(caddy hash-password --plaintext "$PW")" | sudo tee /etc/caddy/metrics-basicauth.conf >/dev/null
printf 'prometheus:%s\n' "$PW" > ~/.zynd-obs/.metrics-password && sudo systemctl reload caddy
```

Prometheus's `/-/quit` and `/-/reload` are enabled for `apply.sh` (it reloads on loopback),
so Caddy answers 403 for them on the public name. Don't enable Prometheus's admin API.

**Moving a name.** The hostnames are constants in `infra/single-box/Caddyfile` and, for
Grafana's redirect URLs, `GF_SERVER_DOMAIN` and `GF_SERVER_ROOT_URL` in
`infra/observability/docker-compose.yml`.

Nothing is notified: **no alert is sent anywhere** until a channel (Slack, Telegram,
email) and an Alertmanager are added.

## Something is wrong: where to look

| Symptom | Start at | Then |
|---|---|---|
| Site or API down | **Edge (Caddy)**: is the public URL probe red? Which hosts return 5xx? | **Project** for that service, then its error logs |
| Everything is slow or flaky | **Box overview**: RAM used %, CPU, OOM kills | "Top memory users" says who; **Project** for them |
| A service keeps restarting | **Box overview**, pm2 / Containers tables (restarts, uptime) | **Logs**, level `error`, same project; the crash is one entry |
| A traceback or a crash | **Logs**, the "Crashes" panel | The record is joined: the whole traceback is one entry |
| Traffic spike or scanners | **Edge**: top 404 paths, clients, user agents | |
| "Did the deploy work?" | **Project**: uptime and restarts reset; error count after | |
| Disk filling | **Box overview**, "Disk used" | `docker system df` on the box (images and build cache are the usual cause) |

Use `level` rather than the pm2 `stream` label: uvicorn writes its INFO lines to
stderr, so `stream="error"` is not "errors". LogQL to paste into Explore:

```
{level="error", env="prod"}
{project="cards-api", env="prod"} |= "Traceback"
sum by (host) (count_over_time({source="caddy", status=~"5.."}[5m]))
```

## Add something

**A pm2 app.** Nothing to do: the exporter and Alloy pick up every pm2 process and its
`<name>-out.log` / `<name>-error.log`, and the process name (minus a `-dev` suffix)
becomes `project`, with `-dev` meaning `env=dev`. Only add a rename if you want a
different project name than the process name (today `api` is shown as `persona-api` and
`web` as `persona-web`; the rule is in `prometheus/prometheus.yml`, job `pm2`, and
`alloy/config.alloy`, `discovery.relabel "pm2"`).

**A Docker service.** Also nothing to do: logs and cAdvisor metrics come from the compose
labels. Compose project `zynd` is prod, `zynd-dev` is dev, and the service name (minus
`-dev`) becomes `project` (today `api` is shown as `memory-api` and `cards` as
`cards-api`). If it is a Python service whose tracebacks span lines, add its project name
to the two `containers_python` regexes in `alloy/config.alloy` so they are joined into one
entry.

**Metrics from a FastAPI app.** Do what `services/cards-api/main.py` does:

```python
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(app, include_in_schema=False)
```

then add a scrape job for its host port in `prometheus/prometheus.yml`. Caddy already
answers 404 for `/metrics` on every public host. The MCP and plugin servers are not
instrumented (FastMCP apps with their own host checks and streaming transport); their
traffic is in the Caddy log and the container series.

**An alert.** Add it to `prometheus/alerts.yml` and a case to `alerts_test.yml`, run the
promtool command at the top of that file, then apply.

**A dashboard.** Edit `grafana/build_dashboards.py`, run it, commit the script and the
JSON. Edits made in Grafana's UI are lost on the next apply.

## Operating the stack

On the box, as `ubuntu`, from a checkout that has `infra/observability/`:

```bash
infra/observability/apply.sh
```

It copies the config to `~/.zynd-obs`, starts or updates the containers (compose
project `zynd-obs`, separate from the app stacks) and reloads what changed. It never
touches the app containers or pm2. The pm2 exporter is a systemd service
(`zynd-pm2-exporter`) that `apply.sh` installs, which needs passwordless sudo.

Test an Alloy pipeline change on a throwaway Alloy before applying it (see "Things
that will bite" in the stack README): `alloy validate` does not catch selector
errors, and renaming a log source re-ingests all the pm2 history.

## Known gaps

- **No notifications.** Choose a channel and add an Alertmanager.
- **Prod has no app metrics yet.** `cards-api` and `memory-api` serve `/metrics` on dev;
  prod gets it with the next prod deploy. Until then those two prod scrape targets are
  down on purpose, and `ScrapeTargetDown` ignores them. After that deploy, delete that
  exclusion (and its test) so they are watched.
- **No error tracking** (Sentry or similar): stack traces come from the logs only.
- **The box's public ports.** 8001, 8002, 8090, 8091 and 5559 are published on the public
  IP by Docker (which bypasses ufw), so `/metrics` and the other endpoints are reachable
  there even though Caddy hides them on the domains. Close them or bind them to loopback.
- **Layout of the dashboards has only been checked by running every query**, not by
  looking at them.
