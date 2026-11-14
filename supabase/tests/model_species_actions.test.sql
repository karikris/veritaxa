begin;
create extension if not exists pgtap with schema extensions;
set search_path=public,extensions;
select plan(11);
select ok(not has_function_privilege('anon','public.get_review_cursor_v3(uuid,integer,text)','execute'),'anonymous users cannot read predictions');
select ok(not has_function_privilege('anon','public.save_image_review_v4(uuid,public.review_label,text,uuid,text,integer)','execute'),'anonymous users cannot save answers');
select ok(not has_function_privilege('authenticated','private.review_model_prediction(uuid)','execute'),'private prediction helper cannot bypass cursor authorization');
insert into auth.users(id,email,raw_user_meta_data) values('71000000-0000-0000-0000-000000000001','model-actions@example.invalid','{"identified_by":"Synthetic model reviewer"}');
insert into review_campaigns(id,internal_name,reviewer_name,campaign_code,target_scientific_name,status) values('72000000-0000-0000-0000-000000000001','Synthetic model actions','Synthetic model actions','SYNTH-MODEL-ACTIONS','Papilio exemplaris','open');
insert into review_batches(id,campaign_id,batch_code,reviewer_name,position,status) values('73000000-0000-0000-0000-000000000001','72000000-0000-0000-0000-000000000001','SYNTH-MODEL-ACTIONS','Synthetic model actions',1,'open');
insert into review_items(id,batch_id,position,image_id,source_provider,image_url,pipeline_metadata) values
('74000000-0000-0000-0000-000000000001','73000000-0000-0000-0000-000000000001',1,'synthetic-model-one','synthetic','https://images.example.invalid/model.png','{"bioclip":{"attestation":{"model":"imageomics/bioclip-2.5-vith14"},"top10":[{"scientific_name":"Papilio testensis","cosine":0.6789}]},"private":"not exposed"}'),
('74000000-0000-0000-0000-000000000002','73000000-0000-0000-0000-000000000001',2,'synthetic-model-two','synthetic','https://images.example.invalid/no-model.png','{}');
select set_config('request.jwt.claim.sub','71000000-0000-0000-0000-000000000001',true);
set local role authenticated;
select is((select model_scientific_name from get_review_cursor_v3('73000000-0000-0000-0000-000000000001',null,'resume')),'Papilio testensis','cursor returns requested model species');
select is((select model_cosine from get_review_cursor_v3('73000000-0000-0000-0000-000000000001',null,'resume')),0.6789::double precision,'cursor returns raw cosine');
select lives_ok($$select * from save_image_review_v4('74000000-0000-0000-0000-000000000001','model_scientific_name',null,'75000000-0000-0000-0000-000000000001','synthetic-test',0)$$,'model choice saves immediately');
select lives_ok($$select * from save_image_review_v4('74000000-0000-0000-0000-000000000001','model_scientific_name',null,'75000000-0000-0000-0000-000000000001','synthetic-test',0)$$,'retry is idempotent');
select throws_ok($$select * from save_image_review_v4('74000000-0000-0000-0000-000000000002','model_scientific_name',null,gen_random_uuid(),'synthetic-test',0)$$,'22023','No valid model prediction is available','missing model prediction fails closed');
reset role;
select is((select "scientificName" from image_reviews where item_id='74000000-0000-0000-0000-000000000001'),'Papilio testensis','stored species comes from trusted model metadata');
select is((select version from image_reviews where item_id='74000000-0000-0000-0000-000000000001'),1,'retry does not create another version');
select is((select "flickrKeyword" from image_reviews where item_id='74000000-0000-0000-0000-000000000001'),null::text,'source keywords stay out of model confirmation');
select * from finish();
rollback;
