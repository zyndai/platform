#!/usr/bin/env bash
# Installs/updates the monitoring stack on the box. Run as `ubuntu` from a
# checkout:   infra/observability/apply.sh
#
# Copies this directory to ~/.zynd-obs (the compose file bind-mounts configs, and
# a git checkout swaps files under a running container on every deploy), creates
# ~/.zynd-obs/.env with a random Grafana password on first run, starts/updates
# the stack and reloads whatever config changed. It never touches the app
# containers or pm2.
set -Eeuo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${ZYND_OBS_DIR:-$HOME/.zynd-obs}"
COMPOSE=(docker compose -f "$DEST/docker-compose.yml" --env-file "$DEST/.env")

log() { printf '[obs %s] %s\n' "$(date -u +%T)" "$*"; }

mkdir -p "$DEST"
changes="$(rsync -rlti --delete --exclude='.env' --exclude='apply.sh' --exclude='.gitkeep' \
  --exclude='README.md' --exclude='.env.example' "$SRC"/ "$DEST"/ | grep -E '^>f' || true)"

if [[ ! -f "$DEST/.env" ]]; then
  (umask 077; printf 'GRAFANA_ADMIN_PASSWORD=%s\n' "$(openssl rand -hex 16)" > "$DEST/.env")
  log "created $DEST/.env with a random Grafana admin password"
fi

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up -d --remove-orphans

# `up -d` leaves running containers alone when only a bind-mounted file changed.
if [[ -n "$changes" ]]; then
  log "config changed:"; sed 's/^/  /' <<<"$changes"
  if grep -q ' prometheus/' <<<"$changes"; then
    curl -fsS -X POST http://127.0.0.1:9090/-/reload && log "prometheus reloaded"
  fi
  for svc in loki:loki/ alloy:alloy/ blackbox:blackbox/ grafana:grafana/; do
    if grep -q " ${svc#*:}" <<<"$changes"; then
      "${COMPOSE[@]}" restart "${svc%%:*}"
    fi
  done
fi

"${COMPOSE[@]}" ps
