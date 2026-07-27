begin;

create extension if not exists pgtap with schema extensions;
set search_path = public, extensions;

select plan(28);

insert into auth.users (
  instance_id,
  id,
  aud,
  role,
  email,
  is_anonymous,
  encrypted_password,
  email_confirmed_at,
  raw_app_meta_data,
  raw_user_meta_data,
  created_at,
  updated_at,
  confirmation_token,
  email_change,
  email_change_token_new,
  recovery_token
)
values
  (
    '00000000-0000-0000-0000-000000000000',
    '10000000-0000-0000-0000-000000000001',
    'authenticated',
    'authenticated',
    'allowed-reviewer@example.invalid',
    false,
    '',
    now(),
    '{"provider":"email","providers":["email"]}',
    '{"identified_by":"Synthetic reviewer"}',
    now(),
    now(),
    '',
    '',
    '',
    ''
  ),
  (
    '00000000-0000-0000-0000-000000000000',
    '10000000-0000-0000-0000-000000000002',
    'authenticated',
    'authenticated',
    null,
    true,
    '',
    null,
    '{"provider":"anonymous","providers":[]}',
    '{"identified_by":"Anonymous reviewer"}',
    now(),
    now(),
    '',
    '',
    '',
    ''
  );

insert into public.review_campaigns (
  id,
  internal_name,
  reviewer_name,
  campaign_code,
  target_scientific_name,
  source_provider,
  status
)
values
  (
    '20000000-0000-0000-0000-000000000001',
    'Synthetic hidden campaign',
    'Synthetic review campaign',
    'SYNTH-OPEN',
    'Taxon example',
    'synthetic',
    'open'
  ),
  (
    '20000000-0000-0000-0000-000000000002',
    'Synthetic draft campaign',
    'Draft review campaign',
    'SYNTH-DRAFT',
    null,
    'synthetic',
    'draft'
  );

insert into public.review_batches (
  id,
  campaign_id,
  batch_code,
  reviewer_name,
  position,
  status
)
values
  (
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000001',
    'SYNTH-001',
    'Batch SYNTH-001',
    1,
    'open'
  ),
  (
    '30000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000001',
    'SYNTH-002',
    'Batch SYNTH-002',
    2,
    'closed'
  ),
  (
    '30000000-0000-0000-0000-000000000003',
    '20000000-0000-0000-0000-000000000002',
    'SYNTH-003',
    'Batch SYNTH-003',
    1,
    'open'
  );

insert into public.review_items (
  id,
  batch_id,
  position,
  image_id,
  source_provider,
  display_url,
  image_url,
  flickr_search_term,
  source_labels,
  pipeline_metadata
)
values
  (
    '40000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000001',
    1,
    'synthetic-image-001',
    'synthetic',
    'https://images.example.invalid/review-001-small.jpg',
    'https://images.example.invalid/review-001.jpg',
    'synthetic Flickr keyword',
    '{"hidden":"label"}',
    '{"hidden":"model output"}'
  ),
  (
    '40000000-0000-0000-0000-000000000002',
    '30000000-0000-0000-0000-000000000001',
    2,
    'synthetic-image-002',
    'synthetic',
    null,
    'https://images.example.invalid/review-002.jpg',
    null,
    null,
    null
  ),
  (
    '40000000-0000-0000-0000-000000000003',
    '30000000-0000-0000-0000-000000000001',
    3,
    'synthetic-image-003',
    'synthetic',
    null,
    'https://images.example.invalid/review-003.jpg',
    null,
    null,
    null
  ),
  (
    '40000000-0000-0000-0000-000000000004',
    '30000000-0000-0000-0000-000000000002',
    1,
    'synthetic-image-closed',
    'synthetic',
    null,
    'https://images.example.invalid/review-closed.jpg',
    null,
    null,
    null
  );

select
  ok(
    not has_function_privilege('anon', 'public.list_review_batches()', 'execute'),
    'anonymous users cannot execute the batch-list RPC'
  );

select
  ok(
    not has_table_privilege('authenticated', 'public.review_items', 'select'),
    'authenticated users cannot select review items directly'
  );

select
  ok(
    not has_table_privilege('authenticated', 'public.image_reviews', 'insert'),
    'authenticated users cannot insert reviews directly'
  );

select
  ok(
    not has_schema_privilege('authenticated', 'private', 'usage'),
    'authenticated users cannot use the private schema'
  );

select
  ok(
    not has_table_privilege('authenticated', 'private.reviewer_profiles', 'select'),
    'authenticated users cannot read stored reviewer profiles directly'
  );

select
  results_eq(
    $$
      select user_id, email, identified_by
      from private.reviewer_profiles
      where user_id in (
        '10000000-0000-0000-0000-000000000001',
        '10000000-0000-0000-0000-000000000002'
      )
      order by user_id
    $$,
    $$
      values
        (
          '10000000-0000-0000-0000-000000000001'::uuid,
          'allowed-reviewer@example.invalid'::text,
          'Synthetic reviewer'::text
        ),
        (
          '10000000-0000-0000-0000-000000000002'::uuid,
          null::text,
          'Anonymous reviewer'::text
        )
    $$,
    'anonymous Auth users receive private profiles containing only their submitted name'
  );

select
  ok(
    position(
      'internal_name' in pg_get_function_result('public.list_review_batches()'::regprocedure)
    ) = 0,
    'batch-list result omits internal campaign context'
  );

select
  ok(
    position(
      'flickr' in pg_get_function_result(
        'public.get_review_queue(uuid,integer)'::regprocedure
      )
    ) > 0,
    'queue result exposes the current item Flickr keyword'
  );

select
  ok(
    position(
      'source_labels' in pg_get_function_result(
        'public.get_review_queue(uuid,integer)'::regprocedure
      )
    ) = 0,
    'queue result still omits other source and pipeline metadata'
  );

set local role authenticated;
select set_config(
  'request.jwt.claims',
  '{"sub":"10000000-0000-0000-0000-000000000002","role":"authenticated","is_anonymous":true}',
  true
);

select
  is(
    (
      select count(*)
      from public.list_review_batches()
      where batch_id in (
        '30000000-0000-0000-0000-000000000001',
        '30000000-0000-0000-0000-000000000002',
        '30000000-0000-0000-0000-000000000003'
      )
    ),
    1::bigint,
    'new name-only anonymous users can list open review batches immediately'
  );

reset role;

update private.reviewer_profiles
set active = false
where user_id = '10000000-0000-0000-0000-000000000002';

set local role authenticated;
select set_config(
  'request.jwt.claims',
  '{"sub":"10000000-0000-0000-0000-000000000002","role":"authenticated","is_anonymous":true}',
  true
);

select
  throws_ok(
    'select * from public.list_review_batches()',
    '42501',
    'Reviewer is not authorised',
    'an inactive reviewer profile cannot list batches'
  );

select set_config(
  'request.jwt.claims',
  '{"sub":"10000000-0000-0000-0000-000000000001","email":"allowed-reviewer@example.invalid","role":"authenticated"}',
  true
);

select
  is(
    (
      select count(*)
      from public.list_review_batches()
      where batch_id in (
        '30000000-0000-0000-0000-000000000001',
        '30000000-0000-0000-0000-000000000002',
        '30000000-0000-0000-0000-000000000003'
      )
    ),
    1::bigint,
    'active reviewers see open batches in open campaigns only'
  );

select
  is(
    (
      select count(*)
      from public.get_review_queue('30000000-0000-0000-0000-000000000001', 99)
    ),
    2::bigint,
    'review queue clamps its limit to two'
  );

select
  is(
    (
      select flickr_keyword
      from public.get_review_queue('30000000-0000-0000-0000-000000000001', 2)
      where item_id = '40000000-0000-0000-0000-000000000001'
    ),
    'synthetic Flickr keyword'::text,
    'the queue returns the retrieval keyword for its matching item only'
  );

select
  throws_ok(
    $$
      select *
      from public.submit_image_review(
        '40000000-0000-0000-0000-000000000001',
        'not_a_label'::public.review_label,
        null,
        '50000000-0000-0000-0000-000000000001',
        'test-client'
      )
    $$,
    '22P02',
    null,
    'invalid review labels are rejected'
  );

select
  lives_ok(
    $$
      select *
      from public.submit_image_review(
        '40000000-0000-0000-0000-000000000001',
        'flickr_keyword_match',
        '   ',
        '50000000-0000-0000-0000-000000000001',
        'test-client'
      )
    $$,
    'an active reviewer can submit a review'
  );

reset role;

select
  is(
    (
      select reviewer_id
      from public.image_reviews
      where submission_id = '50000000-0000-0000-0000-000000000001'
    ),
    '10000000-0000-0000-0000-000000000001'::uuid,
    'the database derives reviewer identity from the JWT'
  );

select
  is(
    (
      select comment
      from public.image_reviews
      where submission_id = '50000000-0000-0000-0000-000000000001'
    ),
    null,
    'blank comments are normalised to null'
  );

select
  is(
    (
      select "identifiedBy"
      from public.image_reviews
      where submission_id = '50000000-0000-0000-0000-000000000001'
    ),
    'Synthetic reviewer',
    'reviews snapshot the stored reviewer profile name'
  );

select
  is(
    (
      select "flickrKeyword"
      from public.image_reviews
      where submission_id = '50000000-0000-0000-0000-000000000001'
    ),
    'synthetic Flickr keyword'::text,
    'keyword-match reviews snapshot the item Flickr keyword'
  );

set local role authenticated;
select set_config(
  'request.jwt.claims',
  '{"sub":"10000000-0000-0000-0000-000000000001","email":"allowed-reviewer@example.invalid","role":"authenticated"}',
  true
);

select
  lives_ok(
    $$
      select *
      from public.submit_image_review(
        '40000000-0000-0000-0000-000000000001',
        'flickr_keyword_match',
        '',
        '50000000-0000-0000-0000-000000000001',
        'test-client'
      )
    $$,
    'an identical submission ID retry is idempotent'
  );

select
  throws_ok(
    $$
      select *
      from public.submit_image_review(
        '40000000-0000-0000-0000-000000000001',
        'moth',
        null,
        '50000000-0000-0000-0000-000000000001',
        'test-client'
      )
    $$,
    '23505',
    'Submission ID conflicts with an existing review',
    'a conflicting submission ID is rejected'
  );

select
  throws_ok(
    $$
      select *
      from public.submit_image_review(
        '40000000-0000-0000-0000-000000000001',
        'flickr_keyword_match',
        null,
        '50000000-0000-0000-0000-000000000002',
        'test-client'
      )
    $$,
    '23505',
    'Item has already been reviewed',
    'one reviewer cannot review the same item twice'
  );

select
  throws_ok(
    $$
      select *
      from public.submit_image_review(
        '40000000-0000-0000-0000-000000000002',
        'moth',
        repeat('x', 1001),
        '50000000-0000-0000-0000-000000000003',
        'test-client'
      )
    $$,
    '22001',
    'Comment exceeds 1000 characters',
    'comments over 1000 characters are rejected'
  );

select
  throws_ok(
    $$
      select *
      from public.submit_image_review(
        '40000000-0000-0000-0000-000000000002',
        'flickr_keyword_match',
        null,
        '50000000-0000-0000-0000-000000000005',
        'test-client'
      )
    $$,
    '22023',
    'Item has no Flickr keyword to select',
    'keyword-match reviews are rejected when the item has no keyword'
  );

select
  throws_ok(
    $$
      select *
      from public.submit_image_review(
        '40000000-0000-0000-0000-000000000004',
        'uncertain',
        null,
        '50000000-0000-0000-0000-000000000004',
        'test-client'
      )
    $$,
    '22023',
    'Item is not available for review',
    'closed batches reject new reviews'
  );

reset role;

select
  throws_ok(
    $$
      update public.image_reviews
      set comment = 'changed'
      where submission_id = '50000000-0000-0000-0000-000000000001'
    $$,
    '55000',
    'Image reviews are append-only',
    'stored reviews cannot be edited'
  );

select
  throws_ok(
    $$
      update private.reviewer_profiles
      set identified_by = '   '
      where user_id = '10000000-0000-0000-0000-000000000001'
    $$,
    '23514',
    null,
    'reviewer profile names cannot be blank'
  );

select * from finish();
rollback;
