-- Run setup, partition_no_geotag.sql and assertions inside one rolled-back transaction.
do $fixture$
declare
  reviewer uuid:=gen_random_uuid();
  campaign uuid;
  batch uuid;
  codes jsonb:='[]';
  code text;
  group_n integer;
  item_n integer;
  item_id uuid;
  labels jsonb;
  metadata jsonb;
  target text:='Synthetic no-geotag '||gen_random_uuid();
begin
  insert into auth.users(id,raw_user_meta_data) values(reviewer,
    '{"identified_by":"Synthetic geotag reviewer"}');
  for group_n in 1..4 loop
    code:='SYNTH-GEOTAG-'||group_n||'-'||gen_random_uuid();
    codes:=codes||jsonb_build_array(code);
    insert into public.review_campaigns(campaign_code,internal_name,reviewer_name,
      target_scientific_name,status) values(code,'Synthetic geotag partition',
      'Synthetic cohort '||group_n,target,'open') returning id into campaign;
    insert into public.review_batches(campaign_id,batch_code,reviewer_name,position,status)
      values(campaign,code,'Synthetic source '||group_n,1,'open') returning id into batch;
    for item_n in select generate_series(case group_n when 1 then 1 when 2 then 6
      when 3 then 8 else 10 end,case group_n when 1 then 5 when 2 then 7
      when 3 then 9 else 10 end) loop
      labels:=jsonb_build_object('original_biology','saved synthetic label');
      metadata:=jsonb_build_object('private','synthetic payload');
      if item_n in(1,2,8) then labels:=labels||jsonb_build_object('_veritaxa_geotag',
        jsonb_build_object('latitude',case when item_n=1 then 0 else 12 end,
          'longitude',30,'status',case when item_n=2 then 'provisional' else 'source_reported' end));
      elsif item_n=4 then labels:=labels||'{"_veritaxa_geotag":{"latitude":0,"longitude":0}}';
      elsif item_n=5 then labels:=labels||'{"_veritaxa_geotag":{"latitude":"missing","longitude":20}}';
      elsif item_n=6 then metadata:=metadata||'{"latitude":"-12.5","longitude":"130.2"}';
      end if;
      if group_n>=3 then metadata:=metadata||jsonb_build_object('_veritaxa_rereview',
        jsonb_build_object('round_code','SYNTH-GEOTAG','category',case when group_n=3
          then 'yes_target' else 'no_target' end));end if;
      insert into public.review_items(batch_id,position,image_id,source_provider,
        source_record_id,image_url,source_labels,pipeline_metadata)
        values(batch,item_n,'synthetic-geotag-'||item_n,'synthetic',item_n::text,
          'https://images.example.invalid/geotag.svg',labels,metadata) returning id into item_id;
      insert into public.image_reviews(item_id,reviewer_id,label,submission_id,client_version,"identifiedBy")
        values(item_id,reviewer,'moth',gen_random_uuid(),'synthetic','Synthetic geotag reviewer');
    end loop;
  end loop;
  perform set_config('veritaxa.geotag_run_code','SYNTH-GEOTAG',true);
  perform set_config('veritaxa.geotag_source_campaigns',codes::text,true);
  perform set_config('veritaxa.geotag_batch_size','2',true);
  perform set_config('request.jwt.claims',jsonb_build_object('sub',reviewer,'role','authenticated')::text,true);
end;
$fixture$;
