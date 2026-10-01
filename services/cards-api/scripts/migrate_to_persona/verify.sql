-- Read-only. Run on BOTH sides and diff the output:
--   psql "$XMFJ_URL" -X -At -v schema=public -f verify.sql > xmfj.txt
--   psql "$AAFO_URL" -X -At -v schema=cards  -f verify.sql > aafo.txt
--   diff xmfj.txt aafo.txt
-- Expected: identical, run BEFORE rewrite_avatar_urls.sql (that changes the card md5).
-- If you merged into a live aafo (copy_tables.sh default), aafo will ALSO hold the
-- cards created there since the switch, so counts will be higher and the md5 will
-- differ. Use the per-id check at the bottom instead.
set search_path = :schema, extensions, public;

select 'rows ' || status, count(*)::text from agent_profile_cards group by status
union all select 'x_accounts', count(*)::text from x_accounts
union all select 'x_conversations', count(*)::text from x_conversations
union all select 'x_mentions', count(*)::text from x_mentions
union all select 'embeddings', count(embedding)::text from agent_profile_cards
union all select 'claim tokens', count(claim_token_hash)::text from agent_profile_cards
union all select 'ids+card md5', md5(string_agg(id || md5(card::text), ',' order by id)) from agent_profile_cards
union all select 'fts top10 "engineer"', coalesce(string_agg(id, ','), '') from (select id from search_cards_fts('engineer', 10)) t
order by 1;

-- Per-id fingerprint, for the merge case: save from both sides and run
--   comm -23 xmfj_ids.txt aafo_ids.txt   (lines only xmfj has = cards that did not arrive)
\echo '--- id|card md5 (one per row) ---'
select id || '|' || md5(card::text) from agent_profile_cards order by id;
