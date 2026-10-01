#!/usr/bin/env bash
# Run a pytest command and fail only on NEW failures.
#
#   pytest-baseline.sh <allowed_failures> -- <pytest command...>
#
# AGENTS.md §5 lists known, pre-existing failures per service (they need env
# vars or a live Postgres/Redis that CI doesn't have). This passes while the
# number of failed + errored tests is <= that baseline, and fails the moment
# it goes above it. Lower the number when you fix one; never raise it to make a
# red build green.
set -uo pipefail

max="${1:?usage: pytest-baseline.sh <allowed_failures> -- <command...>}"
shift
[[ "${1:-}" == "--" ]] && shift

out="$("$@" 2>&1)"
rc=$?
printf '%s\n' "$out" | tail -n 60

if [[ $rc -eq 0 ]]; then
  echo "pytest-baseline: all tests passed"
  exit 0
fi
if [[ $rc -ne 1 ]]; then
  echo "pytest-baseline: pytest exited $rc (usage error / interrupted / no tests), not a plain test failure" >&2
  exit "$rc"
fi

summary="$(printf '%s\n' "$out" | grep -E '[0-9]+ (passed|failed|error)' | tail -n 1)"
bad="$(printf '%s' "$summary" | grep -oE '[0-9]+ (failed|errors?)' | awk '{s += $1} END {print s + 0}')"
echo "pytest-baseline: $bad failed/errored (baseline allows $max) — $summary"

if (( bad > max )); then
  echo "pytest-baseline: FAIL: $((bad - max)) new failure(s) over the baseline of $max" >&2
  printf '%s\n' "$out" | grep -E '^(FAILED|ERROR)' >&2
  exit 1
fi
echo "pytest-baseline: OK (only the known baseline failures)"
