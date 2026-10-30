#!/usr/bin/env bash
# One scheduled call to prod cards-api's /internal/* endpoints, run from cron on the
# single box (infra/single-box/crontab). Replaces the GitHub Actions schedules, which
# GitHub throttles: morning-digest got ~10% of its runs.
#
#   run-job.sh <name> <path> <max-seconds>
#
# - Calls cards-api on localhost, so DNS, Caddy and TLS are not in the path.
# - CRON_SECRET comes from cards-api's own env file; nothing new to configure.
# - One run per job at a time (flock), like the workflows' `concurrency` groups.
# - On failure, posts to Mattermost if ~/.zynd-box/alerts.env defines
#   MATTERMOST_WEBHOOK_URL; always logs. On success touches <name>.last-ok.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

name="${1:?job name}"; path="${2:?endpoint path}"; max="${3:?max seconds}"
BOX="${ZYND_BOX:-/home/ubuntu/.zynd-box}"
REPO="${ZYND_ROOT:-/home/ubuntu/zynd-platform}"
API="${CARDS_API_LOCAL:-http://127.0.0.1:8002}"
OUT="$BOX/cron"
mkdir -p "$OUT"
log() { printf '[%s] %s: %s\n' "$(date -u +%FT%TZ)" "$name" "$*" >> "$OUT/$name.log"; }

exec 9>"$OUT/$name.lock"
flock -n 9 || { log "previous run still going; skipped"; exit 0; }

alert() { # <message>
  log "FAILED: $1"
  local url
  url="$(grep -m1 '^MATTERMOST_WEBHOOK_URL=' "$BOX/alerts.env" 2>/dev/null | cut -d= -f2- | tr -d '"'"'" || true)"
  [[ -n "$url" ]] || return 0
  curl -fsS -m 15 -X POST -H 'Content-Type: application/json' "$url" \
    -d "{\"text\":\"Scheduled job \`$name\` failed on the box: $1. Log: ~/.zynd-box/cron/$name.log\"}" >/dev/null 2>&1 || true
}

secret="$(grep -m1 '^CRON_SECRET=' "$REPO/services/cards-api/.env.prod" 2>/dev/null | cut -d= -f2- | tr -d '"'"'" | tr -d '\r' || true)"
[[ -n "$secret" ]] || { alert "CRON_SECRET not found in services/cards-api/.env.prod"; exit 1; }

body="$(mktemp)"; trap 'rm -f "$body"' EXIT
code="$(curl -sS -m "$max" -o "$body" -w '%{http_code}' -X POST "$API$path" \
  -H "Authorization: Bearer $secret" 2>>"$OUT/$name.log")"
rc=$?
if [[ $rc -eq 0 && "$code" =~ ^2 ]]; then
  log "ok ($code) $(head -c 300 "$body" | tr '\n' ' ')"
  date -u +%s > "$OUT/$name.last-ok"
else
  alert "curl exit $rc, HTTP $code, $(head -c 200 "$body" | tr '\n' ' ')"
  exit 1
fi
