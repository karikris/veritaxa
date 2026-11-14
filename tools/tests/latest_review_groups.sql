-- Execute within an outer transaction and ROLLBACK afterwards (including on failure).
-- All fixture writes use fresh identities and a unique synthetic target.
do $test$
declare
  reviewer_a uuid := gen_random_uuid();
  reviewer_b uuid := gen_random_uuid();
  campaign uuid := gen_random_uuid();
  batch uuid := gen_random_uuid();
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
  insert into public.review_items(batch_id,position,image_id,source_provider,image_url)
    select batch,n,'synthetic-latest-'||n,'synthetic-latest',
      'https://images.example.invalid/synthetic.svg' from generate_series(1,5) n;
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
  perform set_config('request.jwt.claims',jsonb_build_object('sub',reviewer_a,'role','authenticated')::text,true);
  perform set_config('veritaxa.test_claims',current_setting('request.jwt.claims'),true);

  if (select team_reviewed_count from public.list_review_batches_v2() where batch_id=batch) <> 5 then
    raise exception 'Shared progress double-counted multiple reviewers';
  end if;
  if not (select reviewed_by_anyone from public.get_review_cursor_v2(batch,0,'next')) then
    raise exception 'Missing reviewed image badge';
  end if;
end;
$test$;

-- The caller runs tools/latest_review_groups.sql here, then the assertions below.
