#!/usr/bin/env bash
# Fail only if ESLint reports MORE errors than today's baseline (a ratchet).
#
#   eslint-baseline.sh <allowed_errors>      # run inside an app directory
#
# `npm run lint` already exits 1 on main (pre-existing errors, listed nowhere in
# AGENTS.md's baseline table), so a plain lint gate would be red from day one.
# This keeps that debt from growing: lower the number when you fix errors,
# never raise it to make a red build green. Warnings are not counted.
set -uo pipefail

max="${1:?usage: eslint-baseline.sh <allowed_errors>}"

json="$(npx eslint . --format json 2>/dev/null)"
errors="$(printf '%s' "$json" | node -e '
  let s = "";
  process.stdin.on("data", d => (s += d)).on("end", () => {
    try { console.log(JSON.parse(s).reduce((n, f) => n + f.errorCount, 0)); }
    catch { console.log("crashed"); }
  });')"

if [[ "$errors" == "crashed" ]]; then
  echo "eslint-baseline: ESLint did not produce a report (config/parse crash):" >&2
  npx eslint . 2>&1 | tail -n 20 >&2
  exit 1
fi

echo "eslint-baseline: $errors error(s) (baseline allows $max)"
if (( errors > max )); then
  echo "eslint-baseline: FAIL: $((errors - max)) new lint error(s) over the baseline of $max" >&2
  npx eslint . --quiet 2>&1 | tail -n 60 >&2
  exit 1
fi
echo "eslint-baseline: OK"
