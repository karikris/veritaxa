-- Minimal SQL-only Auth fixture for a dedicated, disposable local database.
-- Not the Supabase Auth service and never a production migration.
do $$
begin
  if current_database() <> 'veritaxa_cursor_synthetic'
    or (inet_server_addr() is not null and not (
      inet_server_addr() <<= '127.0.0.0/8'::inet or inet_server_addr() = '::1'::inet
    ))
  then
    raise exception 'Cursor fixtures require the dedicated local synthetic database';
  end if;
  if exists (select 1 from pg_namespace where nspname = 'auth')
    or to_regclass('public.review_items') is not null
  then
    raise exception 'Cursor fixtures require an empty database';
  end if;
  -- Create missing test roles only. Never alter existing role privileges.
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin bypassrls;
  end if;
end;
$$;

create schema auth;
create schema extensions;
grant usage on schema auth, extensions, public to anon, authenticated, service_role;
create table auth.users (
  instance_id uuid, id uuid primary key, aud text, role text, email text,
  is_anonymous boolean default false, encrypted_password text,
  email_confirmed_at timestamptz, raw_app_meta_data jsonb default '{}'::jsonb,
  raw_user_meta_data jsonb default '{}'::jsonb, created_at timestamptz,
  updated_at timestamptz, confirmation_token text, email_change text,
  email_change_token_new text, recovery_token text
);
revoke all on auth.users from public, anon, authenticated;
create function auth.uid() returns uuid language sql stable
set search_path = pg_catalog as $$
  select coalesce(nullif(current_setting('request.jwt.claim.sub', true), ''),
    nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')::uuid;
$$;
create function auth.jwt() returns jsonb language sql stable
set search_path = pg_catalog as $$
  select coalesce(nullif(current_setting('request.jwt.claim', true), ''),
    nullif(current_setting('request.jwt.claims', true), ''))::jsonb;
$$;
create extension pgtap with schema extensions;
