begin;

create extension if not exists pgtap with schema extensions;
set search_path = public, extensions;

select plan(17);

select is(
  (select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname in ('is_authorized_reviewer', 'list_review_batches',
        'get_review_cursor', 'save_image_review_v2')
      and not p.prosecdef and p.prosqlbody is not null
      and p.proconfig = array['search_path=pg_catalog']),
  4::bigint,
  'all public review entry points are bound SQL invokers with a safe search path'
);

select is(
  (select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'private'
      and p.proname in ('is_authorized_reviewer', 'list_review_batches',
        'get_review_cursor', 'save_image_review_v2')
      and p.prosecdef and p.proconfig = array['search_path=pg_catalog']),
  4::bigint,
  'privileged review implementations remain private with a safe search path'
);

select is(
  (select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.prosecdef
      and (has_function_privilege('anon', p.oid, 'execute')
        or has_function_privilege('authenticated', p.oid, 'execute'))),
  0::bigint,
  'browser roles cannot execute public SECURITY DEFINER functions'
);

select ok(not has_schema_privilege('authenticated', 'private', 'usage'),
  'authenticated reviewers still cannot resolve private-schema objects');
select ok(not has_schema_privilege('anon', 'private', 'usage'),
  'unauthenticated callers still cannot resolve private-schema objects');

select is(
  (select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname in ('public', 'private')
      and p.proname in ('is_authorized_reviewer', 'list_review_batches',
        'get_review_cursor', 'save_image_review_v2')
      and has_function_privilege('authenticated', p.oid, 'execute')
      and not has_function_privilege('anon', p.oid, 'execute')),
  8::bigint,
  'authenticated execution is limited to the bound review functions, never anon'
);

select is(
  (select count(*) from pg_policy p
    where p.polname = 'review_rpc_only' and not p.polpermissive and p.polcmd = '*'
      and pg_get_expr(p.polqual, p.polrelid) = 'false'
      and pg_get_expr(p.polwithcheck, p.polrelid) = 'false'
      and p.polroles @> array['anon'::regrole::oid, 'authenticated'::regrole::oid]
      and p.polrelid in (
        'public.review_campaigns'::regclass, 'public.review_batches'::regclass,
        'public.review_items'::regclass, 'public.image_reviews'::regclass,
        'private.reviewer_profiles'::regclass, 'private.reviewer_allowlist'::regclass)),
  6::bigint,
  'all VeriTaxa tables explicitly reject direct browser reads and writes'
);

select ok(
  not has_table_privilege('authenticated', 'public.review_items', 'select')
    and not has_table_privilege('authenticated', 'public.image_reviews', 'insert')
    and not has_table_privilege('authenticated', 'private.reviewer_profiles', 'select'),
  'no table privileges were added to make the invoker API work'
);

-- Simulate an accidental future grant and permissive policy. The restrictive
-- policy must still deny access. All temporary privileges/policies roll back.
grant select, insert on public.review_campaigns to authenticated;
create policy synthetic_permissive_campaigns on public.review_campaigns
  for all to authenticated using (true) with check (true);
insert into public.review_campaigns (id, internal_name, reviewer_name, campaign_code)
values ('f0000000-0000-0000-0000-000000000001', 'Synthetic boundary',
  'Synthetic boundary', 'SYNTH-BOUNDARY');

set local role authenticated;
select is((select count(*) from public.review_campaigns), 0::bigint,
  'restrictive policy blocks reads even with a permissive policy and SELECT grant');
select throws_ok(
  $$insert into public.review_campaigns (internal_name, reviewer_name, campaign_code)
    values ('Synthetic denied', 'Synthetic denied', 'SYNTH-DENIED')$$,
  '42501', null, 'restrictive policy blocks writes even with an INSERT grant'
);
select is(public.is_authorized_reviewer(), false,
  'the bound authorization wrapper works without private-schema USAGE');
select throws_ok($$select private.is_authorized_reviewer()$$, '42501', null,
  'direct private function lookup is still denied');
select throws_ok($$select * from public.list_review_batches()$$, '42501', null,
  'the invoker batch API preserves the missing-identity guard');
select throws_ok(
  $$select * from public.get_review_cursor(null, null, 'resume')$$,
  '42501', null, 'the invoker cursor API preserves the missing-identity guard'
);
select throws_ok(
  $$select * from public.save_image_review_v2(null, null, null, null, null, null)$$,
  '42501', null, 'the invoker save API preserves the missing-identity guard'
);

reset role;
select ok(
  to_regprocedure('public.rls_auto_enable()') is null or (
    not has_function_privilege('anon', to_regprocedure('public.rls_auto_enable()'), 'execute')
    and not has_function_privilege('authenticated', to_regprocedure('public.rls_auto_enable()'), 'execute')
  ),
  'the optional hosted RLS helper cannot be called by browser roles'
);

select is(
  (select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname in ('public', 'private')
      and p.proname in ('get_review_queue', 'submit_image_review')),
  0::bigint, 'hardening does not restore either retired RPC'
);

select * from finish();
rollback;
