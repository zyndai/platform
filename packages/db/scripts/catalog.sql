-- Read-only catalog of the public schema, as ONE text cell (so the Supabase
-- SQL editor's row limit never truncates it). Run it on prod in the SQL
-- editor and save the cell to introspection/aafo-YYYY-MM-DD.txt; run it on a
-- scratch DB with psql. scripts/check-drift.sh diffs the two.
-- First line identifies the project: developer_keys=true means xmfj.
select string_agg(line, E'\n' order by line) from (
  select '0 project | developer_keys=' || (to_regclass('public.developer_keys') is not null)::text
      || ' agent_profile_cards=' || (to_regclass('public.agent_profile_cards') is not null)::text as line
  union all
  select 'extension | ' || extname || ' | ' || extversion || ' | schema=' || extnamespace::regnamespace::text from pg_extension
  union all
  select 'column | ' || c.relname || '.' || a.attname || ' | ' || format_type(a.atttypid, a.atttypmod)
    || case when a.attgenerated = 's' then ' GENERATED ALWAYS AS (' || pg_get_expr(d.adbin, d.adrelid) || ') STORED'
            when d.adbin is not null then ' DEFAULT ' || pg_get_expr(d.adbin, d.adrelid) else '' end
    || case when a.attnotnull then ' NOT NULL' else '' end
  from pg_attribute a join pg_class c on c.oid = a.attrelid
  left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
  where c.relnamespace = 'public'::regnamespace and c.relkind = 'r' and a.attnum > 0 and not a.attisdropped
  union all
  select 'constraint | ' || conrelid::regclass::text || '.' || conname || ' | ' || pg_get_constraintdef(oid)
  from pg_constraint where connamespace = 'public'::regnamespace and conrelid <> 0
  union all
  select 'index | ' || indexname || ' | ' || indexdef from pg_indexes where schemaname = 'public'
  union all
  select 'trigger | ' || t.tgrelid::regclass::text || '.' || t.tgname || ' | ' || pg_get_triggerdef(t.oid)
  from pg_trigger t join pg_class c on c.oid = t.tgrelid
  where not t.tgisinternal and c.relnamespace = 'public'::regnamespace
  union all
  select 'function | ' || p.oid::regprocedure::text || ' | acl=' || coalesce(p.proacl::text, 'default')
      || E'\n' || pg_get_functiondef(p.oid)
  from pg_proc p
  where p.pronamespace = 'public'::regnamespace and p.prokind = 'f'
    and not exists (select 1 from pg_depend d where d.objid = p.oid and d.deptype = 'e')
  union all
  select 'rls | ' || relname || ' | enabled=' || relrowsecurity::text || ' forced=' || relforcerowsecurity::text
  from pg_class where relnamespace = 'public'::regnamespace and relkind = 'r'
  union all
  select 'policy | ' || tablename || '.' || policyname || ' | '
      || format('%s for %s to %s using (%s) with check (%s)', permissive, cmd, roles, qual, with_check)
  from pg_policies where schemaname = 'public'
  union all
  select 'view | ' || viewname || ' | ' || definition from pg_views where schemaname = 'public'
  union all
  select 'publication | ' || pubname || ' | ' || schemaname || '.' || tablename from pg_publication_tables
  union all
  select 'grant | ' || table_name || ' -> ' || grantee || ' | ' || string_agg(privilege_type, ',' order by privilege_type)
  from information_schema.role_table_grants where table_schema = 'public' group by table_name, grantee
) x;
