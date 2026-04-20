# Backend Scripts

Dev / ops scripts that sit outside the running FastAPI process.

## `nuke_db.py` — clean-slate wiper

Wipes persona / DM / token data so you can re-test registration from scratch.
Destructive. There is no undo. Dev environments only.

### What it does

1. For every row in `persona_agents`, deregisters the persona from the Zynd DNS
   registry (so the next registration doesn't hit `409 already exists`).
2. Deletes every row from these tables:
   - `persona_agents`
   - `dm_threads`, `dm_messages`
   - `agent_tasks`
   - `api_tokens`
   - `chat_messages`
   - `telegram_links`, `telegram_chat_history`
3. *Optional* (`--wipe-users`): deletes every row from `auth.users` via the
   Supabase admin API. Fully resets sign-ins — users will have to sign in
   again from the frontend (and will get a brand new UUID).

### Prerequisites

- Run from the `backend/` directory (the script injects `..` into `sys.path`
  so it can import `config`, `agent.*`, etc.).
- `backend/.env` must be populated with:
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_KEY` (service role, not anon)
  - `ZYND_REGISTRY_URL`
  - `ZYND_DEVELOPER_KEYPAIR_PATH` (the developer seed used to sign deregister calls)
- Python deps already installed via `requirements.txt` (`supabase`, `requests`,
  `cryptography`).

### Usage

From `backend/`:

```bash
# 1. Dry run — shows current row counts and the personas it would deregister.
#    Does not touch anything.
python scripts/nuke_db.py

# 2. Actually wipe persona/DM/token data (keeps auth.users).
python scripts/nuke_db.py --yes

# 3. Full nuke — also delete every auth.users row.
python scripts/nuke_db.py --yes --wipe-users

# 4. Wipe DB only, skip registry deregister (use if dns01.zynd.ai is down).
#    Next registration will hit 409 and fall back to PUT-update.
python scripts/nuke_db.py --yes --skip-deregister
```

### Sample output (dry run)

```
============================================================
Zynd clean-slate nuker
Supabase: https://supabase.shortblogs.org
Registry: https://dns01.zynd.ai
============================================================

Current row counts:
  dm_messages                    0
  dm_threads                     0
  agent_tasks                    0
  api_tokens                     0
  chat_messages                  0
  telegram_chat_history          0
  telegram_links                 0
  persona_agents                 2

Personas to deregister from registry: 2
  - zns:9ca2a9c3... (user 193b12c6-..., idx 0)
  - zns:575b2c8e... (user 2a5e1f52-..., idx 1)

Dry run. Re-run with --yes to actually wipe.
```

### Flags

| Flag                 | Effect                                                          |
| -------------------- | --------------------------------------------------------------- |
| *(none)*             | Dry run. Prints counts + personas that would be deregistered.   |
| `--yes`              | Execute. Required for any mutation.                             |
| `--wipe-users`       | Also delete rows from `auth.users`. Requires `--yes`.           |
| `--skip-deregister`  | Skip registry DELETE calls (faster, or if registry unreachable).|

### When to use which

- **Re-testing persona registration flow** → `--yes` (keeps auth user, so
  you don't have to re-login from the frontend).
- **Switching Supabase projects / testing fresh sign-ups** → `--yes --wipe-users`.
- **Registry is down but I need to reset local state** → `--yes --skip-deregister`.
  Note: next registration will 409, and the backend will fall back to a PUT
  update, which is fine.

### Safety notes

- Always uses `SUPABASE_SERVICE_KEY` (bypasses RLS). Don't run this against a
  production Supabase project unless you actually want to nuke it.
- The deregister loop tolerates `404` from the registry — if the persona was
  already deleted server-side, that's counted as success.
- Table wipes use `.neq("updated_at", "1970-01-01T00:00:00Z")` which matches
  every real row. If you add a table without an `updated_at` column, extend
  the filter logic accordingly.
