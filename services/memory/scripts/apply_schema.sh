#!/usr/bin/env bash
# Apply sql/schema.sql to the running Postgres container.
# Idempotent — safe to run anytime the schema changes.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec -T postgres psql -U zynd -d zynd < sql/schema.sql
echo "schema applied."
