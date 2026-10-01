# Move cards data from xmfj (dashboard project) to aafo (persona project)

Phase G/H of [`docs/plans/ZYND_DB_UNIFY_PLAN.md`](../../../../docs/plans/ZYND_DB_UNIFY_PLAN.md) (§6).
**A person runs these** (AGENTS.md §6: prod SQL). Everything is a dry run until
you pass `--apply`. xmfj is only ever read.

| Script | Does | Where it writes |
|---|---|---|
| `copy_tables.sh` | `agent_profile_cards`, `x_accounts`, `x_conversations`, `x_mentions`: xmfj `public` → aafo `cards` | aafo |
| `copy_auth.sh` | Card owners' accounts (`auth.users` + `auth.identities`) xmfj → aafo, same user ids | aafo auth |
| `copy_avatars.py` | `avatars` storage bucket, same paths and content-types | aafo storage |
| `rewrite_avatar_urls.sql` | avatar URLs inside card JSON: xmfj host → aafo host | aafo |
| `backfill_owner_user_id.sql` | link each card to its aafo `auth.users` row by email | aafo |
| `verify.sql` | counts and per-card fingerprints, to diff both sides | none (read-only) |
| `owners_xmfj.sql` / `owners_aafo.sql` | who can and can't sign in on aafo (read-only) | none |

## What you need

- Connection strings for **both** databases: Supabase → Project Settings →
  Database → *Direct* or *Session pooler* (port **5432**). Not the transaction
  pooler (6543); `pg_dump` and `--single-transaction` break on it.
- `psql` and `pg_dump` (any version ≥ the servers').
- For the avatars: each project's URL and **service-role** key (Settings → API).
- `pip install httpx` (already in `services/cards-api/requirements.txt`).

Put the secrets in your shell only (`read -s`), never in a file in the repo:

```bash
read -rs XMFJ_URL; read -rs AAFO_URL; export XMFJ_URL AAFO_URL
```

## Run order

```bash
cd services/cards-api/scripts/migrate_to_persona

# 0. Size the login risk (xmfj). Owners who only used Google need LinkedIn on aafo.
psql "$XMFJ_URL" -X -f owners_xmfj.sql

# 1. Cards + X-bot tables. Dry run first.
./copy_tables.sh "$XMFJ_URL" "$AAFO_URL"
./copy_tables.sh "$XMFJ_URL" "$AAFO_URL" --apply

# 2. Verify. Diff must be empty on a clean copy (see "Already live on aafo?").
psql "$XMFJ_URL" -X -At -v schema=public -f verify.sql > /tmp/xmfj.txt
psql "$AAFO_URL" -X -At -v schema=cards  -f verify.sql > /tmp/aafo.txt
diff /tmp/xmfj.txt /tmp/aafo.txt

# 3. Avatars, then rewrite the URLs (copy_avatars.py prints the exact command)
export SRC_SUPABASE_URL=https://<xmfj-ref>.supabase.co SRC_SERVICE_KEY=…
export DST_SUPABASE_URL=https://<aafo-ref>.supabase.co  DST_SERVICE_KEY=…
python copy_avatars.py            # dry run
python copy_avatars.py --apply

# 4. Accounts: copy card owners' logins so they are not treated as new users.
#    The dry run executes the whole load in a transaction and rolls it back.
./copy_auth.sh "$XMFJ_URL" "$AAFO_URL"
./copy_auth.sh "$XMFJ_URL" "$AAFO_URL" --apply

# 5. Link cards to aafo users (safe to repeat; owners who haven't signed in yet stay unlinked)
psql "$AAFO_URL" -X -v ON_ERROR_STOP=1 -f backfill_owner_user_id.sql
psql "$AAFO_URL" -X -f owners_aafo.sql      # who still has no aafo account
rm /tmp/xmfj.txt /tmp/aafo.txt              # they contain owner ids
```

`verify.sql`'s `ids+card md5` must be compared **before** step 3's URL rewrite.

## Already live on aafo?

Merge mode is the default for that reason. If people have already created
cards on aafo since the switch, `copy_tables.sh`:

- **adds** every xmfj card aafo doesn't have, with its X-bot rows;
- **skips**, and lists, a card whose **id or handle** already exists on aafo
  (aafo's version wins; the X-bot account rows that pointed at a skipped card
  are skipped with it);
- **never deletes or overwrites** anything.

`verify.sql` counts will then be higher on aafo than on xmfj; check that no id
from xmfj is missing instead:

```bash
psql "$XMFJ_URL" -X -At -v schema=public -f verify.sql | sed -n '/^---/,$p' | tail -n +2 | cut -d'|' -f1 | sort > xmfj_ids.txt
psql "$AAFO_URL" -X -At -v schema=cards  -f verify.sql | sed -n '/^---/,$p' | tail -n +2 | cut -d'|' -f1 | sort > aafo_ids.txt
comm -23 xmfj_ids.txt aafo_ids.txt      # ids that did not arrive: should be only the skipped ones listed above
```

`--replace` (truncate + load) is for rehearsals and the planned cutover when aafo
holds nothing real. It refuses to run if aafo has cards, unless
`I_KNOW_THIS_DELETES_AAFO_CARDS=1`.

## Logins (`copy_auth.sh`)

Copies, for every person whose email is a card's `owner_email` on xmfj:

- the `auth.users` row, **with the same user id**, email, confirmation state
  and password hash (if they ever used one);
- their `auth.identities` rows (Google, LinkedIn, …).

It does **not** copy dashboard developers (use `--all-users` only if you really
want them), sessions, refresh tokens or MFA factors. Tokens are signed by the
project that issued them, so everyone signs in once more after the move, but as
the same user, and anyone with MFA must enrol it again.

Safe by construction:

- Someone who **already has an aafo account** (same id, or same email ignoring
  case) is skipped and listed, never overwritten. Their cards link to that
  account through `backfill_owner_user_id.sql`.
- It copies only columns both projects have, minus generated ones, and prints
  any differences, so a GoTrue version gap doesn't break it.
- It refuses to run if aafo has a trigger on `auth.users` (each copied user
  would fire it) unless `ALLOW_AUTH_TRIGGERS=1`.
- The dry run really executes the inserts, inside a transaction that is rolled
  back, so constraint problems show up before anything is written.
- The work dir holds emails and password hashes; it is deleted on exit (`--keep`
  to inspect it, then delete it yourself).

### Which sign-in methods then work on aafo

A copied account is found by its **email**. When someone signs in on aafo with a
provider, Supabase matches the provider identity first, then falls back to an
existing account with the same verified email and links to it. So:

- **LinkedIn** (what cards-web offers today): works for every owner whose
  LinkedIn email equals the email on their account.
- **Google**: the copied Google identity only helps if the **Google provider is
  enabled on aafo** (Authentication → Providers, with an OAuth client whose
  redirect URI is aafo's) **and cards-web shows a Google button**. Plan D12
  removed it. Without both, a Google-only owner has to use LinkedIn with the
  same email. `owners_xmfj.sql` shows how many that is.
- **Email + password** users keep their password (the hash is copied).
- **Magic link** needs SMTP on aafo (plan D12), still not set up.

An owner whose sign-in email differs from the one on the card still needs
support to change `owner_email`.

## If cards-api still shows an empty dashboard after the copy

The listing is `owner_email ilike <signed-in email>`
(`services/cards.py:get_card_by_owner`). Check, in order:

1. cards-api's env points at aafo **and** `SUPABASE_DB_SCHEMA=cards`
   (otherwise it reads `public`, where aafo has no cards table).
2. `TRUSTED_SUPABASE_URLS` includes aafo's URL and `AAFO_ISSUER` is
   `https://<aafo-ref>.supabase.co/auth/v1`, so aafo tokens are accepted.
3. The email on the signed-in LinkedIn account equals the card's `owner_email`
   (`select owner_email from cards.agent_profile_cards where handle = '…'`).
