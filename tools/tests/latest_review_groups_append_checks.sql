do $test$
begin
  -- Only the attested, same-media non-target prediction joins the five original images.
  if (select count(*) from latest_group_additions)<>1
    or (select min(image_id) from latest_group_additions)<>'synthetic-excluded-6' then
    raise exception 'Append widened beyond the explicitly permitted model disagreement';
  end if;
  if (select count(*) from public.review_items i where
    i.pipeline_metadata->'_veritaxa_rereview'->>'round_code'='SYNTH-LATEST')<>6 then
    raise exception 'Append lost original images or duplicated an existing image';
  end if;
  if (select count(*) from public.image_reviews r join public.review_items i on i.id=r.item_id
    where i.pipeline_metadata->'_veritaxa_rereview'->>'round_code'='SYNTH-LATEST'
      and r.label='target_not_present' and r.version=1)<>1 then
    raise exception 'An existing second-round answer was reset';
  end if;
end;
$test$;
