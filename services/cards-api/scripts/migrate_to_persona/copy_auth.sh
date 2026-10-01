#!/usr/bin/env bash
# Copy card owners' accounts from xmfj's Supabase Auth into aafo's, keeping
# their user ids, emails, password hashes and provider identities, so they can
# sign in on aafo without being treated as new users.
#
#   copy_auth.sh SRC_URL DST_URL [--apply] [--all-users] [--keep]
#
#   SRC_URL  xmfj Postgres connection string (or env SRC_URL)
#   DST_URL  aafo Postgres connection string (or env DST_URL)
#   (direct or session pooler, port 5432; not the 6543 transaction pooler)
#
# Run it AFTER copy_tables.sh and BEFORE backfill_owner_user_id.sql.
#
# What is copied
#   auth.users       only people whose email is an owner_email on an xmfj card
#                    (--all-users: every xmfj account, which includes every
#                    dashboard developer; usually not what you want)
#   auth.identities  those users' provider identities (google, linkedin_oidc, …)
#   NOT copied: sessions, refresh tokens, MFA factors, one-time tokens, audit
#   log. Nobody stays signed in across projects (tokens are signed by the
#   project that issued them) and anyone with MFA must enrol it again.
#
# What is NEVER touched
#   An aafo account that already has the same id or the same email (compared
#   case-insensitively) is left alone and listed. Those people already exist
#   on aafo; backfill_owner_user_id.sql links their cards to that account.
#
# Columns: only columns present on BOTH sides, minus generated ones
# (confirmed_at, identities.email), so it survives GoTrue schema differences
# between the two projects. The differences are printed.
#
# Dry run by default: the whole load runs inside a transaction that is rolled
# back, so constraint, NOT NULL and trigger problems show up with nothing
# written. --apply commits the same transaction.
set -euo pipefail

SRC_URL="${SRC_URL:-}"; DST_URL="${DST_URL:-}"
APPLY=0; ALL=0; KEEP=0; pos=()
for a in "$@"; do
  case "$a" in
    --apply) APPLY=1 ;; --all-users) ALL=1 ;; --keep) KEEP=1 ;;
    -h|--help) sed -n '2,33p' "$0"; exit 0 ;;
    --*) echo "unknown flag: $a" >&2; exit 2 ;;
    *) pos+=("$a") ;;
  esac
done
[ "${#pos[@]}" -ge 1 ] && SRC_URL="${pos[0]}"
[ "${#pos[@]}" -ge 2 ] && DST_URL="${pos[1]}"
if [ -z "$SRC_URL" ] || [ -z "$DST_URL" ]; then
  echo "usage: copy_auth.sh SRC_URL DST_URL [--apply] [--all-users] [--keep]" >&2; exit 2
fi
[ "$SRC_URL" != "$DST_URL" ] || { echo "SRC_URL and DST_URL are identical, refusing." >&2; exit 2; }

q() { psql "$1" -v ON_ERROR_STOP=1 -X -At -c "$2"; }

# ── Guards ──────────────────────────────────────────────────────────────────
[ "$(q "$SRC_URL" "select to_regclass('public.developer_keys') is not null")" = "t" ] \
  || { echo "SRC is not xmfj (public.developer_keys missing). Refusing." >&2; exit 1; }
[ "$(q "$DST_URL" "select to_regclass('cards.agent_profile_cards') is not null and to_regclass('public.persona_agents') is not null and to_regclass('public.developer_keys') is null")" = "t" ] \
  || { echo "DST is not aafo (needs cards.agent_profile_cards + public.persona_agents, and no developer_keys). Refusing." >&2; exit 1; }

# A trigger on auth.users (a welcome email, a profile row, a webhook) would fire
# once per copied user. persona has none in its migrations, but the Supabase
# dashboard can add some, so look.
TRIG="$(q "$DST_URL" "select string_agg(tgname, ', ') from pg_trigger where tgrelid = 'auth.users'::regclass and not tgisinternal")"
if [ -n "$TRIG" ] && [ "${ALLOW_AUTH_TRIGGERS:-}" != "1" ]; then
  echo "aafo has trigger(s) on auth.users: $TRIG" >&2
  echo "Each copied user would fire them. Check what they do; to proceed anyway set ALLOW_AUTH_TRIGGERS=1." >&2
  exit 1
fi

WORK="$(mktemp -d)"; chmod 700 "$WORK"
cleanup() { if [ "$KEEP" = 1 ]; then echo "work dir kept: $WORK (holds emails and password hashes)"; else rm -rf "$WORK"; fi; }
trap cleanup EXIT

# ── Columns both sides share, non-generated ─────────────────────────────────
cols() { q "$1" "select column_name from information_schema.columns where table_schema='auth' and table_name='$2' and is_generated='NEVER' order by column_name" | LC_ALL=C sort; }
common() { # table → quoted, comma-separated list of shared columns
  comm -12 <(cols "$SRC_URL" "$1") <(cols "$DST_URL" "$1") | sed 's/.*/"&"/' | paste -sd, -
}
show_diff() {
  local only_src only_dst
  only_src="$(comm -23 <(cols "$SRC_URL" "$1") <(cols "$DST_URL" "$1") | paste -sd' ' -)"
  only_dst="$(comm -13 <(cols "$SRC_URL" "$1") <(cols "$DST_URL" "$1") | paste -sd' ' -)"
  [ -z "$only_src" ] || echo "  auth.$1 columns only on xmfj (not copied): $only_src"
  [ -z "$only_dst" ] || echo "  auth.$1 columns only on aafo (take their default): $only_dst"
}
UCOLS="$(common users)"; ICOLS="$(common identities)"
for need in '"id"' '"email"'; do
  case ",$UCOLS," in *",$need,"*) ;; *) echo "auth.users has no shared $need column?" >&2; exit 1 ;; esac
done
case ",$ICOLS," in *',"provider_id",'*) ;; *) echo "auth.identities has no provider_id on both sides; this script targets current GoTrue." >&2; exit 1 ;; esac
echo "column differences:"; show_diff users; show_diff identities

# Which xmfj users: card owners (or everyone), minus deleted and anonymous accounts
WHERE="u.email is not null"
case ",$UCOLS," in *',"deleted_at",'*) WHERE="$WHERE and u.deleted_at is null" ;; esac
case ",$UCOLS," in *',"is_anonymous",'*) WHERE="$WHERE and u.is_anonymous is not true" ;; esac
[ "$ALL" = 1 ] || WHERE="$WHERE and lower(u.email) in (select lower(owner_email) from public.agent_profile_cards where owner_email is not null)"

# ── Export from xmfj (read-only) ────────────────────────────────────────────
UQ="$(echo "$UCOLS" | sed 's/"\([a-z_]*\)"/u."\1"/g')"
IQ="$(echo "$ICOLS" | sed 's/"\([a-z_]*\)"/i."\1"/g')"
psql "$SRC_URL" -v ON_ERROR_STOP=1 -X -c "\copy (select $UQ from auth.users u where $WHERE) to '$WORK/users.csv' csv"
psql "$SRC_URL" -v ON_ERROR_STOP=1 -X -c "\copy (select $IQ from auth.identities i join auth.users u on u.id = i.user_id where $WHERE) to '$WORK/identities.csv' csv"
echo "xmfj accounts selected: $(q "$SRC_URL" "select count(*) from auth.users u where $WHERE")"

# ── Load into aafo in one transaction: commit with --apply, else roll back ──
{
cat <<SQL
begin;
create temp table su (like auth.users including defaults);
create temp table si (like auth.identities including defaults);
\\copy su ($UCOLS) from '$WORK/users.csv' csv
\\copy si ($ICOLS) from '$WORK/identities.csv' csv

create temp table _plan as
select s.id, s.email,
       case when exists (select 1 from auth.users d where d.id = s.id)
              then 'skip: same id already on aafo'
            when exists (select 1 from auth.users d where lower(d.email) = lower(s.email))
              then 'skip: aafo account with this email exists'
            else 'copy' end as action
  from su s;

insert into auth.users ($UCOLS)
select $UCOLS from su where id in (select id from _plan where action = 'copy');

insert into auth.identities ($ICOLS)
select $ICOLS from si i
 where i.user_id in (select id from _plan where action = 'copy')
   and not exists (select 1 from auth.identities d where d.provider = i.provider and d.provider_id = i.provider_id);

\\echo
\\echo 'plan:'
select action, count(*) from _plan group by 1 order by 1;
\\echo 'accounts left alone (the person already exists on aafo, so their cards link by email):'
select email, action from _plan where action <> 'copy' order by 1;
\\echo 'identities now on the copied accounts, by provider:'
select i.provider, count(*) from auth.identities i where i.user_id in (select id from _plan where action = 'copy') group by 1 order by 2 desc;
\\echo 'copied accounts with no identity (they can only sign in by email, set a password or link a provider):'
select count(*) from _plan p where p.action = 'copy' and not exists (select 1 from auth.identities i where i.user_id = p.id);
SQL
if [ "$APPLY" = 1 ]; then echo "commit;"; else echo "rollback;"; fi
} > "$WORK/load.sql"

psql "$DST_URL" -v ON_ERROR_STOP=1 -X -q -f "$WORK/load.sql"

echo
if [ "$APPLY" = 1 ]; then
  echo "COMMITTED. aafo auth.users now: $(q "$DST_URL" "select count(*) from auth.users")"
  echo "Next: psql \"\$AAFO_URL\" -X -f backfill_owner_user_id.sql   (links cards to these accounts)"
else
  echo "DRY RUN: everything above ran inside a transaction that was rolled back. Nothing was written."
  echo "Re-run with --apply to commit."
fi
