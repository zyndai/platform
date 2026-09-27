#!/usr/bin/env bash
# Create a Python 3.12 venv in each service (services/<svc>/.venv, gitignored)
# with its runtime deps plus pytest. Same layout the servers use, so
# `npm run dev` and `npm test` at the root can call .venv/bin/* directly.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }

for svc in persona-api cards-api; do
  echo "== services/$svc"
  [ -x "services/$svc/.venv/bin/python" ] || uv venv --python 3.12 "services/$svc/.venv"
  uv pip install --python "services/$svc/.venv" -r "services/$svc/requirements.txt" pytest pytest-asyncio
done

# memory has a pyproject (no lockfile committed): install its deps + the dev group
# without `uv sync`, which would write a new uv.lock into the repo.
echo "== services/memory"
[ -x services/memory/.venv/bin/python ] || uv venv --python 3.12 services/memory/.venv
uv pip install --python services/memory/.venv -r services/memory/pyproject.toml --group services/memory/pyproject.toml:dev

echo "Python services ready."
