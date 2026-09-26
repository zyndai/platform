-- Read-only catalog of every schema our migrations own (public = persona,
-- cards, identity), as ONE text cell, so the Supabase SQL editor's row limit
-- never truncates it. Run it on prod in the SQL editor and save the cell to
-- introspection/aafo-YYYY-MM-DD.txt; `npm run db:drift` runs it on a scratch
-- DB built from the migrations and diffs the two. Names are schema-qualified.
-- First line identifies the project: developer_keys=true means xmfj.
with owned as (
  select oid, nspname from pg_namespace where nspname in ('public', 'cards', 'identity')
)
select string_agg(line, E'\n' order by line) from (
  select '0 project | developer_keys=' || (to_regclass('public.developer_keys') is not null)::text
      || ' agent_profile_cards=' || (to_regclass('cards.agent_profile_cards') is not null or to_regclass('public.agent_profile_cards') is not null)::text as line
  union all
  select 'schema | ' || nspname from owned
  union all
  select 'extension | ' || extname || ' | ' || extversion || ' | schema=' || extnamespace::regnamespace::text from pg_extension
  union all
  select 'column | ' || o.nspname || '.' || c.relname || '.' || a.attname || ' | ' || format_type(a.atttypid, a.atttypmod)
    || case when a.attgenerated = 's' then ' GENERATED ALWAYS AS (' || pg_get_expr(d.adbin, d.adrelid) || ') STORED'
            when d.adbin is not null then ' DEFAULT ' || pg_get_expr(d.adbin, d.adrelid) else '' end
    || case when a.attnotnull then ' NOT NULL' else '' end
  from pg_attribute a join pg_class c on c.oid = a.attrelid join owned o on o.oid = c.relnamespace
  left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
  where c.relkind = 'r' and a.attnum > 0 and not a.attisdropped
  union all
  select 'constraint | ' || o.nspname || '.' || c.relname || '.' || k.conname || ' | ' || pg_get_constraintdef(k.oid)
  from pg_constraint k join pg_class c on c.oid = k.conrelid join owned o on o.oid = c.relnamespace
  union all
  select 'index | ' || i.schemaname || '.' || i.indexname || ' | ' || i.indexdef
  from pg_indexes i join owned o on o.nspname = i.schemaname
  union all
  select 'trigger | ' || o.nspname || '.' || c.relname || '.' || t.tgname || ' | ' || pg_get_triggerdef(t.oid)
  from pg_trigger t join pg_class c on c.oid = t.tgrelid join owned o on o.oid = c.relnamespace
  where not t.tgisinternal
  union all
  select 'function | ' || o.nspname || '.' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')'
      || ' | acl=' || coalesce(p.proacl::text, 'default') || E'\n' || pg_get_functiondef(p.oid)
  from pg_proc p join owned o on o.oid = p.pronamespace
  where p.prokind = 'f'
    and not exists (select 1 from pg_depend d where d.objid = p.oid and d.deptype = 'e')
  union all
  select 'rls | ' || o.nspname || '.' || c.relname || ' | enabled=' || c.relrowsecurity::text || ' forced=' || c.relforcerowsecurity::text
  from pg_class c join owned o on o.oid = c.relnamespace where c.relkind = 'r'
  union all
  select 'policy | ' || p.schemaname || '.' || p.tablename || '.' || p.policyname || ' | '
      || format('%s for %s to %s using (%s) with check (%s)', p.permissive, p.cmd, p.roles, p.qual, p.with_check)
  from pg_policies p join owned o on o.nspname = p.schemaname
  union all
  select 'view | ' || v.schemaname || '.' || v.viewname || ' | ' || v.definition
  from pg_views v join owned o on o.nspname = v.schemaname
  union all
  select 'publication | ' || pubname || ' | ' || schemaname || '.' || tablename from pg_publication_tables
  union all
  select 'grant | ' || g.table_schema || '.' || g.table_name || ' -> ' || g.grantee || ' | ' || string_agg(g.privilege_type, ',' order by g.privilege_type)
  from information_schema.role_table_grants g join owned o on o.nspname = g.table_schema
  group by g.table_schema, g.table_name, g.grantee
  union all
  select 'schema-acl | ' || nspname || ' | ' || coalesce(n.nspacl::text, 'default')
  from pg_namespace n where nspname in ('cards', 'identity')
  union all
  select 'default-acl | ' || n.nspname || ' | ' || d.defaclobjtype::text || ' | ' || d.defaclacl::text
  from pg_default_acl d join pg_namespace n on n.oid = d.defaclnamespace
  where n.nspname in ('cards', 'identity')
) x;
