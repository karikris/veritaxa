begin;
set local plpgsql.check_asserts = on;

-- Synthetic-only fixtures; the complete transaction is rolled back.
insert into auth.users (id, raw_user_meta_data)
select ('81000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  jsonb_build_object('identified_by', 'Synthetic progress reviewer ' || n)
from generate_series(1, 2) n;

insert into public.review_campaigns (
  id, internal_name, reviewer_name, campaign_code, target_scientific_name, status
) values ('82000000-0000-0000-0000-000000000001',
  'Synthetic progress', 'Synthetic progress', 'SYNTH-PROGRESS', 'Taxon example', 'open');

insert into public.review_batches (
  id, campaign_id, batch_code, reviewer_name, position, status
)
select ('83000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  '82000000-0000-0000-0000-000000000001', 'SYNTH-PROGRESS-' || n,
  'Synthetic progress', n,
  case when n = 4 then 'closed' else 'open' end::public.batch_status
from generate_series(1, 4) n;

insert into public.review_items (
  id, batch_id, position, image_id, source_provider, image_url, pipeline_metadata
)
select ('84000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  ('83000000-0000-0000-0000-' || lpad(b::text, 12, '0'))::uuid,
  p, 'synthetic-progress-' || n, 'synthetic',
  'https://images.example.invalid/progress.svg',
  case when b = 2 then '{"_veritaxa_rereview":{"round_code":"SYNTH"}}'::jsonb
    else '{"private":"not exposed"}'::jsonb end
from (values (1, 1, 1), (2, 1, 2), (3, 1, 3), (4, 2, 1), (5, 4, 1)) v(n, b, p);

insert into public.image_reviews (
  item_id, reviewer_id, label, submission_id, client_version, "identifiedBy"
)
select ('84000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid,
  ('81000000-0000-0000-0000-' || lpad(r::text, 12, '0'))::uuid,
  'plant', gen_random_uuid(), 'synthetic-progress', 'Synthetic progress reviewer ' || r
from (values (1, 1), (1, 2), (2, 2), (4, 2)) v(i, r);

select set_config('request.jwt.claims',
  '{"sub":"81000000-0000-0000-0000-000000000001","role":"authenticated"}', true);
-- A pooled connection's generic-plan policy must not affect counts or scope.
set local plan_cache_mode = force_generic_plan;
set local role authenticated;

do $$
declare
  first_batch uuid := '83000000-0000-0000-0000-000000000001';
  round_two uuid := '83000000-0000-0000-0000-000000000002';
  empty_batch uuid := '83000000-0000-0000-0000-000000000003';
  result record;
begin
  select * into strict result from public.list_review_batches_v2()
    where batch_id = first_batch;
  assert result.total_count = 3, 'Multiple reviewers must not inflate dataset size';
  assert result.reviewed_count = 1, 'Personal progress must remain reviewer-scoped';
  assert result.team_reviewed_count = 2, 'Count reviewed images, not review rows';
  assert result.review_round = 1 and not result.complete, 'First-round state changed';

  select * into strict result from public.list_review_batches_v2()
    where batch_id = round_two;
  assert result.review_round = 2, 'Custom campaign names must still detect round 2';
  assert result.reviewed_count = 0 and result.team_reviewed_count = 1,
    'Another reviewer must not complete personal round 2 progress';
  assert not result.complete, 'Personal completion must remain independent of shared progress';

  select * into strict result from public.list_review_batches_v2()
    where batch_id = empty_batch;
  assert result.total_count = 0 and not result.complete and result.review_round = 1,
    'Empty datasets must retain their existing completion contract';
  assert not exists (select 1 from public.list_review_batches_v2()
    where batch_id = '83000000-0000-0000-0000-000000000004'), 'Closed dataset exposed';
  assert not (to_jsonb(result) ? 'pipeline_metadata'), 'Private source metadata exposed';
  assert not has_function_privilege('anon', 'public.list_review_batches_v2()', 'execute'),
    'Anonymous database role must not list datasets';

  perform set_config('request.jwt.claims', '{}', true);
  begin
    perform public.list_review_batches_v2();
    raise exception 'Unauthenticated request accepted';
  exception when insufficient_privilege then null;
  end;
end;
$$;

select '1..1' as tap;
select 'ok 1 - dataset progress preserves counts, rounds, empty states and authorization' as tap;
rollback;
