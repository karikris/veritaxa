-- Administrative, atomic regrouping. Existing item IDs and saved answers are retained.
-- Caller sets veritaxa.geotag_run_code and veritaxa.geotag_source_campaigns.
do $partition$
declare
  run_code text := current_setting('veritaxa.geotag_run_code');
  source_codes text[] := array(select jsonb_array_elements_text(
    current_setting('veritaxa.geotag_source_campaigns')::jsonb));
  max_batch integer := coalesce(nullif(current_setting('veritaxa.geotag_batch_size',true),''),'1000')::integer;
  point_path jsonpath := '$ ? (@.latitude.double() >= -90 && @.latitude.double() <= 90 && @.longitude.double() >= -180 && @.longitude.double() <= 180 && (@.latitude.double() != 0 || @.longitude.double() != 0))';
  group_row record;
  bucket_row record;
  new_campaign uuid;
  new_batch uuid;
  group_number integer := 0;
  offset_position bigint;
  original_reviews bigint;
  display_name text;
begin
  if run_code !~ '^[A-Z0-9][A-Z0-9-]{0,29}$' or coalesce(cardinality(source_codes),0)=0
    or max_batch not between 1 and 1000 then
    raise exception 'Explicit source campaigns, valid run code and batch size are required';
  end if;
  set local lock_timeout='5s';
  lock table public.review_campaigns,public.review_batches,public.review_items,
    public.image_reviews in share row exclusive mode;

  if exists(select 1 from public.review_campaigns c where c.campaign_code ~
    ('^NOGEO-'||run_code||'-[0-9]+$')) then
    raise exception 'This no-geotag run already exists';
  end if;
  create temporary table no_geo_inventory on commit drop as
  select i.id,i.batch_id original_batch_id,i.position original_position,
    c.id original_campaign_id,c.campaign_code original_campaign_code,
    c.reviewer_name campaign_name,c.target_taxon_key,c.target_scientific_name,
    i.source_provider,i.source_labels original_labels,
    case when i.pipeline_metadata ? '_veritaxa_rereview' then 2 else 1 end review_round,
    i.pipeline_metadata#>>'{_veritaxa_rereview,category}' original_classification_category,
    coalesce(jsonb_path_exists(coalesce(i.source_labels->'_veritaxa_geotag','{}'::jsonb),point_path,'{}',true),false)
      or coalesce(jsonb_path_exists(coalesce(i.pipeline_metadata,'{}'::jsonb),point_path,'{}',true),false) has_geotag,
    md5(i.pipeline_metadata::text) pipeline_hash,
    md5(jsonb_build_array(i.id,i.image_id,i.source_provider,i.source_record_id,
      i.display_url,i.image_url,i.source_page_url,i.flickr_search_term,i.created_at)::text) immutable_hash
  from public.review_items i join public.review_batches b on b.id=i.batch_id
  join public.review_campaigns c on c.id=b.campaign_id
  where c.campaign_code=any(source_codes) and c.status='open' and b.status='open'
    and b.batch_code !~ '(^|-)NOGEO-';
  create unique index on no_geo_inventory(id);
  if not exists(select 1 from no_geo_inventory where not has_geotag) then
    raise exception 'No images without usable geotags in the selected live scope';
  end if;

  create temporary table no_geo_review_versions on commit drop as
    select id,xmin::text row_version from public.image_reviews;
  select count(*) into original_reviews from public.image_reviews;

  create temporary table no_geo_groups on commit drop as
    select review_round,
      case when review_round=1 then original_campaign_id::text
        else jsonb_build_array(target_taxon_key,target_scientific_name,source_provider)::text end group_key,
      min(campaign_name) campaign_name,min(target_taxon_key) target_taxon_key,
      min(target_scientific_name) target_scientific_name,min(source_provider) source_provider,
      count(*) images,ceil(count(*)::numeric/max_batch)::integer batch_count
    from no_geo_inventory where not has_geotag
    group by review_round,case when review_round=1 then original_campaign_id::text
      else jsonb_build_array(target_taxon_key,target_scientific_name,source_provider)::text end;
  create temporary table no_geo_destinations(id uuid primary key,new_batch_id uuid,
    new_position integer) on commit drop;

  -- Location status is separate from the stored biological classification.
  update public.review_items i set source_labels=coalesce(i.source_labels,'{}'::jsonb)||
    jsonb_build_object('has_geotag',s.has_geotag,
      'geolocation_status',case when s.has_geotag then 'geotagged' else 'no_geotag' end,
      '_veritaxa_geolocation',jsonb_build_object('run_code',run_code,
        'review_round',s.review_round,'checked_at',transaction_timestamp(),
        'original_batch_id',s.original_batch_id,'original_position',s.original_position,
        'original_campaign_id',s.original_campaign_id,
        'original_classification_category',s.original_classification_category,
        'category',case when s.has_geotag then 'geotagged' else 'no_geotag' end,
        'reason',case when s.has_geotag then 'usable_recorded_or_provisional_coordinates'
          when s.original_labels#>>'{_veritaxa_geotag,status}'='unresolved'
            then 'location_clues_unresolved' else 'no_usable_coordinate_record' end))
    from no_geo_inventory s where i.id=s.id;

  for group_row in select * from no_geo_groups order by review_round,campaign_name,group_key loop
    group_number:=group_number+1;
    display_name:=case when group_row.review_round=2 then 'No geotag (round 2)'
      else 'No geotag — '||left(group_row.campaign_name,92) end;
    insert into public.review_campaigns(campaign_code,internal_name,reviewer_name,
      target_taxon_key,target_scientific_name,source_provider,status)
    values('NOGEO-'||run_code||'-'||lpad(group_number::text,3,'0'),
      'No usable geotag; biological review labels retained',display_name,
      group_row.target_taxon_key,group_row.target_scientific_name,group_row.source_provider,'open')
    returning id into new_campaign;

    for bucket_row in select generate_series(1,group_row.batch_count) bucket_number loop
      insert into public.review_batches(campaign_id,batch_code,reviewer_name,position,status,opened_at)
      values(new_campaign,'ZZ-NOGEO-'||run_code||'-R'||group_row.review_round||'-'||
        lpad(group_number::text,3,'0')||'-'||lpad(bucket_row.bucket_number::text,3,'0'),
        display_name||case when group_row.batch_count>1 then ' — '||bucket_row.bucket_number||
          ' of '||group_row.batch_count else '' end,bucket_row.bucket_number,'open',now())
      returning id into new_batch;
      insert into no_geo_destinations
      select id,new_batch,row_number()over(order by original_campaign_code,original_batch_id,
        original_position,id)::integer from (
        select s.*,ntile(group_row.batch_count)over(order by original_campaign_code,
          original_batch_id,original_position,id) bucket_number
        from no_geo_inventory s where not s.has_geotag and s.review_round=group_row.review_round
          and (case when s.review_round=1 then s.original_campaign_id::text else
            jsonb_build_array(s.target_taxon_key,s.target_scientific_name,s.source_provider)::text end)
            =group_row.group_key
      ) members where members.bucket_number=bucket_row.bucket_number;
    end loop;
  end loop;

  update public.review_items i set batch_id=d.new_batch_id,position=d.new_position
    from no_geo_destinations d where i.id=d.id;
  -- Keep the remaining cursor positions contiguous without unique-key collisions.
  select max(original_position)::bigint+count(*)+1 into offset_position from no_geo_inventory;
  if 2*(select max(original_position)::bigint from no_geo_inventory)+
    (select count(*) from no_geo_inventory)+1>=2147483647 then
    raise exception 'Cannot safely stage cursor positions';
  end if;
  update public.review_items i set position=(i.position+offset_position)::integer
    from no_geo_inventory s where i.id=s.id and s.has_geotag;
  update public.review_items i set position=p.position from (
    select id,row_number()over(partition by original_batch_id order by original_position,id)::integer position
    from no_geo_inventory where has_geotag
  ) p where i.id=p.id;
  update public.review_batches b set status='closed',closed_at=now()
    where b.id in(select distinct original_batch_id from no_geo_inventory)
      and not exists(select 1 from public.review_items i where i.batch_id=b.id);

  if (select count(*) from no_geo_destinations)<>(select count(*) from no_geo_inventory where not has_geotag)
    or exists(select 1 from no_geo_inventory s left join public.review_items i on i.id=s.id
      where i.id is null or md5(i.pipeline_metadata::text) is distinct from s.pipeline_hash
        or md5(jsonb_build_array(i.id,i.image_id,i.source_provider,i.source_record_id,
          i.display_url,i.image_url,i.source_page_url,i.flickr_search_term,i.created_at)::text)
          is distinct from s.immutable_hash
        or (i.source_labels-'has_geotag'-'geolocation_status'-'_veritaxa_geolocation')
          is distinct from (coalesce(s.original_labels,'{}'::jsonb)-'has_geotag'-'geolocation_status'-'_veritaxa_geolocation'))
  then raise exception 'Image inventory or original metadata changed'; end if;
  if (select count(*) from public.image_reviews)<>original_reviews or exists(
    select 1 from no_geo_review_versions v left join public.image_reviews r on r.id=v.id
    where r.id is null or r.xmin::text is distinct from v.row_version
  ) then raise exception 'Saved reviews changed'; end if;
  if exists(select 1 from no_geo_inventory s join public.review_items i on i.id=s.id
    left join no_geo_destinations d on d.id=s.id
    where (s.has_geotag and i.batch_id<>s.original_batch_id)
      or (not s.has_geotag and i.batch_id is distinct from d.new_batch_id)
      or i.source_labels->>'geolocation_status' is distinct from
        case when s.has_geotag then 'geotagged' else 'no_geotag' end
  ) then raise exception 'Geotagged/no-geotag partition mismatch'; end if;
  if exists(select 1 from public.review_items i where i.batch_id in (
    select original_batch_id from no_geo_inventory union select new_batch_id from no_geo_destinations)
    group by i.batch_id having min(position)<>1 or max(position)<>count(*)
  ) then raise exception 'Cursor positions are not contiguous'; end if;
end;
$partition$;
