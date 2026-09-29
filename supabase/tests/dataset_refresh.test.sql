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
  '72000000-0000-0000-0000-000000000001', case n when 1 then 'SYNTH-A-002' when 2 then 'SYNTH-B-001' when 3 then 'SYNTH-C-001' else 'SYNTH-A-001' end,
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


insert into public.review_batches (id, campaign_id, batch_code, reviewer_name, position, status)
values
  ('73000000-0000-0000-0000-000000000005', '72000000-0000-0000-0000-000000000001', 'SYNTH-C-002', 'Synthetic C', 5, 'open'),
  ('73000000-0000-0000-0000-000000000006', '72000000-0000-0000-0000-000000000001', 'SYNTH-B-002', 'Synthetic B', 6, 'open');
insert into public.review_items (id, batch_id, position, image_id, source_provider, image_url)
values
  ('74000000-0000-0000-0000-000000000009', '73000000-0000-0000-0000-000000000005', 1, 'synthetic-e', 'synthetic', 'https://images.example.invalid/e.svg'),
  ('74000000-0000-0000-0000-000000000010', '73000000-0000-0000-0000-000000000006', 1, 'synthetic-f', 'synthetic', 'https://images.example.invalid/f.svg');
insert into public.image_reviews (item_id, reviewer_id, label, submission_id, client_version, "identifiedBy")
values ('74000000-0000-0000-0000-000000000010', '71000000-0000-0000-0000-000000000002',
  'plant', gen_random_uuid(), 'synthetic-refresh', 'Synthetic reviewer 2');

create temporary table original_items as select id, to_jsonb(item) as row_data from public.review_items item;
create temporary table original_reviews as select id, to_jsonb(review) as row_data from public.image_reviews review;

-- Exercise the actual publication transaction against reviewed, duplicate,
-- fully reviewed, unaffected, and same-ID/different-provider fixtures.
\ir ../migrations/20260929105250_refresh_review_datasets_and_order_series.sql

do $$
begin
  assert not exists (
    select 1 from public.review_items item
    join public.review_batches batch on batch.id = item.batch_id
    join private.reviewed_image_keys reviewed using (source_provider, image_id)
    where batch.status = 'open'
  ), 'no reviewed image remains in an active dataset, including cross-batch copies';
  assert (select count(*) from public.image_reviews) = (select count(*) from original_reviews),
    'all review records are retained without duplication';
  assert not exists (select 1 from original_items old left join public.review_items item using (id)
    where old.row_data is distinct from to_jsonb(item)), 'all original items and metadata remain unchanged';
  assert not exists (select 1 from original_reviews old left join public.image_reviews review using (id)
    where old.row_data is distinct from to_jsonb(review)), 'all historical answers remain unchanged';
  assert (select count(*) from public.review_batches where batch_code = 'SYNTH-B-002-remaining') = 0,
    'a fully reviewed batch does not create an empty replacement';
  assert (select count(*) from public.review_items item join public.review_batches batch on batch.id = item.batch_id
    where batch.batch_code = 'SYNTH-A-002-remaining') = 2, 'only unreviewed images are copied';
  assert (select status from public.review_batches where batch_code = 'SYNTH-A-001') = 'open',
    'matching image IDs from different providers remain available';
end;
$$;

-- Running the refresh again with no new reviews must make no additional copies.
create temporary table refreshed_counts as
select (select count(*) from public.review_batches) as batches,
       (select count(*) from public.review_items) as items;
\ir ../migrations/20260929105250_refresh_review_datasets_and_order_series.sql

do $$
begin
  assert (select count(*) from public.review_batches) = (select batches from refreshed_counts),
    'a repeat refresh does not duplicate batches';
  assert (select count(*) from public.review_items) = (select items from refreshed_counts),
    'a repeat refresh does not duplicate items';
end;
$$;

set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"71000000-0000-0000-0000-000000000001","role":"authenticated"}', true);
do $$
begin
  assert (select array_agg(batch_code) from public.list_review_batches()) =
    array['SYNTH-A-001', 'SYNTH-A-002-remaining', 'SYNTH-B-001-remaining', 'SYNTH-C-002'],
    'dataset chooser orders A, then B, then C, including replacement batches';
  assert (select array_agg(batch_code) from public.list_pending_review_batches()) =
    (select array_agg(batch_code) from public.list_review_batches()),
    'older clients receive the same ordering';
  assert not has_schema_privilege('authenticated', 'private', 'usage'),
    'reviewers cannot inspect private source data';
  assert not has_function_privilege('anon', 'public.list_review_batches()', 'execute'),
    'signed-out role cannot enumerate datasets';
end;
$$;
reset role;
select '1..1' as tap;
select 'ok 1 - refresh preserves history, removes reviewed images and orders dataset series' as tap;
rollback;
