-- Link each card to its aafo user (cards.agent_profile_cards.owner_user_id →
-- auth.users) by email. Run on AAFO only, after the data copy. Idempotent: safe
-- to re-run whenever more owners have signed in. Only fills NULLs, never
-- overwrites a link cards-api already stamped.
--
--   psql "$AAFO_URL" -X -v ON_ERROR_STOP=1 -f backfill_owner_user_id.sql
--
-- "unmatched" owners have no aafo account yet. Nothing is wrong: ownership
-- still works through owner_email, and cards-api stamps owner_user_id the
-- first time they sign in and edit/publish. Re-run this later to link them
-- sooner.
with unique_users as (          -- skip emails shared by 2+ aafo users (ambiguous)
  select min(id::text)::uuid as id, lower(email) as email
    from auth.users
   where email is not null
   group by lower(email)
  having count(*) = 1
), m as (
  update cards.agent_profile_cards c
     set owner_user_id = u.id
    from unique_users u
   where c.owner_user_id is null
     and c.owner_email is not null
     and u.email = lower(c.owner_email)
  returning c.id
)
select count(*) as linked_now from m;

select count(*) filter (where owner_user_id is not null) as linked_total,
       count(distinct lower(owner_email)) filter (where owner_email is not null and owner_user_id is null and status <> 'archived')
         as owners_without_aafo_user
  from cards.agent_profile_cards;
