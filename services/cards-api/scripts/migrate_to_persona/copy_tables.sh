#!/usr/bin/env bash
# Copy the 4 cards tables from xmfj (dashboard project, schema `public`) into
# aafo (persona project, schema `cards`). See docs/plans/ZYND_DB_UNIFY_PLAN.md §6.
#
#   copy_tables.sh SRC_URL DST_URL [--apply] [--replace] [--keep]
#
#   SRC_URL  xmfj Postgres connection string (or env SRC_URL)
#   DST_URL  aafo Postgres connection string (or env DST_URL)
#
# Use the DIRECT connection or the *session* pooler (port 5432) for both.
# The transaction pooler (port 6543) breaks pg_dump and psql --single-transaction.
#
# Dry run by default: dumps xmfj (read-only), retargets the dump, prints row
# counts on both sides and what would happen. Writes nothing to aafo.
#
# Modes (with --apply):
#   merge (default)  Adds rows aafo doesn't have yet. Never deletes or
#                    overwrites. Safe once people are already using cards on
#                    aafo. A row is skipped if aafo has the same id OR the
#                    same handle (the skips are counted and listed).
#   --replace        Truncates the 4 aafo tables first, then loads. This is
#                    the plan's original rehearsal/cutover behaviour. It
#                    DESTROYS anything created on aafo since the switch, so
#                    it refuses to run if aafo already holds cards, unless
#                    you also set I_KNOW_THIS_DELETES_AAFO_CARDS=1.
#
# --keep   keep the work dir (it holds owner emails = PII); default is to
#          delete it on exit.
set -euo pipefail

SRC_URL="${SRC_URL:-}"
DST_URL="${DST_URL:-}"
APPLY=0
REPLACE=0
KEEP=0
pos=()
for a in "$@"; do
  case "$a" in
    --apply) APPLY=1 ;;
    --replace) REPLACE=1 ;;
    --keep) KEEP=1 ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    --*) echo "unknown flag: $a" >&2; exit 2 ;;
    *) pos+=("$a") ;;
  esac
done
[ "${#pos[@]}" -ge 1 ] && SRC_URL="${pos[0]}"
[ "${#pos[@]}" -ge 2 ] && DST_URL="${pos[1]}"
if [ -z "$SRC_URL" ] || [ -z "$DST_URL" ]; then
  echo "usage: copy_tables.sh SRC_URL DST_URL [--apply] [--replace] [--keep]" >&2
  exit 2
fi
if [ "$SRC_URL" = "$DST_URL" ]; then
  echo "SRC_URL and DST_URL are identical, refusing." >&2
  exit 2
fi

TABLES=(agent_profile_cards x_accounts x_conversations x_mentions)
psql_q() { psql "$1" -v ON_ERROR_STOP=1 -X -At -c "$2"; }

# ── Guard: the URLs must be the projects we think they are ──────────────────
if [ "$(psql_q "$SRC_URL" "select to_regclass('public.developer_keys') is not null")" != "t" ]; then
  echo "SRC is not xmfj (public.developer_keys missing). Refusing." >&2; exit 1
fi
if [ "$(psql_q "$DST_URL" "select to_regclass('cards.agent_profile_cards') is not null and to_regclass('public.persona_agents') is not null")" != "t" ]; then
  echo "DST is not aafo with the cards schema applied (cards.agent_profile_cards / public.persona_agents missing). Refusing." >&2; exit 1
fi
if [ "$(psql_q "$DST_URL" "select to_regclass('public.developer_keys') is null")" != "t" ]; then
  echo "DST has public.developer_keys, it looks like xmfj. Refusing." >&2; exit 1
fi

WORK="$(mktemp -d)"
chmod 700 "$WORK"
cleanup() { [ "$KEEP" = 1 ] && echo "work dir kept: $WORK" || rm -rf "$WORK"; }
trap cleanup EXIT

# ── 1. Dump ─────────────────────────────────────────────────────────────────
dump_args=()
for t in "${TABLES[@]}"; do dump_args+=(-t "public.$t"); done
echo "dumping xmfj (read-only)…"
pg_dump "$SRC_URL" --data-only --no-owner --no-privileges "${dump_args[@]}" > "$WORK/raw.sql"

# ── 2. Retarget public.* → <target>.* ───────────────────────────────────────
# Only touches COPY headers and setval lines. Data rows (card JSON etc.) are
# skipped, so text like "public.example" inside a card is never rewritten.
# Fails if any other statement still mentions public.
# $1 = target schema; merge mode loads into pg_temp staging tables.
retarget() {
  awk -v target="$1" '
    in_copy { print; if ($0 == "\\.") in_copy = 0; next }
    /^COPY public\./ { sub(/^COPY public\./, "COPY " target "."); in_copy = 1; print; next }
    /^SELECT pg_catalog\.setval\(.public\./ { sub(/setval\(.public\./, "setval(\x27" target "."); print; next }
    /^SET transaction_timeout/ { next }   # pg_dump 17+ emits it; older servers reject it
    /^--/ || /^$/ { print; next }
    /public\./ { print "unexpected reference to public.: " $0 > "/dev/stderr"; bad = 1 }
    { print }
    END { exit bad }
  ' "$WORK/raw.sql" > "$2"
}

# ── 3. Counts ───────────────────────────────────────────────────────────────
counts() { # $1 url  $2 schema
  for t in "${TABLES[@]}"; do
    printf '  %-22s %s\n' "$t" "$(psql_q "$1" "select count(*) from $2.$t")"
  done
}
echo "xmfj (public):";  counts "$SRC_URL" public
echo "aafo (cards):";   counts "$DST_URL" cards
DST_CARDS="$(psql_q "$DST_URL" "select count(*) from cards.agent_profile_cards")"

if [ "$REPLACE" = 1 ]; then
  retarget cards "$WORK/load.sql"
  if [ "$DST_CARDS" != "0" ] && [ "${I_KNOW_THIS_DELETES_AAFO_CARDS:-}" != "1" ]; then
    echo "--replace would delete the $DST_CARDS cards already on aafo." >&2
    echo "If they are only a previous rehearsal, re-run with I_KNOW_THIS_DELETES_AAFO_CARDS=1." >&2
    exit 1
  fi
  echo "mode: REPLACE (truncate the 4 aafo tables, then load)"
else
  retarget pg_temp "$WORK/load.sql"
  echo "mode: MERGE (add rows aafo lacks; skip same id or same handle; delete nothing)"
fi

if [ "$APPLY" != 1 ]; then
  echo
  echo "DRY RUN: dump parsed and retargeted OK, nothing written to aafo. Re-run with --apply."
  exit 0
fi

# ── 4. Load, one transaction ────────────────────────────────────────────────
if [ "$REPLACE" = 1 ]; then
  psql "$DST_URL" -q -v ON_ERROR_STOP=1 -X --single-transaction \
    -c "truncate cards.x_mentions, cards.x_conversations, cards.x_accounts, cards.agent_profile_cards" \
    -f "$WORK/load.sql"
else
  cat > "$WORK/stage.sql" <<'SQL'
-- staging copies (temp: vanish with the session); generated search_tsv is excluded by pg_dump
create temp table agent_profile_cards (like cards.agent_profile_cards including defaults);
create temp table x_accounts          (like cards.x_accounts          including defaults);
create temp table x_conversations     (like cards.x_conversations     including defaults);
create temp table x_mentions          (like cards.x_mentions          including defaults);
SQL
  cat > "$WORK/merge.sql" <<'SQL'
create temp table _skipped as
  select s.id, s.handle,
         case when exists (select 1 from cards.agent_profile_cards d where d.id = s.id)
              then 'id already on aafo' else 'handle taken on aafo' end as why
    from pg_temp.agent_profile_cards s
   where exists (select 1 from cards.agent_profile_cards d where d.id = s.id or d.handle = s.handle);

insert into cards.agent_profile_cards
  (id, status, handle_github, handle_x, card, created_at, updated_at, published_at, handle,
   embedding, scrape_raw, user_intent, owner_email, suggested_posts, claim_token_hash)
select id, status, handle_github, handle_x, card, created_at, updated_at, published_at, handle,
       embedding, scrape_raw, user_intent, owner_email, suggested_posts, claim_token_hash
  from pg_temp.agent_profile_cards s
 where s.id not in (select id from _skipped);

insert into cards.x_accounts (x_user_id, username, card_id, created_at, updated_at)
select x_user_id, username, card_id, created_at, updated_at from pg_temp.x_accounts s
 where (card_id is null or exists (select 1 from cards.agent_profile_cards c where c.id = s.card_id))
on conflict (x_user_id) do nothing;

insert into cards.x_conversations (id, x_user_id, card_id, status, current_question, answered, created_at, updated_at)
select id, x_user_id, card_id, status, current_question, answered, created_at, updated_at from pg_temp.x_conversations s
 where (card_id is null or exists (select 1 from cards.agent_profile_cards c where c.id = s.card_id))
on conflict (id) do nothing;

insert into cards.x_mentions (tweet_id, x_user_id, text, status, created_at)
select tweet_id, x_user_id, text, status, created_at from pg_temp.x_mentions
on conflict (tweet_id) do nothing;

\echo
\echo 'skipped cards (kept the aafo version):'
select id, handle, why from _skipped order by id;
SQL
  psql "$DST_URL" -q -v ON_ERROR_STOP=1 -X --single-transaction \
    -f "$WORK/stage.sql" -f "$WORK/load.sql" -f "$WORK/merge.sql"
fi

echo
echo "aafo (cards) after load:"; counts "$DST_URL" cards
echo
echo "Next: run verify.sql on both sides, then copy_avatars.py, then backfill_owner_user_id.sql."
