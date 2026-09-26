#!/usr/bin/env bash
# Migration hygiene, run in CI and before opening a PR:
#  - every migration file is listed in the journal and vice versa
#  - file names are NNNN_lower_snake.sql
#  - every migration after the baseline starts with "-- owner: persona|cards|shared"
#  - with BASE_REF set (CI), no already-merged migration file was modified
set -euo pipefail
cd "$(dirname "$0")/.."

fail=0
err() { echo "lint-migrations: $*" >&2; fail=1; }

journal_tags=$(node -e 'for (const e of require("./migrations/meta/_journal.json").entries) console.log(e.tag)')
file_tags=$(cd migrations && ls *.sql | sed 's/\.sql$//')

[ "$journal_tags" = "$file_tags" ] || err "journal and migrations/*.sql differ:
journal: $(echo $journal_tags)
files:   $(echo $file_tags)"

for tag in $file_tags; do
  [[ "$tag" =~ ^[0-9]{4}_[a-z0-9_]+$ ]] || err "$tag.sql: name must be NNNN_lower_snake"
  [[ "$tag" == 0000_* ]] && continue
  head -1 "migrations/$tag.sql" | grep -Eq '^-- owner: (persona|cards|shared)$' \
    || err "$tag.sql: first line must be '-- owner: persona|cards|shared'"
done

if [ -n "${BASE_REF:-}" ]; then
  changed=$(git diff --name-only --diff-filter=MD "$BASE_REF"...HEAD -- migrations/ | grep '\.sql$' || true)
  [ -z "$changed" ] || err "already-merged migrations must never change; add a new one instead:
$changed"
fi

[ $fail -eq 0 ] && echo "lint-migrations: ok ($(echo "$file_tags" | wc -l | tr -d ' ') migrations)"
exit $fail
