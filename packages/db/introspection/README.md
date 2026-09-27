# Catalog exports of prod

Evidence that the migrations match the real database. Each file is the
single-cell output of `../scripts/catalog.sql`, run in the Supabase SQL
editor (read-only) and saved as-is: raw text, or the editor's JSON/CSV
export. `npm run db:drift` accepts all three.

Name files `<project>-<YYYY-MM-DD>.txt`, e.g. `aafo-2026-09-26.txt`.
Schema only: no row data, no secrets.
