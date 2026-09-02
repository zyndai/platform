-- Zynd Agent Profile Cards
-- One row per card. `card` holds the full AgentProfileCard JSON; `search_tsv`
-- is a generated tsvector column backed by a GIN index for on-site search.

create or replace function skill_names(card jsonb) returns text
language sql immutable as $$
  select coalesce(string_agg(s->>'name', ' ' order by s->>'name'), '')
  from jsonb_array_elements(coalesce(card->'skills', '[]'::jsonb)) s
$$;

create table if not exists agent_profile_cards (
  id            text primary key,
  status        text not null default 'draft',
  handle_github text,
  handle_x      text,
  card          jsonb not null,
  search_tsv    tsvector generated always as (
                  to_tsvector('english',
                    coalesce(card->'identity'->>'name','') || ' ' ||
                    coalesce(card->'identity'->>'headline','') || ' ' ||
                    coalesce(card->>'summary','') || ' ' ||
                    skill_names(card)
                  )
                ) stored,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  published_at  timestamptz
);

create index if not exists agent_profile_cards_tsv_idx
  on agent_profile_cards using gin (search_tsv);
create index if not exists agent_profile_cards_status_idx
  on agent_profile_cards (status);

alter table agent_profile_cards enable row level security;

drop policy if exists "public read published cards" on agent_profile_cards;
create policy "public read published cards"
  on agent_profile_cards for select
  using (status = 'published');

drop policy if exists "service role full access on cards" on agent_profile_cards;
create policy "service role full access on cards"
  on agent_profile_cards for all
  to service_role
  using (true)
  with check (true);

-- Phase 1: canonical slug handle
alter table agent_profile_cards add column if not exists handle text unique;
create index if not exists agent_profile_cards_handle_idx on agent_profile_cards (handle);

-- Backfill: github handle → x handle → slugified name from card JSON
update agent_profile_cards
set handle = coalesce(
  nullif(lower(handle_github), ''),
  nullif(lower(handle_x), ''),
  lower(regexp_replace(
    regexp_replace(card->'identity'->>'name', '[^a-zA-Z0-9]+', '-', 'g'),
    '^-+|-+$', '', 'g'
  ))
)
where handle is null and status = 'published';

-- Append short id suffix to resolve any uniqueness conflicts (rare)
update agent_profile_cards a
set handle = a.handle || '-' || substr(a.id, 1, 4)
where handle in (
  select handle from agent_profile_cards group by handle having count(*) > 1
) and id not in (
  select min(id) from agent_profile_cards group by handle having count(*) > 1
);

-- Raw scraped source texts per provider for re-synthesis and auditing
alter table agent_profile_cards add column if not exists scrape_raw jsonb;

-- User intent answers from onboarding follow-up questions
alter table agent_profile_cards add column if not exists user_intent jsonb;
