begin;
set local plpgsql.check_asserts=on;
do $test$
declare
 reviewer uuid:=gen_random_uuid();campaign uuid:=gen_random_uuid();batch uuid:=gen_random_uuid();old_batch uuid:=gen_random_uuid();
 old_item uuid:=gen_random_uuid();copy_item uuid:=gen_random_uuid();fresh_item uuid:=gen_random_uuid();other_provider uuid:=gen_random_uuid();
 self_item uuid:=gen_random_uuid();legacy_old uuid:=gen_random_uuid();legacy_copy uuid:=gen_random_uuid();row_data record;
begin
 insert into auth.users(id,raw_user_meta_data)values(reviewer,'{"identified_by":"Synthetic history reviewer"}');
 insert into public.review_campaigns(id,campaign_code,internal_name,reviewer_name,target_scientific_name,status)
 values(campaign,'SYNTH-HISTORY-'||campaign::text,'Synthetic history','Synthetic history','Taxon example','open');
 insert into public.review_batches(id,campaign_id,batch_code,reviewer_name,position,status)values
 (batch,campaign,'SYNTH-HISTORY-'||batch::text,'Synthetic current',1,'open'),
 (old_batch,campaign,'SYNTH-HISTORY-'||old_batch::text,'Synthetic archived',2,'closed');
 insert into public.review_items(id,batch_id,position,image_id,source_provider,source_record_id,image_url,pipeline_metadata)values
 (old_item,old_batch,1,'old-import-id','synthetic','shared-photo','https://images.example.invalid/history.svg','{}'),
 (copy_item,batch,1,'new-import-id','synthetic','shared-photo','https://images.example.invalid/history.svg','{"_veritaxa_rereview":{"round_code":"SYNTH","category":"yes_target"}}'),
 (fresh_item,batch,2,'fresh-photo','synthetic','fresh-photo','https://images.example.invalid/fresh.svg','{}'),
 (other_provider,batch,3,'same-id-another-provider','other-provider','shared-photo','https://images.example.invalid/other.svg','{}'),
 (self_item,batch,4,'self-only','synthetic','self-only','https://images.example.invalid/self.svg','{}'),
 (legacy_old,old_batch,2,'legacy-fallback','synthetic',null,'https://images.example.invalid/legacy.svg','{}'),
 (legacy_copy,batch,5,'legacy-fallback','synthetic',null,'https://images.example.invalid/legacy.svg','{}');
 insert into public.image_reviews(item_id,reviewer_id,label,submission_id,client_version,"identifiedBy")
 select id,reviewer,'plant',gen_random_uuid(),'synthetic','Synthetic history reviewer'
 from public.review_items where id in(old_item,self_item,legacy_old);
 perform set_config('request.jwt.claims',jsonb_build_object('sub',reviewer,'role','authenticated')::text,true);
 select *into strict row_data from public.get_review_cursor_v4(batch,0,'next');
 assert row_data.item_id=copy_item and row_data.previously_reviewed,'Historical source identity was missed';
 assert row_data.current_version=0 and not row_data.reviewed_by_anyone,
   'First-round history must not complete the new round-two copy';
 assert row_data.team_reviewed_count=1,'History must not inflate current-dataset counts';
 assert not(to_jsonb(row_data)?'source_labels')and not(to_jsonb(row_data)?'pipeline_metadata')
   and not(to_jsonb(row_data)?'reviewer_id'),'Private history leaked';
 select *into strict row_data from public.get_review_cursor_v4(batch,2,'next');
 assert row_data.item_id=other_provider and not row_data.previously_reviewed,'Source providers were conflated';
 select *into strict row_data from public.get_review_cursor_v4(batch,3,'next');
 assert row_data.item_id=self_item and not row_data.previously_reviewed and row_data.current_version=1,
   'A current-item review was misreported as another-dataset history';
 select *into strict row_data from public.get_review_cursor_v4(batch,4,'next');
 assert row_data.item_id=legacy_copy and row_data.previously_reviewed,'Legacy image-ID fallback failed';
 select *into strict row_data from public.save_image_review_v5(copy_item,'target_not_present',null,
   gen_random_uuid(),'synthetic-history',0);
 assert row_data.item_id=fresh_item and not row_data.previously_reviewed,'Save response history belongs to the wrong image';
 assert (select second_round_label::text from public.image_reviews where item_id=copy_item)='target_not_present',
   'Second-round save semantics changed';
 assert not has_function_privilege('anon','public.get_review_cursor_v4(uuid,integer,text)','execute'),
   'Signed-out users can read review data';
 assert not has_function_privilege('authenticated','private.has_other_review(uuid)','execute'),
   'History helper can bypass review authorization';
 perform set_config('request.jwt.claims','{}',true);
 begin
  perform public.get_review_cursor_v4(batch,0,'next');
  raise exception 'Unauthenticated request accepted';
 exception when insufficient_privilege then null;end;
end;
$test$;
select '1..1' as tap;
select 'ok 1 - prior review marker preserves privacy, source identity, progress and saves' as tap;
rollback;
