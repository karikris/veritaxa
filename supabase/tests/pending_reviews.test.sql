begin;
set local plpgsql.check_asserts = on;

-- Synthetic fixtures only. Every write, including auth profiles, is rolled back.
insert into auth.users (id, email, raw_user_meta_data)
select ('71000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  'pending-' || n || '@example.invalid',
  jsonb_build_object('identified_by', 'Synthetic pending reviewer ' || n)
from generate_series(1, 2) n;

insert into public.review_campaigns (
  id, internal_name, reviewer_name, campaign_code, target_scientific_name, status
) values ('72000000-0000-0000-0000-000000000001', 'Synthetic pending',
  'Synthetic pending', 'SYNTH-PENDING', 'Taxon example', 'open');

insert into public.review_batches (id, campaign_id, batch_code, reviewer_name, position, status)
select ('73000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  '72000000-0000-0000-0000-000000000001', 'SYNTH-PENDING-' || n,
  'Synthetic pending batch', n, case when n = 3 then 'closed' else 'open' end::public.batch_status
from generate_series(1, 4) n;

insert into public.review_items (id, batch_id, position, image_id, source_provider, image_url)
select ('74000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  ('73000000-0000-0000-0000-' || lpad(batch::text, 12, '0'))::uuid,
  position, image, provider, 'https://images.example.invalid/pending.svg'
from (values
  (1, 1, 1, 'synthetic-a', 'synthetic'),
  (2, 1, 3, 'synthetic-b', 'synthetic'),
  (3, 1, 7, 'synthetic-c', 'synthetic'),
  (4, 2, 1, 'synthetic-a', 'synthetic'),
  (5, 3, 1, 'synthetic-d', 'synthetic'),
  (6, 1, 9, 'synthetic-d', 'synthetic'),
  (7, 4, 1, 'synthetic-a', 'synthetic-other'),
  (8, 2, 2, 'synthetic-c', 'synthetic')
) fixtures(n, batch, position, image, provider);

insert into public.image_reviews (item_id, reviewer_id, label, submission_id, client_version, "identifiedBy")
select ('74000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  '71000000-0000-0000-0000-000000000002', 'image_unavailable', gen_random_uuid(),
  'synthetic-pending-test', 'Synthetic pending reviewer 2'
from unnest(array[1, 5]) n;

set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"71000000-0000-0000-0000-000000000001","role":"authenticated"}', true);

do $$
declare
  batch uuid := '73000000-0000-0000-0000-000000000001';
  next_item record;
begin
  assert (select count(*) from public.list_pending_review_batches()
    where batch_id::text like '73000000-%') = 3, 'only nonempty open batches appear';
  assert (select reviewed_count from public.list_pending_review_batches() where batch_id = batch) = 2,
    'global progress includes unavailable images and reviews in closed batches';
  select * into next_item from public.get_pending_review_cursor(batch, null, 'resume');
  assert next_item.position = 3 and next_item.current_label is null and next_item.current_version = 0,
    'resume skips all previously reviewed images';
  assert next_item.reviewed_count = 2 and next_item.total_count = 4, 'progress counts items once';
  assert (select position from public.get_pending_review_cursor(batch, 3, 'next')) = 7,
    'next skips reviewed images';
  assert (select position from public.get_pending_review_cursor(batch, 7, 'next')) = 3,
    'next wraps only through pending images';
  assert (select position from public.get_pending_review_cursor(batch, 3, 'previous')) = 7,
    'previous wraps only through pending images';
  assert (select position from public.get_pending_review_cursor(batch, 7, 'previous')) = 3,
    'previous skips reviewed images';
  assert (select count(*) from public.get_pending_review_cursor(
    '73000000-0000-0000-0000-000000000004', null, 'resume')) = 1,
    'identical image IDs from different providers stay distinct';
  begin
    perform public.get_pending_review_cursor('73000000-0000-0000-0000-000000000003', null, 'resume');
    raise exception 'closed batch should be rejected';
  exception when sqlstate '22023' then null; end;
  begin
    perform public.get_pending_review_cursor(batch, null, 'next');
    raise exception 'missing anchor should be rejected';
  exception when sqlstate '22023' then null; end;
  select * into next_item from public.save_pending_image_review(
    '74000000-0000-0000-0000-000000000002', 'plant', null,
    '75000000-0000-0000-0000-000000000001', 'synthetic-pending-test', 0);
  assert next_item.position = 7 and next_item.reviewed_count = 3, 'save returns next pending image';
  assert (select count(*) from public.save_pending_image_review(
    '74000000-0000-0000-0000-000000000003', 'plant', null,
    '75000000-0000-0000-0000-000000000002', 'synthetic-pending-test', 0)) = 0,
    'last save succeeds with an empty cursor';
  assert (select count(*) from public.save_pending_image_review(
    '74000000-0000-0000-0000-000000000003', 'plant', null,
    '75000000-0000-0000-0000-000000000002', 'synthetic-pending-test', 0)) = 0,
    'last save retry remains idempotent';
  assert (select count(*) from public.list_pending_review_batches()
    where batch_id::text like '73000000-%') = 1,
    'completed batch and duplicate-only batch disappear';
  assert (select count(*) from public.get_pending_review_cursor(batch, null, 'resume')) = 0,
    'a completed batch never falls back to reviewed images';
  assert not has_table_privilege('authenticated',
    (select c.oid from pg_class c join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'private' and c.relname = 'reviewed_image_keys'), 'select'),
    'private source identities remain inaccessible';
  assert not has_function_privilege('anon', 'public.list_pending_review_batches()', 'execute'),
    'anonymous database role cannot list batches';
  assert not has_function_privilege('anon', 'public.get_pending_review_cursor(uuid,integer,text)', 'execute'),
    'anonymous database role cannot browse images';
  assert not has_function_privilege('anon',
    'public.save_pending_image_review(uuid,public.review_label,text,uuid,text,integer)', 'execute'),
    'anonymous database role cannot submit reviews';
end;
$$;

select set_config('request.jwt.claims',
  '{"sub":"71000000-0000-0000-0000-000000000002","role":"authenticated"}', true);
do $$
begin
  begin
    perform public.save_pending_image_review(
      '74000000-0000-0000-0000-000000000002', 'bird', null,
      '75000000-0000-0000-0000-000000000003', 'synthetic-pending-test', 0);
    raise exception 'a second reviewer must not create another review';
  exception when sqlstate 'PT409' then null; end;
  begin
    perform public.save_pending_image_review(
      '74000000-0000-0000-0000-000000000008', 'bird', null,
      '75000000-0000-0000-0000-000000000004', 'synthetic-pending-test', 0);
    raise exception 'a duplicate in another batch must not be reviewed again';
  exception when sqlstate 'PT409' then null; end;
end;
$$;

select set_config('request.jwt.claims', '{}', true);
do $$
begin
  begin
    perform public.list_pending_review_batches();
    raise exception 'missing identity must not list batches';
  exception when sqlstate '42501' then null; end;
end;
$$;

reset role;
do $$
begin
  assert (select count(*) from public.image_reviews
    where item_id::text like '74000000-%') = 4, 'existing reviews remain and retries add no duplicates';
end;
$$;

-- Emit TAP so this assertion-based test also runs under supabase test db.
select '1..1' as tap;
select 'ok 1 - global pending review queues, completion, retries and access checks' as tap;
rollback;
