-- Point avatar URLs inside card JSON at aafo's storage instead of xmfj's.
-- Run on AAFO, after copy_avatars.py has uploaded the files. Idempotent.
--
--   psql "$AAFO_URL" -X -v ON_ERROR_STOP=1 \
--     -v src='https://<xmfj-ref>.supabase.co/storage/v1/object/public/avatars/' \
--     -v dst='https://<aafo-ref>.supabase.co/storage/v1/object/public/avatars/' \
--     -f rewrite_avatar_urls.sql
--
-- (copy_avatars.py prints this command with the right values filled in.)
\if :{?src}
\else
  \echo 'set -v src=… and -v dst=… (see header)'
  \quit
\endif
begin;
update cards.agent_profile_cards set card            = replace(card::text,            :'src', :'dst')::jsonb where card::text            like '%' || :'src' || '%';
update cards.agent_profile_cards set scrape_raw      = replace(scrape_raw::text,      :'src', :'dst')::jsonb where scrape_raw::text      like '%' || :'src' || '%';
update cards.agent_profile_cards set user_intent     = replace(user_intent::text,     :'src', :'dst')::jsonb where user_intent::text     like '%' || :'src' || '%';
update cards.agent_profile_cards set suggested_posts = replace(suggested_posts::text, :'src', :'dst')::jsonb where suggested_posts::text like '%' || :'src' || '%';
commit;

-- Anything still pointing at xmfj storage (should be 0 rows):
select id, handle from cards.agent_profile_cards
 where card::text like '%' || :'src' || '%' or scrape_raw::text like '%' || :'src' || '%'
    or user_intent::text like '%' || :'src' || '%' or suggested_posts::text like '%' || :'src' || '%';
