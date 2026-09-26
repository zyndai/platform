-- Read-only checks on aafo BEFORE applying 0002–0004 (the cards migrations).
-- Every row should say ok = true. Paste into the aafo SQL editor.
select 'is aafo (persona tables present)' as check, to_regclass('public.persona_agents') is not null as ok
union all select 'is NOT xmfj (no developer_keys)', to_regclass('public.developer_keys') is null
union all select 'baseline recorded (drizzle.__drizzle_migrations exists)', to_regclass('drizzle.__drizzle_migrations') is not null
union all select 'no agent_profile_cards yet', to_regclass('public.agent_profile_cards') is null
union all select 'no x_accounts yet', to_regclass('public.x_accounts') is null
union all select 'no x_mentions yet', to_regclass('public.x_mentions') is null
union all select 'no x_conversations yet', to_regclass('public.x_conversations') is null
union all select 'no skill_names() yet', to_regproc('public.skill_names') is null
union all select 'no match_cards() yet', not exists (select 1 from pg_proc where proname = 'match_cards')
union all select 'no search_cards_fts() yet', not exists (select 1 from pg_proc where proname = 'search_cards_fts')
union all select 'vector extension available to install', exists (select 1 from pg_available_extensions where name = 'vector')
union all select 'extensions schema exists', to_regnamespace('extensions') is not null;
