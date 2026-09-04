-- X Bot tables: idempotency, account mapping, conversation state
-- tweet_id / x_user_id used as PKs to avoid sequence permission issues in Supabase

create table if not exists x_mentions (
  tweet_id   text primary key,
  x_user_id  text not null,
  text       text,
  status     text not null default 'processed',
  created_at timestamptz not null default now()
);
create index if not exists x_mentions_user_idx on x_mentions (x_user_id);

create table if not exists x_accounts (
  x_user_id  text primary key,
  username   text not null,
  card_id    text references agent_profile_cards(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists x_conversations (
  id               uuid primary key default gen_random_uuid(),
  x_user_id        text not null,
  card_id          text references agent_profile_cards(id),
  status           text not null default 'initial',
  current_question text,
  answered         jsonb not null default '{}',
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index if not exists x_conversations_user_idx on x_conversations (x_user_id);

-- RLS: service role full access (same pattern as agent_profile_cards)
alter table x_mentions      enable row level security;
alter table x_accounts      enable row level security;
alter table x_conversations enable row level security;

drop policy if exists "service role full access on x_mentions"      on x_mentions;
drop policy if exists "service role full access on x_accounts"      on x_accounts;
drop policy if exists "service role full access on x_conversations" on x_conversations;

create policy "service role full access on x_mentions"
  on x_mentions for all to service_role using (true) with check (true);
create policy "service role full access on x_accounts"
  on x_accounts for all to service_role using (true) with check (true);
create policy "service role full access on x_conversations"
  on x_conversations for all to service_role using (true) with check (true);
