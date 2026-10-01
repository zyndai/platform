-- Read-only. Run on XMFJ before the cutover to size the login risk:
--   psql "$XMFJ_URL" -X -f owners_xmfj.sql
--
-- cards-web is LinkedIn-only (plan D12), so each card owner has to sign in to
-- aafo with a LinkedIn account whose email equals the card's owner_email.
-- Owners who only ever used Google on xmfj ("google" rows below) are the ones
-- who need to use LinkedIn with the same email, or get reassigned by support.
select coalesce(i.provider, '(no xmfj user)') as provider,
       count(distinct lower(c.owner_email))   as owners
  from public.agent_profile_cards c
  left join auth.users u      on lower(u.email) = lower(c.owner_email)
  left join auth.identities i on i.user_id = u.id
 where c.owner_email is not null and c.status <> 'archived'
 group by 1 order by 2 desc;
