do $test$
declare
  new_batch uuid;
  chosen_item uuid;
  counts jsonb;
begin
  select jsonb_object_agg(category,n) into counts from (
    select category,count(*) n from latest_group_members group by category
  ) grouped;
  if counts <> '{"yes_target":1,"no_target":1,"no_butterfly":3}'::jsonb then
    raise exception 'Latest review grouping or tie-break failed: %',counts;
  end if;
  if (select count(distinct (source_provider,image_id)) from latest_group_members) <> 5 then
    raise exception 'Duplicate memberships';
  end if;
  if (select count(*) from latest_group_votes) <> 7 then
    raise exception 'Historical reviews missing';
  end if;
  if exists(select 1 from latest_group_members where image_id='synthetic-latest-1'
    and (label <> 'adult_butterfly' or jsonb_array_length(source_reviews) <> 2)) then
    raise exception 'Latest answer or historical provenance missing';
  end if;
  select i.batch_id,i.id into new_batch,chosen_item from public.review_items i
    where i.pipeline_metadata->'_veritaxa_rereview'->>'round_code'='SYNTH-LATEST'
      and i.pipeline_metadata->'_veritaxa_rereview'->>'category'='yes_target';
  perform set_config('veritaxa.test_batch',new_batch::text,true);
  if (select review_round from public.list_review_batches_v2() where batch_id=new_batch) <> 2 then
    raise exception 'Round detection failed';
  end if;
  if (select reviewed_by_anyone from public.get_review_cursor_v2(new_batch,null,'resume')) then
    raise exception 'First-round review incorrectly marked second round complete';
  end if;
  -- Exercise save and retry without changing any real image or review.
  perform set_config('veritaxa.test_submission',gen_random_uuid()::text,true);
  perform public.save_image_review_v3(chosen_item,'target_not_present',null,
    current_setting('veritaxa.test_submission')::uuid,'synthetic',0);
  perform public.save_image_review_v3(chosen_item,'target_not_present',null,
    current_setting('veritaxa.test_submission')::uuid,'synthetic',0);
  if (select team_reviewed_count from public.list_review_batches_v2() where batch_id=new_batch) <> 1 then
    raise exception 'Saved/retried review incorrectly counted';
  end if;
  if not (select reviewed_by_anyone from public.get_review_cursor_v2(new_batch,null,'resume')) then
    raise exception 'Saved badge missing';
  end if;
  begin
    perform public.save_image_review_v3(chosen_item,'no_butterfly',null,gen_random_uuid(),'synthetic',0);
    raise exception 'Stale version accepted';
  exception when serialization_failure then null;
  end;
  perform set_config('request.jwt.claims','{}',true);
  begin
    perform public.list_review_batches_v2();
    raise exception 'Unauthenticated request accepted';
  exception when insufficient_privilege then null;
  end;
end;
$test$;
