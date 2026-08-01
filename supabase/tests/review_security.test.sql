begin;

create extension if not exists pgtap with schema extensions;
set search_path = public, extensions;

select plan(54);

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
    5,
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
  throws_ok(
    $$
      update public.review_campaigns
      set status = 'open'
      where id = '20000000-0000-0000-0000-000000000002'
    $$,
    '23514',
    null,
    'a campaign cannot be opened without a target scientific name'
  );

select
  ok(
    not has_function_privilege('anon', 'public.list_review_batches()', 'execute'),
    'anonymous users cannot execute the batch-list RPC'
  );

select
  ok(
    not has_function_privilege(
      'anon',
      'public.get_review_cursor(uuid,integer,text)',
      'execute'
    ),
    'anonymous users cannot execute the review-cursor RPC'
  );

select
  ok(
    not has_function_privilege(
      'anon',
      'public.save_image_review_v2(uuid,public.review_label,text,uuid,text,integer)',
      'execute'
    ),
    'anonymous users cannot execute the editable-review RPC'
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
      'target_scientific_name' in pg_get_function_result(
        'public.get_review_queue(uuid,integer)'::regprocedure
      )
    ) > 0,
    'queue result exposes the campaign target scientific name'
  );

select
  ok(
    position(
      'source_labels' in pg_get_function_result(
        'public.get_review_queue(uuid,integer)'::regprocedure
      )
    ) = 0
    and position(
      'flickr' in pg_get_function_result(
        'public.get_review_queue(uuid,integer)'::regprocedure
      )
    ) = 0,
    'queue result omits Flickr and other source or pipeline metadata'
  );

select
  ok(
    position(
      'source_labels' in pg_get_function_result(
        'public.get_review_cursor(uuid,integer,text)'::regprocedure
      )
    ) = 0
    and position(
      'pipeline_metadata' in pg_get_function_result(
        'public.get_review_cursor(uuid,integer,text)'::regprocedure
      )
    ) = 0
    and position(
      'source_page' in pg_get_function_result(
        'public.get_review_cursor(uuid,integer,text)'::regprocedure
      )
    ) = 0
    and position(
      'flickr' in pg_get_function_result(
        'public.get_review_cursor(uuid,integer,text)'::regprocedure
      )
    ) = 0
    and position(
      'source_labels' in pg_get_function_result(
        'public.save_image_review_v2(uuid,public.review_label,text,uuid,text,integer)'::regprocedure
      )
    ) = 0
    and position(
      'pipeline_metadata' in pg_get_function_result(
        'public.save_image_review_v2(uuid,public.review_label,text,uuid,text,integer)'::regprocedure
      )
    ) = 0
    and position(
      'source_page' in pg_get_function_result(
        'public.save_image_review_v2(uuid,public.review_label,text,uuid,text,integer)'::regprocedure
      )
    ) = 0
    and position(
      'flickr' in pg_get_function_result(
        'public.save_image_review_v2(uuid,public.review_label,text,uuid,text,integer)'::regprocedure
      )
    ) = 0,
    'new RPC responses omit source labels, pipeline metadata, source pages, and Flickr context'
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

select
  throws_ok(
    $$
      select *
      from public.get_review_cursor(
        '30000000-0000-0000-0000-000000000001',
        null,
        'resume'
      )
    $$,
    '42501',
    'Reviewer is not authorised',
    'an inactive reviewer profile cannot access the review cursor'
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
      select item_id
      from public.get_review_cursor(
        '30000000-0000-0000-0000-000000000001',
        null,
        'resume'
      )
    ),
    '40000000-0000-0000-0000-000000000001'::uuid,
    'resume starts at the first unreviewed image'
  );

select
  is(
    (
      select item_id
      from public.get_review_cursor(
        '30000000-0000-0000-0000-000000000001',
        1,
        'next'
      )
    ),
    '40000000-0000-0000-0000-000000000002'::uuid,
    'next advances by batch position'
  );

select
  is(
    (
      select item_id
      from public.get_review_cursor(
        '30000000-0000-0000-0000-000000000001',
        1,
        'previous'
      )
    ),
    '40000000-0000-0000-0000-000000000003'::uuid,
    'previous wraps from the first image to the last image'
  );

select
  is(
    (
      select item_id
      from public.get_review_cursor(
        '30000000-0000-0000-0000-000000000001',
        3,
        'next'
      )
    ),
    '40000000-0000-0000-0000-000000000003'::uuid,
    'next crosses a gap in batch positions'
  );

select
  is(
    (
      select item_id
      from public.get_review_cursor(
        '30000000-0000-0000-0000-000000000001',
        4,
        'previous'
      )
    ),
    '40000000-0000-0000-0000-000000000002'::uuid,
    'previous crosses a gap in batch positions'
  );

select
  throws_ok(
    $$
      select *
      from public.get_review_cursor(
        '30000000-0000-0000-0000-000000000002',
        null,
        'resume'
      )
    $$,
    '22023',
    'Batch is not available for review',
    'closed batches reject cursor access'
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
      select target_scientific_name
      from public.get_review_queue('30000000-0000-0000-0000-000000000001', 2)
      where item_id = '40000000-0000-0000-0000-000000000001'
    ),
    'Taxon example'::text,
    'the queue returns the campaign target scientific name'
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
        'target_scientific_name',
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
      select "scientificName"
      from public.image_reviews
      where submission_id = '50000000-0000-0000-0000-000000000001'
    ),
    'Taxon example'::text,
    'target reviews snapshot the campaign scientific name'
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
        'target_scientific_name',
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
        'target_scientific_name',
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
    'Flickr keyword classification is no longer supported',
    'legacy Flickr keyword classifications are rejected'
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

select
  results_eq(
    $$
      select item_id, current_version, reviewed_count, total_count, complete
      from public.save_image_review_v2(
        '40000000-0000-0000-0000-000000000002',
        'moth',
        'first answer',
        '50000000-0000-0000-0000-000000000006',
        'test-client-v2',
        0
      )
    $$,
    $$
      values (
        '40000000-0000-0000-0000-000000000003'::uuid,
        0,
        2::bigint,
        3::bigint,
        false
      )
    $$,
    'a first v2 save inserts once and atomically returns the next image'
  );

reset role;

select
  results_eq(
    $$
      select label::text, comment, version
      from public.image_reviews
      where item_id = '40000000-0000-0000-0000-000000000002'
        and reviewer_id = '10000000-0000-0000-0000-000000000001'
    $$,
    $$
      values ('moth'::text, 'first answer'::text, 1)
    $$,
    'a first v2 answer is stored at version one'
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
      from public.save_image_review_v2(
        '40000000-0000-0000-0000-000000000002',
        'moth',
        'first answer',
        '50000000-0000-0000-0000-000000000006',
        'test-client-v2',
        0
      )
    $$,
    'an identical v2 submission retry is idempotent'
  );

select
  is(
    (
      select current_version
      from public.get_review_cursor(
        '30000000-0000-0000-0000-000000000001',
        5,
        'previous'
      )
    ),
    1,
    'an idempotent retry does not increment the answer version'
  );

select
  results_eq(
    $$
      select item_id, reviewed_count, total_count, complete
      from public.save_image_review_v2(
        '40000000-0000-0000-0000-000000000002',
        'adult_butterfly',
        'corrected answer',
        '50000000-0000-0000-0000-000000000007',
        'test-client-v2',
        1
      )
    $$,
    $$
      values (
        '40000000-0000-0000-0000-000000000003'::uuid,
        2::bigint,
        3::bigint,
        false
      )
    $$,
    'editing an answer advances without increasing reviewed progress'
  );

reset role;

select
  results_eq(
    $$
      select label::text, comment, version, count(*) over ()
      from public.image_reviews
      where item_id = '40000000-0000-0000-0000-000000000002'
        and reviewer_id = '10000000-0000-0000-0000-000000000001'
    $$,
    $$
      values ('adult_butterfly'::text, 'corrected answer'::text, 2, 1::bigint)
    $$,
    'editing replaces the reviewer answer in the same row and increments its version'
  );

set local role authenticated;
select set_config(
  'request.jwt.claims',
  '{"sub":"10000000-0000-0000-0000-000000000001","email":"allowed-reviewer@example.invalid","role":"authenticated"}',
  true
);

select
  throws_ok(
    $$
      select *
      from public.save_image_review_v2(
        '40000000-0000-0000-0000-000000000002',
        'plant',
        null,
        '50000000-0000-0000-0000-000000000008',
        'test-client-v2',
        1
      )
    $$,
    '40001',
    'Review version is stale',
    'a stale correction is rejected'
  );

select
  throws_ok(
    $$
      select *
      from public.save_image_review_v2(
        '40000000-0000-0000-0000-000000000004',
        'uncertain',
        null,
        '50000000-0000-0000-0000-000000000009',
        'test-client-v2',
        0
      )
    $$,
    '22023',
    'Item is not available for review',
    'closed batches reject v2 saves'
  );

select
  throws_ok(
    $$
      update public.image_reviews
      set comment = 'direct browser update'
      where item_id = '40000000-0000-0000-0000-000000000002'
    $$,
    '42501',
    'permission denied for table image_reviews',
    'reviewers cannot update review rows directly'
  );

select
  throws_ok(
    $$
      delete from public.image_reviews
      where item_id = '40000000-0000-0000-0000-000000000002'
    $$,
    '42501',
    'permission denied for table image_reviews',
    'reviewers cannot delete review rows directly'
  );

reset role;

update private.reviewer_profiles
set active = true
where user_id = '10000000-0000-0000-0000-000000000002';

set local role authenticated;
select set_config(
  'request.jwt.claims',
  '{"sub":"10000000-0000-0000-0000-000000000002","role":"authenticated","is_anonymous":true}',
  true
);

select
  lives_ok(
    $$
      select *
      from public.save_image_review_v2(
        '40000000-0000-0000-0000-000000000002',
        'plant',
        null,
        '50000000-0000-0000-0000-000000000010',
        'test-client-v2',
        0
      )
    $$,
    'a different reviewer can save an independent answer for the same image'
  );

reset role;

select
  is(
    (
      select count(*)
      from public.image_reviews
      where item_id = '40000000-0000-0000-0000-000000000002'
    ),
    2::bigint,
    'different reviewers retain separate current answers'
  );

set local role authenticated;
select set_config(
  'request.jwt.claims',
  '{"sub":"10000000-0000-0000-0000-000000000001","email":"allowed-reviewer@example.invalid","role":"authenticated"}',
  true
);

select
  results_eq(
    $$
      select item_id, current_label::text, current_version, reviewed_count, complete
      from public.save_image_review_v2(
        '40000000-0000-0000-0000-000000000003',
        'bird',
        null,
        '50000000-0000-0000-0000-000000000011',
        'test-client-v2',
        0
      )
    $$,
    $$
      values (
        '40000000-0000-0000-0000-000000000001'::uuid,
        'target_scientific_name'::text,
        1,
        3::bigint,
        true
      )
    $$,
    'the final save remains navigable and wraps to the first reviewed image'
  );

select
  is(
    (
      select item_id
      from public.get_review_cursor(
        '30000000-0000-0000-0000-000000000001',
        null,
        'resume'
      )
    ),
    '40000000-0000-0000-0000-000000000001'::uuid,
    'resume returns the first image when the reviewer has completed the batch'
  );

reset role;

select
  throws_ok(
    $$
      update public.image_reviews
      set item_id = '40000000-0000-0000-0000-000000000003',
        version = version + 1,
        updated_at = updated_at + interval '1 second'
      where submission_id = '50000000-0000-0000-0000-000000000001'
    $$,
    '55000',
    'Image review identity cannot be changed',
    'review identity cannot be changed'
  );

select
  throws_ok(
    $$
      delete from public.image_reviews
      where submission_id = '50000000-0000-0000-0000-000000000001'
    $$,
    '55000',
    'Image reviews cannot be deleted',
    'review rows cannot be deleted even by a privileged table writer'
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
