#!/usr/bin/env bash
# Migration hygiene for every history (identity, persona, cards), run in CI
# and before opening a PR:
#  - every migration file is listed in its journal and vice versa
#  - file names are NNNN_lower_snake.sql
#  - every migration starts with "-- owner: persona|cards|shared"
#    (persona's 0000 baseline included)
#  - with BASE_REF set (CI), no already-merged migration file was modified
set -euo pipefail
cd "$(dirname "$0")/.."

fail=0
err() { echo "lint-migrations: $*" >&2; fail=1; }
total=0

for history in identity persona cards; do
  dir="$history/migrations"
  journal_tags=$(node -e 'for (const e of JSON.parse(require("fs").readFileSync(process.argv[1])).entries) console.log(e.tag)' "$dir/meta/_journal.json")
  file_tags=$(cd "$dir" && ls *.sql | sed 's/\.sql$//')
  [ "$journal_tags" = "$file_tags" ] || err "$history: journal and $dir/*.sql differ:
  journal: $(echo $journal_tags)
  files:   $(echo $file_tags)"
  for tag in $file_tags; do
    total=$((total + 1))
    [[ "$tag" =~ ^[0-9]{4}_[a-z0-9_]+$ ]] || err "$history/$tag.sql: name must be NNNN_lower_snake"
    head -1 "$dir/$tag.sql" | grep -Eq '^-- owner: (persona|cards|shared)$' \
      || err "$history/$tag.sql: first line must be '-- owner: persona|cards|shared'"
  done
done

if [ -n "${BASE_REF:-}" ]; then
  changed=$(git diff --name-only --diff-filter=MD "$BASE_REF"...HEAD -- '*/migrations/*.sql' | grep '\.sql$' || true)
  [ -z "$changed" ] || err "already-merged migrations must never change; add a new one instead:
$changed"
fi

[ $fail -eq 0 ] && echo "lint-migrations: ok ($total migrations in 3 histories)"
exit $fail
