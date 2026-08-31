-- Zynd Agent Profile Cards
-- One row per card. `card` holds the full AgentProfileCard JSON; `search_tsv`
-- is a generated tsvector column backed by a GIN index for on-site search.

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
                    coalesce((select string_agg(s->>'name',' ')
                              from jsonb_array_elements(card->'skills') s), '')
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
