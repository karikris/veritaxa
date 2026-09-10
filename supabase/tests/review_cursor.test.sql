begin;

create extension if not exists pgtap with schema extensions;
set search_path = public, extensions;
select plan(48);

select is(
  (select array_agg(attribute.attname::text order by key.ordinality)
   from pg_constraint as constraint_definition
   cross join unnest(constraint_definition.conkey) with ordinality as key(attnum, ordinality)
   join pg_attribute as attribute on attribute.attnum = key.attnum
     and attribute.attrelid = constraint_definition.conrelid
   where constraint_definition.conrelid = 'public.review_items'::regclass
     and constraint_definition.conname = 'review_items_batch_position_key'
     and constraint_definition.contype = 'u' and not constraint_definition.condeferrable),
  array['batch_id', 'position']::text[],
  'immediate unique batch/position constraint makes an ID tie-breaker unnecessary'
);

-- Entirely synthetic, rolled back, and exercised as the real browser role.
insert into auth.users (id, email, raw_user_meta_data)
select
  ('61000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  'cursor-' || n || '@example.invalid',
  jsonb_build_object('identified_by', 'Synthetic cursor reviewer ' || n)
from generate_series(1, 2) as n;

insert into public.review_campaigns (
  id, internal_name, reviewer_name, campaign_code, target_scientific_name, status
)
select
  ('62000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  'Synthetic cursor campaign ' || n, 'Synthetic cursor campaign',
  'SYNTH-CURSOR-' || n, 'Taxon example',
  case n when 1 then 'open' else 'draft' end::public.campaign_status
from generate_series(1, 2) as n;

insert into public.review_batches (
  id, campaign_id, batch_code, reviewer_name, position, status
)
select
  ('63000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  case n when 5 then '62000000-0000-0000-0000-000000000002'
    else '62000000-0000-0000-0000-000000000001' end::uuid,
  'SYNTH-CURSOR-BATCH-' || n, 'Synthetic cursor batch', n,
  case n when 4 then 'closed' else 'open' end::public.batch_status
from generate_series(1, 5) as n;

insert into public.review_items (
  id, batch_id, position, image_id, source_provider, display_url, image_url,
  source_labels, pipeline_metadata
)
select
  ('64000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  case n when 7 then '63000000-0000-0000-0000-000000000003'
    else '63000000-0000-0000-0000-000000000001' end::uuid,
  n, 'synthetic-cursor-' || n, 'synthetic',
  case n when 2 then 'https://images.example.invalid/preview.png' else null end,
  'https://images.example.invalid/source.png',
  '{"private":"synthetic label"}', '{"private":"synthetic metadata"}'
from unnest(array[2, 5, 7, 9]) as n;

-- Preserve legacy interpretation and count only the caller's own current rows.
insert into public.image_reviews (
  item_id, reviewer_id, label, comment, submission_id, client_version,
  "identifiedBy", "flickrKeyword", version
)
select
  ('64000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  ('61000000-0000-0000-0000-' || lpad(reviewer::text, 12, '0'))::uuid,
  case when reviewer = 2 then 'bird' when n = 2 then 'flickr_keyword_match'
    else 'plant' end::public.review_label,
  case when reviewer = 1 and n = 2 then 'Synthetic comment 🦋' else null end,
  gen_random_uuid(), 'synthetic-cursor-test', 'Synthetic cursor reviewer',
  case when reviewer = 1 and n = 2 then 'synthetic legacy keyword' else null end,
  case when reviewer = 2 then 1 when n = 2 then 3 else 2 end
from unnest(array[2, 5, 9]) as n
cross join generate_series(1, 2) as reviewer
where reviewer = 2 or n <> 5;

select ok(
  (select prosecdef and proconfig = array['search_path=pg_catalog']
   from pg_proc where oid = 'public.get_review_cursor(uuid,integer,text)'::regprocedure)
  and has_function_privilege('authenticated', 'public.get_review_cursor(uuid,integer,text)', 'execute')
  and not has_function_privilege('anon', 'public.get_review_cursor(uuid,integer,text)', 'execute'),
  'cursor keeps its fixed search path and restricted definer grant'
);

set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"61000000-0000-0000-0000-000000000001","role":"authenticated"}', true);

-- Nonexistent anchors are positions, not item identities; strict inequalities
-- must handle gaps and both integer extremes without arithmetic overflow.
select is(
  (select "position" from public.get_review_cursor(
    '63000000-0000-0000-0000-000000000001', anchor, direction)),
  case direction when 'next' then expected_next else expected_previous end,
  direction || ' at anchor ' || anchor
)
from (values
  (-2147483648, 2, 9), (1, 2, 9), (2, 5, 9), (3, 5, 2), (5, 9, 2),
  (7, 9, 5), (9, 2, 5), (10, 2, 9), (2147483647, 2, 9)
) as cases(anchor, expected_next, expected_previous)
cross join (values ('next'), ('previous')) as directions(direction);

select is(
  (select count(*) from public.get_review_cursor(
    '63000000-0000-0000-0000-000000000002', 1, direction)),
  0::bigint, 'empty batch returns no row for ' || direction
)
from (values ('resume'), ('next'), ('previous')) as directions(direction);

select results_eq(
  format('select "position", reviewed_count, total_count, complete from public.get_review_cursor(%L, %L, %L)',
    '63000000-0000-0000-0000-000000000003', anchor, direction),
  $$values (7, 0::bigint, 1::bigint, false)$$,
  'single-item batch stays on its only item for ' || direction || coalesce(anchor::text, '')
)
from (values
  (null::integer, 'resume'), (-2147483648, 'next'), (7, 'next'), (2147483647, 'next'),
  (-2147483648, 'previous'), (7, 'previous'), (2147483647, 'previous')
) as cases(anchor, direction);

select is(
  (select "position" from public.get_review_cursor(
    '63000000-0000-0000-0000-000000000001', anchor, '  ReSuMe  ')),
  5, 'resume normalizes direction, ignores anchor, and chooses first own-unreviewed item'
)
from (values (null::integer), (2147483647)) as cases(anchor);

select results_eq(
  $$select * from public.get_review_cursor('63000000-0000-0000-0000-000000000001', 1, 'next')$$,
  $$values ('64000000-0000-0000-0000-000000000002'::uuid,
    'synthetic-cursor-2'::text, 'Taxon example'::text,
    'https://images.example.invalid/preview.png'::text,
    'https://images.example.invalid/source.png'::text, 2,
    null::public.review_label, 'Synthetic comment 🦋'::text, 3, 2::bigint, 3::bigint, false)$$,
  'exact legacy response retains comment/version/progress but omits label and all hidden fields'
);

select results_eq(
  $$select * from public.get_review_cursor('63000000-0000-0000-0000-000000000001', 2, 'next')$$,
  $$values ('64000000-0000-0000-0000-000000000005'::uuid,
    'synthetic-cursor-5'::text, 'Taxon example'::text, null::text,
    'https://images.example.invalid/source.png'::text, 5,
    null::public.review_label, null::text, 0, 2::bigint, 3::bigint, false)$$,
  'exact unreviewed response has null answer, version zero, own progress, and no hidden fields'
);

select throws_ok(
  format('select * from public.get_review_cursor(%L, 1, %L)',
    '63000000-0000-0000-0000-000000000001', direction),
  '22023', 'Review cursor direction is invalid', 'invalid direction is rejected'
)
from (values (null::text), (''), ('later')) as cases(direction);

select throws_ok(
  format('select * from public.get_review_cursor(%L, null, %L)',
    '63000000-0000-0000-0000-000000000001', direction),
  '22023', 'Review cursor anchor is required', direction || ' requires an anchor'
)
from (values ('next'), ('previous')) as cases(direction);

select throws_ok(
  format('select * from public.get_review_cursor(%L, null, %L)', batch, 'resume'),
  '22023', 'Batch is not available for review', 'unavailable batch is rejected'
)
from (values
  (null::uuid), ('63000000-0000-0000-0000-000000000099'::uuid),
  ('63000000-0000-0000-0000-000000000004'::uuid),
  ('63000000-0000-0000-0000-000000000005'::uuid)
) as cases(batch);

select set_config('request.jwt.claims',
  '{"sub":"61000000-0000-0000-0000-000000000002","role":"authenticated"}', true);

select results_eq(
  format('select "position", current_label::text, current_version, reviewed_count, total_count, complete
    from public.get_review_cursor(%L, %L, %L)',
    '63000000-0000-0000-0000-000000000001', anchor, direction),
  format('values (%s, %L::text, 1, 3::bigint, 3::bigint, true)', expected, 'bird'),
  'completed second reviewer keeps own answer/progress for ' || direction
)
from (values (null::integer, 'resume', 2), (9, 'next', 2), (2, 'previous', 9))
  as cases(anchor, direction, expected);

select set_config('request.jwt.claims', '{}', true);
select throws_ok(
  $$select * from public.get_review_cursor(null, null, 'invalid')$$,
  '42501', 'Reviewer is not authorised', 'missing identity is rejected before input validation'
);

reset role;
update private.reviewer_profiles set active = false
where user_id = '61000000-0000-0000-0000-000000000002';
set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"61000000-0000-0000-0000-000000000002","role":"authenticated"}', true);
select throws_ok(
  $$select * from public.get_review_cursor('63000000-0000-0000-0000-000000000001', 9, 'next')$$,
  '42501', 'Reviewer is not authorised', 'disabled reviewer cannot use the wrap path'
);

reset role;
select * from finish();
rollback;
