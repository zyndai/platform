#!/usr/bin/env bash
# Installs infra/single-box/crontab into the current user's crontab as a marked block,
# leaving any other entries alone. Idempotent. Run by deploy.sh (prod) when the crontab
# or these scripts change, or by hand: infra/single-box/cron/install.sh [--remove]
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
begin='# BEGIN zynd-platform jobs (managed by infra/single-box/cron/install.sh)'
end='# END zynd-platform jobs'

current="$(crontab -l 2>/dev/null || true)"
kept="$(awk -v b="$begin" -v e="$end" '$0==b{skip=1} !skip{print} $0==e{skip=0}' <<<"$current")"

if [[ "${1:-}" == "--remove" ]]; then
  printf '%s\n' "$kept" | crontab -
  echo "removed zynd-platform jobs from the crontab"; exit 0
fi

{ [[ -n "$kept" ]] && printf '%s\n' "$kept"; printf '%s\n' "$begin"; cat "$here/../crontab"; printf '%s\n' "$end"; } | crontab -
echo "installed $(grep -c 'run-job.sh' "$here/../crontab") zynd-platform jobs"
