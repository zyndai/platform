-- Just enough of Supabase for these migrations to apply to plain Postgres
-- (CI and local scratch databases). NEVER run this against a Supabase project.
--
-- Mirrors what Supabase provides out of the box: the three API roles, the
-- auth schema with auth.users and the JWT helper functions, the extensions
-- schema, an empty supabase_realtime publication, and the default
-- privileges that make every new public table/function reachable by the
-- API roles (RLS is what actually restricts access).

do $$
begin
  if not exists (select from pg_roles where rolname = 'anon') then
    create role anon nologin noinherit;
  end if;
  if not exists (select from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin noinherit;
  end if;
  if not exists (select from pg_roles where rolname = 'service_role') then
    create role service_role nologin noinherit bypassrls;
  end if;
end $$;

grant usage on schema public to anon, authenticated, service_role;

create schema if not exists extensions;
grant usage on schema extensions to anon, authenticated, service_role;

create schema if not exists auth;
grant usage on schema auth to anon, authenticated, service_role;

create table if not exists auth.users (
  id    uuid primary key,
  email varchar(255)
);

create or replace function auth.uid() returns uuid language sql stable as $$
  select coalesce(
    nullif(current_setting('request.jwt.claim.sub', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
  )::uuid
$$;

create or replace function auth.role() returns text language sql stable as $$
  select coalesce(
    nullif(current_setting('request.jwt.claim.role', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role')
  )::text
$$;

create or replace function auth.email() returns text language sql stable as $$
  select coalesce(
    nullif(current_setting('request.jwt.claim.email', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'email')
  )::text
$$;

create or replace function auth.jwt() returns jsonb language sql stable as $$
  select coalesce(
    nullif(current_setting('request.jwt.claim', true), ''),
    nullif(current_setting('request.jwt.claims', true), '')
  )::jsonb
$$;

-- Minimal Realtime surface for migrations that broadcast from the database.
-- Supabase owns this schema in production; this stub only exists so the
-- cards migration can create its authorization policy and test its triggers
-- against plain Postgres.
create schema if not exists realtime;
grant usage on schema realtime to anon, authenticated, service_role;

create table if not exists realtime.messages (
  id          bigint generated always as identity primary key,
  topic       text not null,
  extension   text not null default 'broadcast',
  event       text,
  payload     jsonb,
  private     boolean not null default true,
  inserted_at timestamptz not null default now()
);
alter table realtime.messages enable row level security;
grant select, insert on realtime.messages to authenticated, service_role;

create or replace function realtime.topic() returns text
language sql stable as $$
  select coalesce(nullif(current_setting('realtime.topic', true), ''), '')
$$;

create or replace function realtime.send(
  payload jsonb, event text, topic text, private boolean default true
) returns void
language sql as $$
  insert into realtime.messages(topic, extension, event, payload, private)
  values (topic, 'broadcast', event, payload, private)
$$;
grant execute on function realtime.send(jsonb, text, text, boolean) to authenticated, service_role;
grant execute on function realtime.topic() to authenticated, service_role;

do $$
begin
  if not exists (select from pg_publication where pubname = 'supabase_realtime') then
    create publication supabase_realtime;
  end if;
end $$;

alter default privileges in schema public grant all on tables    to anon, authenticated, service_role;
alter default privileges in schema public grant all on functions to anon, authenticated, service_role;
alter default privileges in schema public grant all on sequences to anon, authenticated, service_role;

-- Supabase's search_path, so unqualified extension types (vector) resolve.
do $$
begin
  execute format('alter database %I set search_path = "$user", public, extensions', current_database());
end $$;
