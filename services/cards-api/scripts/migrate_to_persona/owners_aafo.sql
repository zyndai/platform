-- Read-only. Run on AAFO after the data copy: which card owners already have
-- an aafo account (so owner_user_id can be linked), which don't yet, and which
-- providers the existing ones use.
--   psql "$AAFO_URL" -X -f owners_aafo.sql
select lower(c.owner_email)                      as owner_email,
       count(*)                                  as cards,
       bool_or(u.id is not null)                 as has_aafo_account,
       string_agg(distinct i.provider, ',')      as aafo_providers
  from cards.agent_profile_cards c
  left join auth.users u      on lower(u.email) = lower(c.owner_email)
  left join auth.identities i on i.user_id = u.id
 where c.owner_email is not null and c.status <> 'archived'
 group by 1
 order by has_aafo_account, cards desc, 1;
