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

Grafana only listens on the box's loopback. Reach it through an SSH tunnel:

```bash
ssh -L 3030:127.0.0.1:3030 <user>@<box>      # then http://localhost:3030
```

Log in as `admin`. The password is `GRAFANA_ADMIN_PASSWORD` in `~/.zynd-obs/.env` on
the box. Prometheus (9090) and Loki (3100) are reachable the same way if you want
to run raw queries, and `127.0.0.1:9090/alerts` shows what is firing.

Nothing is public, and nothing here is notified yet: **no alert is sent anywhere**
until a channel (Slack, Telegram, email) and an Alertmanager are added.

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
