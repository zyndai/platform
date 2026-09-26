-- Read-only checks on aafo BEFORE applying the cards history
-- (cards/migrations). Every row should say ok = true. Paste into the aafo
-- SQL editor.
select 'is aafo (persona tables present)' as check, to_regclass('public.persona_agents') is not null as ok
union all select 'is NOT xmfj (no developer_keys)', to_regclass('public.developer_keys') is null
union all select 'persona baseline recorded (drizzle.__persona_migrations)', to_regclass('drizzle.__persona_migrations') is not null
union all select 'no cards schema yet', to_regnamespace('cards') is null
union all select 'no cards tables in public either', to_regclass('public.agent_profile_cards') is null
union all select 'vector extension available to install', exists (select 1 from pg_available_extensions where name = 'vector')
union all select 'extensions schema exists', to_regnamespace('extensions') is not null
union all select 'service_role exists', exists (select 1 from pg_roles where rolname = 'service_role');
