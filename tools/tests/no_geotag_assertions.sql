do $test$
declare
  item_id uuid;
  bucket uuid;
  response record;
begin
  if (select count(*) from no_geo_inventory)<>10
    or (select count(*) from no_geo_inventory where has_geotag)<>4
    or (select count(*) from no_geo_destinations)<>6 then
    raise exception 'Point validation or total partition failed';
  end if;
  if (select count(*) from no_geo_groups)<>3
    or (select count(distinct new_batch_id) from no_geo_destinations)<>4 then
    raise exception 'First-round cohort separation or balanced batching failed';
  end if;
  if (select count(*) from public.review_items i join no_geo_destinations d on d.id=i.id
    where i.pipeline_metadata ? '_veritaxa_rereview')<>2 then
    raise exception 'Round-two membership lost';
  end if;
  if exists(select 1 from public.review_items i join no_geo_inventory s on s.id=i.id
    where i.source_labels->>'original_biology'<>'saved synthetic label') then
    raise exception 'Biological labels changed';
  end if;
  if (select count(distinct i.batch_id) from public.review_items i
    join no_geo_destinations d on d.id=i.id where i.pipeline_metadata ? '_veritaxa_rereview')<>1 then
    raise exception 'Round-two no-geotag category was not consolidated';
  end if;
  if exists(select 1 from public.review_batches b join public.review_items i on i.batch_id=b.id
    where b.batch_code like 'ZZ-NOGEO-SYNTH-GEOTAG-%' group by b.id having count(*)>2) then
    raise exception 'Bucket capacity exceeded';
  end if;
  select i.id,i.batch_id into item_id,bucket from public.review_items i
    join no_geo_destinations d on d.id=i.id where i.pipeline_metadata ? '_veritaxa_rereview' limit 1;
  select * into strict response from public.list_review_batches_v2() where batch_id=bucket;
  if response.review_round<>2 or response.total_count<>2 or response.team_reviewed_count<>2 then
    raise exception 'Reviewer dataset API does not recognise round-two no-geotag bucket';
  end if;
  select * into strict response from public.get_review_cursor_v3(bucket,null,'resume');
  if response.current_label<>'moth' or response.current_version<>1 then
    raise exception 'Existing saved answer is inaccessible after moving';
  end if;
end;
$test$;
