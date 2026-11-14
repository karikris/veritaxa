-- Execute within an outer transaction and ROLLBACK afterwards (including on failure).
-- All fixture writes use fresh identities and a unique synthetic target.
do $test$
declare
  reviewer_a uuid := gen_random_uuid();
  reviewer_b uuid := gen_random_uuid();
  campaign uuid := gen_random_uuid();
  batch uuid := gen_random_uuid();
  excluded_batch uuid := gen_random_uuid();
  item uuid;
  tie_a uuid := gen_random_uuid();
  tie_b uuid := gen_random_uuid();
  tie_high uuid;
  test_name text := 'Synthetic latest ' || gen_random_uuid()::text;
  stamp timestamptz := clock_timestamp();
begin
  insert into auth.users(id, raw_user_meta_data) values
    (reviewer_a, '{"identified_by":"Synthetic reviewer A"}'),
    (reviewer_b, '{"identified_by":"Synthetic reviewer B"}');
  insert into public.review_campaigns(id,campaign_code,internal_name,reviewer_name,
    target_scientific_name,status) values
    (campaign,'SYNTH-'||campaign::text,'Synthetic latest','Synthetic latest',test_name,'open');
  insert into public.review_batches(id,campaign_id,batch_code,reviewer_name,position,status)
    values(batch,campaign,'SYNTH-'||batch::text,'Synthetic latest',1,'open');
  insert into public.review_items(batch_id,position,image_id,source_provider,image_url,pipeline_metadata)
    select batch,n,'synthetic-latest-'||n,'synthetic-latest',
      'https://images.example.invalid/synthetic.svg',jsonb_build_object(
        'bioclip',jsonb_build_object('top5',jsonb_build_array(jsonb_build_object(
          'scientific_name',test_name)),'attestation',jsonb_build_object('model','bioclip-synthetic')),
        'bioclip_media_byte_sha256','synthetic-hash',
        'scored_cache_image_sha256','sha256:synthetic-hash') from generate_series(1,5) n;
  insert into public.image_reviews(item_id,reviewer_id,label,submission_id,client_version,
    "identifiedBy",updated_at,"scientificName")
    select i.id,reviewer_a,case i.position when 2 then 'target_scientific_name'::public.review_label
      when 3 then 'plant'::public.review_label when 4 then 'image_unavailable'::public.review_label
      else 'target_scientific_name'::public.review_label end,
      gen_random_uuid(),'synthetic','Synthetic reviewer A',stamp,
      case when i.position in (1,2) then test_name else null end
    from public.review_items i where i.batch_id=batch and i.position<5;
  select i.id into item from public.review_items i where i.batch_id=batch and i.position=1;
  insert into public.image_reviews(item_id,reviewer_id,label,submission_id,client_version,
    "identifiedBy",updated_at) values
    (item,reviewer_b,'adult_butterfly',gen_random_uuid(),'synthetic','Synthetic reviewer B',
      stamp+interval '1 second');
  select i.id into item from public.review_items i where i.batch_id=batch and i.position=5;
  tie_high := greatest(tie_a,tie_b);
  insert into public.image_reviews(id,item_id,reviewer_id,label,submission_id,client_version,
    "identifiedBy",updated_at,"scientificName") values
    (least(tie_a,tie_b),item,reviewer_a,'target_scientific_name',gen_random_uuid(),
      'synthetic','Synthetic reviewer A',stamp,test_name),
    (tie_high,item,reviewer_b,'no_butterfly',gen_random_uuid(),
      'synthetic','Synthetic reviewer B',stamp,null);
  perform set_config('veritaxa.round_code','SYNTH-LATEST',true);
  perform set_config('veritaxa.target_name',test_name,true);
  perform set_config('veritaxa.source_campaigns',jsonb_build_array('SYNTH-'||campaign::text)::text,true);
  perform set_config('veritaxa.reviewed_after',(stamp-interval '1 day')::text,true);
  perform set_config('veritaxa.reviewed_before',(stamp+interval '1 day')::text,true);
  perform set_config('request.jwt.claims',jsonb_build_object('sub',reviewer_a,'role','authenticated')::text,true);
  perform set_config('veritaxa.test_claims',current_setting('request.jwt.claims'),true);

  if (select team_reviewed_count from public.list_review_batches_v2() where batch_id=batch) <> 5 then
    raise exception 'Shared progress double-counted multiple reviewers';
  end if;
  if not (select reviewed_by_anyone from public.get_review_cursor_v2(batch,0,'next')) then
    raise exception 'Missing reviewed image badge';
  end if;

  -- Same target is insufficient: exclude non-target BioCLIP, absent evidence,
  -- old reviews, and scores bound to different media bytes.
  insert into public.review_batches(id,campaign_id,batch_code,reviewer_name,position,status)
    values(excluded_batch,campaign,'SYNTH-'||excluded_batch::text,'Synthetic exclusions',2,'open');
  insert into public.review_items(batch_id,position,image_id,source_provider,image_url,
    pipeline_metadata,created_at)
    select excluded_batch,n,'synthetic-excluded-'||n,'synthetic-latest',
      'https://images.example.invalid/synthetic.svg',
      case when n=7 then '{}'::jsonb else jsonb_build_object(
        'bioclip',jsonb_build_object('top5',jsonb_build_array(jsonb_build_object(
          'scientific_name',case when n=6 then 'Other synthetic taxon' else test_name end)),
          'attestation',jsonb_build_object('model','bioclip-synthetic')),
        'bioclip_media_byte_sha256','synthetic-hash',
        'scored_cache_image_sha256',case when n=9 then 'sha256:different-hash'
          else 'sha256:synthetic-hash' end) end,
      case when n=8 then stamp-interval '3 days' else transaction_timestamp() end
    from generate_series(6,9) n;
  insert into public.image_reviews(item_id,reviewer_id,label,submission_id,client_version,
    "identifiedBy",created_at,updated_at)
    select i.id,reviewer_a,'plant',gen_random_uuid(),'synthetic','Synthetic reviewer A',
      case when i.position=8 then stamp-interval '2 days' else stamp end,
      case when i.position=8 then stamp-interval '2 days' else stamp end
    from public.review_items i where i.batch_id=excluded_batch;

  -- A fully attested reviewed image in an unselected campaign must also stay out.
  insert into public.review_campaigns(campaign_code,internal_name,reviewer_name,
    target_scientific_name,status) values
    ('SYNTH-OTHER-'||campaign::text,'Synthetic outside cohort','Synthetic outside cohort',test_name,'open')
    returning id into campaign;
  insert into public.review_batches(campaign_id,batch_code,reviewer_name,position,status)
    values(campaign,'SYNTH-OTHER-'||batch::text,'Synthetic outside cohort',1,'open')
    returning id into excluded_batch;
  insert into public.review_items(batch_id,position,image_id,source_provider,image_url,pipeline_metadata)
    select excluded_batch,1,'synthetic-outside-cohort','synthetic-latest',image_url,pipeline_metadata
    from public.review_items where batch_id=batch and position=1 returning id into item;
  insert into public.image_reviews(item_id,reviewer_id,label,submission_id,client_version,"identifiedBy")
    values(item,reviewer_a,'plant',gen_random_uuid(),'synthetic','Synthetic reviewer A');
end;
$test$;

-- The caller runs tools/latest_review_groups.sql here, then the assertions below.
