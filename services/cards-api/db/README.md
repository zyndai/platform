# Frozen — do not add or apply anything here

Schema changes to the shared aafo database now go through the tracked
migration histories in [`packages/db`](../../../packages/db/README.md) (Drizzle).

The SQL in this folder is history. It built cards' tables on the dashboard's
Supabase project (xmfj), and prod has drifted from it (e.g. `owner_email` is
created by no file here), so **never re-run it**. Cards' schema now lives in
the `cards` Postgres schema on the shared database, defined by
`packages/db/cards/` (its own migration history).
