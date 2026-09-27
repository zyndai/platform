# Frozen — do not add or apply anything here

Schema changes to the shared aafo database now go through the tracked
migration histories in [`packages/db`](../../../packages/db/README.md) (Drizzle).

The SQL in this folder is history. It was applied to prod by hand at various
times, and nothing records which files ran, so **never re-run it**. The
current, verified state of the schema is `packages/db/persona/migrations/0000_baseline_persona.sql`
plus the migrations after it.
