-- Explicit cohort, time window, and attested BioCLIP evidence are mandatory.
-- Copy queue memberships; retain every historical item and saved review unchanged.
do $publish$
declare
  round_code text := current_setting('veritaxa.round_code');
  target_name text := current_setting('veritaxa.target_name');
  source_campaigns text[] := array(select jsonb_array_elements_text(
    current_setting('veritaxa.source_campaigns')::jsonb));
  reviewed_after timestamptz := current_setting('veritaxa.reviewed_after')::timestamptz;
  reviewed_before timestamptz := current_setting('veritaxa.reviewed_before')::timestamptz;
  other_model_campaigns text[] := array(select jsonb_array_elements_text(coalesce(nullif(
    current_setting('veritaxa.other_model_campaigns',true),''),'[]')::jsonb));
  append_existing boolean := coalesce(nullif(
    current_setting('veritaxa.append_existing',true),''),'false')::boolean;
  reopen_source_batches boolean := coalesce(nullif(
    current_setting('veritaxa.reopen_source_batches',true),''),'false')::boolean;
  group_row record;
  new_campaign_id uuid;
  new_batch_id uuid;
  saved_review_count bigint;
  existing_image_count bigint;
  base_position integer;
begin
  if round_code !~ '^[A-Z0-9][A-Z0-9-]{0,29}$' or length(target_name) not between 1 and 500 then
    raise exception 'Invalid round code or target name';
  end if;
  if not other_model_campaigns <@ source_campaigns then
    raise exception 'Other-model campaign exceptions must belong to the explicit source cohort';
  end if;
  if coalesce(cardinality(source_campaigns),0)=0 or reviewed_after is null
    or reviewed_before is null or reviewed_after >= reviewed_before then
    raise exception 'Explicit source campaigns and a valid review time window are required';
  end if;
  set local lock_timeout = '5s';
  lock table public.review_campaigns, public.review_batches,
    public.review_items, public.image_reviews in share row exclusive mode;
  if exists (select 1 from public.review_campaigns c
    where c.campaign_code like 'REREVIEW-' || round_code || '-%') and not append_existing then
    raise exception 'Round already exists; choose a new code';
  end if;
  select count(*) into existing_image_count from public.review_items i
    join public.review_batches b on b.id=i.batch_id
    join public.review_campaigns c on c.id=b.campaign_id
    where c.campaign_code like 'REREVIEW-' || round_code || '-%';
  if append_existing and existing_image_count=0 then
    raise exception 'An existing populated round is required for append';
  end if;
  select count(*) into saved_review_count from public.image_reviews;
  create temporary table latest_group_originals on commit drop as
    select 'item'::text kind, id, xmin::text version from public.review_items
    union all select 'review', id, xmin::text from public.image_reviews;

  create temporary table latest_group_eligible on commit drop as
  select distinct i.source_provider,i.image_id
  from public.image_reviews r
  join public.review_items i on i.id=r.item_id
  join public.review_batches b on b.id=i.batch_id
  join public.review_campaigns c on c.id=b.campaign_id
  where c.target_scientific_name=target_name and c.campaign_code=any(source_campaigns)
    and (i.pipeline_metadata#>>'{bioclip,top5,0,scientific_name}'=target_name
      or (c.campaign_code=any(other_model_campaigns)
        and nullif(i.pipeline_metadata#>>'{bioclip,top5,0,scientific_name}','') is not null))
    and i.pipeline_metadata#>>'{bioclip,attestation,model}' ilike '%bioclip%'
    and nullif(i.pipeline_metadata->>'bioclip_media_byte_sha256','') is not null
    and i.pipeline_metadata->>'scored_cache_image_sha256'=
      'sha256:'||(i.pipeline_metadata->>'bioclip_media_byte_sha256')
    and r.updated_at>=i.created_at
    and ((r.created_at>=reviewed_after and r.created_at<reviewed_before)
      or (r.updated_at>=reviewed_after and r.updated_at<reviewed_before));
  create unique index on latest_group_eligible(source_provider,image_id);

  create temporary table latest_group_votes on commit drop as
  select i.id original_item_id, i.source_provider, i.image_id, r.id review_id,
    r.updated_at, r.label::text label, to_jsonb(r) review_snapshot,
    c.campaign_code source_campaign_code
  from public.image_reviews r
  join public.review_items i on i.id = r.item_id
  join public.review_batches b on b.id = i.batch_id
  join public.review_campaigns c on c.id = b.campaign_id
  join latest_group_eligible eligible on eligible.source_provider=i.source_provider
    and eligible.image_id=i.image_id
  where c.target_scientific_name = target_name and c.campaign_code=any(source_campaigns)
    and (i.pipeline_metadata#>>'{bioclip,top5,0,scientific_name}'=target_name
      or (c.campaign_code=any(other_model_campaigns)
        and nullif(i.pipeline_metadata#>>'{bioclip,top5,0,scientific_name}','') is not null))
    and i.pipeline_metadata#>>'{bioclip,attestation,model}' ilike '%bioclip%'
    and i.pipeline_metadata->>'scored_cache_image_sha256'=
      'sha256:'||nullif(i.pipeline_metadata->>'bioclip_media_byte_sha256','')
    and r.updated_at>=i.created_at;
  create index on latest_group_votes (source_provider, image_id);
  analyze latest_group_votes;

  if not exists (select 1 from latest_group_votes) then
    raise exception 'No human-reviewed images match the explicit cohort, date and BioCLIP target';
  end if;

  create temporary table latest_group_members on commit drop as
  select chosen.*,
    case when chosen.label = 'target_scientific_name' then 'yes_target'
      when chosen.label in ('adult_butterfly', 'target_not_present') then 'no_target'
      else 'no_butterfly' end as category,
    (select jsonb_agg(v.review_snapshot order by v.updated_at, v.review_id)
      from latest_group_votes v where v.source_provider = chosen.source_provider
        and v.image_id = chosen.image_id) source_reviews
  from (
    select distinct on (source_provider, image_id) *
    from latest_group_votes
    order by source_provider, image_id, updated_at desc, review_id desc
  ) chosen;
  create unique index on latest_group_members (source_provider, image_id);
  if exists (select 1 from latest_group_members where label = 'flickr_keyword_match') then
    raise exception 'Latest keyword answers require explicit resolution before three-way grouping';
  end if;
  create temporary table latest_group_additions on commit drop as
    select m.* from latest_group_members m where not exists (
      select 1 from public.review_items i
      join public.review_batches b on b.id=i.batch_id
      join public.review_campaigns c on c.id=b.campaign_id
      where c.campaign_code like 'REREVIEW-' || round_code || '-%'
        and i.source_provider=m.source_provider and i.image_id=m.image_id);

  for group_row in select * from (values
    (1, 'yes_target', 'Yes — ' || target_name),
    (2, 'no_target', 'No — other butterfly'),
    (3, 'no_butterfly', 'No butterfly / other or unresolved')
  ) as groups(position, category, name) order by position loop
    if append_existing then
      select b.id,c.id into strict new_batch_id,new_campaign_id
      from public.review_campaigns c join public.review_batches b on b.campaign_id=c.id
      where c.campaign_code='REREVIEW-'||round_code||'-'||lpad(group_row.position::text,3,'0')
        and c.target_scientific_name=target_name and c.status='open' and b.status='open';
    else
    insert into public.review_campaigns (
      campaign_code, internal_name, reviewer_name, target_scientific_name, status
    ) values (
      'REREVIEW-' || round_code || '-' || lpad(group_row.position::text, 3, '0'),
      'Latest saved review grouping: ' || group_row.category,
      'Round 2: ' || left(group_row.name, 111), target_name, 'open'
    ) returning id into new_campaign_id;
    insert into public.review_batches (
      campaign_id, batch_code, reviewer_name, position, status, opened_at
    ) values (
      new_campaign_id, 'RR-' || round_code || '-' || lpad(group_row.position::text, 3, '0'),
      'Round 2: ' || left(group_row.name, 111), group_row.position, 'open', now()
    ) returning id into new_batch_id;
    end if;
    select coalesce(max(i.position),0) into base_position
      from public.review_items i where i.batch_id=new_batch_id;
    insert into public.review_items (
      batch_id, position, image_id, source_provider, source_record_id,
      display_url, image_url, source_page_url, flickr_search_term, source_labels, pipeline_metadata
    )
    select new_batch_id,
      base_position + row_number() over (order by md5(jsonb_build_array(m.source_provider,m.image_id)::text),
        m.source_provider,m.image_id)::integer,
      i.image_id,i.source_provider,i.source_record_id,i.display_url,i.image_url,
      i.source_page_url,i.flickr_search_term,i.source_labels,
      (coalesce(i.pipeline_metadata, '{}'::jsonb) - '_veritaxa_rereview') ||
      jsonb_build_object('_veritaxa_rereview', jsonb_build_object(
        'round_code', round_code, 'category', m.category,
        'grouping_rule', 'latest_updated_at_then_review_id_desc',
        'eligibility',jsonb_build_object('source_campaigns',source_campaigns,
          'reviewed_after',reviewed_after,'reviewed_before',reviewed_before,
          'requires_bioclip_target_top1',not(m.source_campaign_code=any(other_model_campaigns)),
          'other_model_campaigns',other_model_campaigns,'requires_matching_scored_media',true),
        'snapshot_at', transaction_timestamp(), 'original_item_id', m.original_item_id,
        'effective_review_id', m.review_id, 'effective_label', m.label,
        'source_reviews', m.source_reviews))
    from latest_group_additions m join public.review_items i on i.id = m.original_item_id
    where m.category = group_row.category;
  end loop;

  if (select count(*) from public.review_items i
    join public.review_batches b on b.id=i.batch_id
    join public.review_campaigns c on c.id=b.campaign_id
    where c.campaign_code like 'REREVIEW-' || round_code || '-%')
    <> existing_image_count+(select count(*) from latest_group_additions) then
    raise exception 'New membership count differs from latest reviewed image inventory';
  end if;
  if exists(select 1 from public.review_items i
    join public.review_batches b on b.id=i.batch_id
    join public.review_campaigns c on c.id=b.campaign_id
    where c.campaign_code like 'REREVIEW-'||round_code||'-%'
    group by i.source_provider,i.image_id having count(*)>1) then
    raise exception 'Duplicate image membership in round';
  end if;
  if saved_review_count <> (select count(*) from public.image_reviews) or exists (
    select 1 from latest_group_originals o left join (
      select 'item'::text kind,id,xmin::text version from public.review_items
      union all select 'review',id,xmin::text from public.image_reviews
    ) current_row using (kind,id) where o.version is distinct from current_row.version
  ) then
    raise exception 'Historical items or reviews changed';
  end if;

  -- Retire older round-two menus after successful publication; keep all their data.
  update public.review_batches b set status='archived',closed_at=now()
  from public.review_campaigns c where c.id=b.campaign_id
    and c.target_scientific_name=target_name and c.campaign_code like 'REREVIEW-%'
    and c.campaign_code not like 'REREVIEW-' || round_code || '-%'
    and b.status <> 'archived';
  update public.review_campaigns c set status='archived',updated_at=now()
  where c.target_scientific_name=target_name and c.campaign_code like 'REREVIEW-%'
    and c.campaign_code not like 'REREVIEW-' || round_code || '-%'
    and c.status <> 'archived';

  -- Publishing round two must not hide first-round BioCLIP datasets.
  if reopen_source_batches then
    update public.review_batches b set status='open',closed_at=null
    from public.review_campaigns c where c.id=b.campaign_id
      and c.target_scientific_name=target_name and c.campaign_code=any(source_campaigns)
      and c.status='open' and b.status='closed';
  end if;
end;
$publish$;
