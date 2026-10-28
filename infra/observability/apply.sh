#!/usr/bin/env bash
# Installs/updates the monitoring stack on the box. Run as `ubuntu` from a
# checkout:   infra/observability/apply.sh
#
# Copies this directory to ~/.zynd-obs (the compose file bind-mounts configs, and
# a git checkout swaps files under a running container on every deploy), creates
# ~/.zynd-obs/.env with a random Grafana password on first run, starts/updates
# the stack and reloads whatever config changed, and installs the pm2 exporter's
# systemd unit. It never touches the app containers or pm2.
set -Eeuo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${ZYND_OBS_DIR:-$HOME/.zynd-obs}"
COMPOSE=(docker compose -f "$DEST/docker-compose.yml" --env-file "$DEST/.env")

log() { printf '[obs %s] %s\n' "$(date -u +%T)" "$*"; }

mkdir -p "$DEST"
# --delete leaves excluded paths alone, so everything that exists only on the box (.env,
# the metrics.zynd.ai password in .metrics-password) must stay in this exclude list.
changes="$(rsync -rlti --delete --exclude='.env' --exclude='.metrics-password' --exclude='apply.sh' --exclude='.gitkeep' \
  --exclude='README.md' --exclude='.env.example' --exclude='build_dashboards.py' \
  --exclude='tests' --exclude='__pycache__' --exclude='import' "$SRC"/ "$DEST"/ | grep -E '^>f' || true)"

if [[ ! -f "$DEST/.env" ]]; then
  (umask 077; printf 'GRAFANA_ADMIN_PASSWORD=%s\n' "$(openssl rand -hex 16)" > "$DEST/.env")
  log "created $DEST/.env with a random Grafana admin password"
fi

if ! grep -q '^LOGS_API_KEYS=.' "$DEST/.env"; then
  (umask 077; printf 'LOGS_API_KEYS=%s\n' "$(openssl rand -hex 24)" >> "$DEST/.env")
  log "added a LOGS_API_KEYS to $DEST/.env"
fi

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up -d --build --remove-orphans

# `up -d` leaves running containers alone when only a bind-mounted file changed.
if [[ -n "$changes" ]]; then
  log "config changed:"; sed 's/^/  /' <<<"$changes"
  # Prometheus runs without --web.enable-lifecycle (that would let anything on the box
  # stop it through /-/quit), so it is reloaded with SIGHUP. A signal reports nothing
  # back, so the config is checked first: a bad one stops this script here, as a failed
  # /-/reload used to, instead of being silently ignored by Prometheus.
  if grep -q ' prometheus/' <<<"$changes"; then
    "${COMPOSE[@]}" exec -T prometheus promtool check config /etc/prometheus/prometheus.yml
    "${COMPOSE[@]}" kill -s SIGHUP prometheus && log "prometheus reloaded"
  fi
  for svc in loki:loki/ alloy:alloy/ blackbox:blackbox/ grafana:grafana/; do
    if grep -q " ${svc#*:}" <<<"$changes"; then
      "${COMPOSE[@]}" restart "${svc%%:*}"
    fi
  done
fi

# pm2 exporter: a host service (it reads pm2, which isn't in a container), so
# installing its systemd unit needs sudo (ubuntu has it passwordless here).
unit=zynd-pm2-exporter.service
if ! systemctl is-active --quiet "$unit" || grep -q ' pm2-exporter/' <<<"$changes"; then
  if sudo -n true 2>/dev/null; then
    sudo install -m 644 "$DEST/pm2-exporter/$unit" "/etc/systemd/system/$unit"
    sudo systemctl daemon-reload
    sudo systemctl enable "$unit" >/dev/null 2>&1
    sudo systemctl restart "$unit"
    log "$unit (re)started"
  else
    log "WARNING: no passwordless sudo, install $DEST/pm2-exporter/$unit by hand"
  fi
fi

"${COMPOSE[@]}" ps
