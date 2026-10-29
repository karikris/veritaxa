-- Administrative data publication only; no schema or browser permissions change.
-- ROUND_CODE is replaced only after strict validation by create_rereview_round.py.
do $round$
declare
  round_code constant text := 'ROUND_CODE';
  replace_existing constant boolean := REPLACE_EXISTING;
  category_name text;
  group_row record;
  new_campaign uuid;
  new_batch uuid;
  original_reviews bigint;
  original_images bigint;
begin
  set local lock_timeout = '5s';
  lock table public.review_campaigns, public.review_batches,
    public.review_items, public.image_reviews in share row exclusive mode;

  if exists (select 1 from public.review_campaigns
    where campaign_code ~ ('^REREVIEW-' || round_code || '-[0-9]+$')) then
    raise exception 'Re-review round already exists; export the existing round instead';
  end if;

  if exists (select 1 from public.review_items where
    not coalesce(pipeline_metadata ? '_veritaxa_archive', false)
    and octet_length(pipeline_metadata::text) >= 8192) then
    raise exception 'Archive bulky pipeline metadata before creating another re-review round';
  end if;

  create temporary table rereview_original_versions on commit drop as
  select 'item'::text as kind, id, xmin::text as version from public.review_items
  union all
  select 'review', id, xmin::text from public.image_reviews;
  select count(*) into original_reviews from public.image_reviews;
  select count(*) into original_images from private.reviewed_image_keys;

  -- Snapshot first-round reviews, including closed historical batches.
  -- Conflicting labels retain separate category memberships and all votes.
  create temporary table rereview_votes on commit drop as
  select item.id as original_item_id, item.source_provider, item.image_id,
    review.updated_at, review.id as review_id,
    case when review.label::text = 'target_scientific_name'
      then 'scientific_name:' || coalesce(nullif(review."scientificName", ''),
        campaign.target_scientific_name, '(unspecified)')
      when review.label::text = 'flickr_keyword_match'
      then 'flickr_keyword:' || coalesce(review."flickrKeyword", item.flickr_search_term, '')
      else review.label::text end as category,
    to_jsonb(review) || jsonb_build_object(
      'original_campaign_code', campaign.campaign_code,
      'original_batch_code', batch.batch_code,
      'target_scientific_name', campaign.target_scientific_name,
      'image_id', item.image_id, 'source_provider', item.source_provider,
      'image_url', item.image_url, 'display_url', item.display_url
    ) as review_snapshot
  from public.image_reviews review
  join public.review_items item on item.id = review.item_id
  join public.review_batches batch on batch.id = item.batch_id
  join public.review_campaigns campaign on campaign.id = batch.campaign_id
  where not coalesce(item.pipeline_metadata ? '_veritaxa_rereview', false);

  if not exists (select 1 from rereview_votes) then
    raise exception 'No reviews exist to re-review';
  end if;

  create temporary table rereview_members on commit drop as
  select picked.*, campaign.target_scientific_name,
    row_number() over (partition by picked.category, campaign.target_scientific_name,
      picked.source_provider
      order by md5(jsonb_build_array(picked.source_provider, picked.image_id)::text),
        picked.source_provider, picked.image_id)::integer as member_position
  from (
    select category, source_provider, image_id,
      (array_agg(original_item_id order by updated_at desc, review_id))[1] as original_item_id,
      jsonb_agg(review_snapshot order by updated_at, review_id) as source_reviews
    from rereview_votes group by category, source_provider, image_id
  ) picked
  join public.review_items item on item.id = picked.original_item_id
  join public.review_batches batch on batch.id = item.batch_id
  join public.review_campaigns campaign on campaign.id = batch.campaign_id;

  for group_row in
    select category, target_scientific_name, source_provider,
      row_number() over (order by category, target_scientific_name, source_provider) as group_number
    from rereview_members group by category, target_scientific_name, source_provider
    order by category, target_scientific_name, source_provider
  loop
    category_name := case
      when group_row.category like 'scientific_name:%'
        then substring(group_row.category from length('scientific_name:') + 1)
      when group_row.category like 'flickr_keyword:%'
        then 'Keyword match: ' || substring(group_row.category from length('flickr_keyword:') + 1)
      when group_row.category = 'artifact_or_illustration' then 'Object, artwork or illustration'
      when group_row.category = 'no_biological_subject' then 'No clear biological subject'
      when group_row.category = 'arachnid' then 'Spider or other arachnid'
      else upper(left(group_row.category, 1)) || replace(substring(group_row.category from 2), '_', ' ')
    end;
    insert into public.review_campaigns (
      campaign_code, internal_name, reviewer_name, target_scientific_name, source_provider, status
    ) values (
      'REREVIEW-' || round_code || '-' || lpad(group_row.group_number::text, 3, '0'),
      'Re-review ' || round_code || ': ' || group_row.category,
      'Round 2: ' || left(category_name, 111),
      group_row.target_scientific_name, group_row.source_provider, 'open'
    ) returning id into new_campaign;

    -- A re-review folder contains the whole option, regardless of image count.
    insert into public.review_batches (
      campaign_id, batch_code, reviewer_name, position, status, opened_at
    ) values (
      new_campaign,
      'RR-' || round_code || '-' || lpad(group_row.group_number::text, 3, '0')
        || '-001',
      'Round 2: ' || left(category_name, 111),
      1, 'open', now()
    ) returning id into new_batch;

    insert into public.review_items (
      batch_id, position, image_id, source_provider, source_record_id,
      display_url, image_url, source_page_url, flickr_search_term,
      source_labels, pipeline_metadata
    )
    select new_batch, member.member_position,
      item.image_id, item.source_provider, item.source_record_id,
      item.display_url, item.image_url, item.source_page_url, item.flickr_search_term,
      item.source_labels, coalesce(item.pipeline_metadata, '{}'::jsonb)
        || jsonb_build_object('_veritaxa_rereview', jsonb_build_object(
          'round_code', round_code, 'category', member.category,
          'snapshot_at', transaction_timestamp(),
          'original_item_id', member.original_item_id,
          'source_reviews', member.source_reviews))
    from rereview_members member
    join public.review_items item on item.id = member.original_item_id
    where member.category = group_row.category
      and member.source_provider = group_row.source_provider
      and member.target_scientific_name is not distinct from group_row.target_scientific_name;
  end loop;

  if (select count(*) from public.review_items item
      join public.review_batches batch on batch.id = item.batch_id
      join public.review_campaigns campaign on campaign.id = batch.campaign_id
      where campaign.campaign_code ~ ('^REREVIEW-' || round_code || '-[0-9]+$'))
      <> (select count(*) from rereview_members) then
    raise exception 'Re-review membership count mismatch';
  end if;
  if (select count(*) from public.image_reviews) <> original_reviews
    or (select count(*) from private.reviewed_image_keys) <> original_images then
    raise exception 'Historical review inventory changed';
  end if;
  if exists (
    select 1 from rereview_original_versions original
    left join (
      select 'item'::text as kind, id, xmin::text as version from public.review_items
      union all select 'review', id, xmin::text from public.image_reviews
    ) current_row using (kind, id)
    where current_row.version is distinct from original.version
  ) then
    raise exception 'Historical records changed';
  end if;

  -- Switch visibility only after the fresh round has passed every invariant.
  -- Archived batches and their saved answers remain available to administrators.
  if replace_existing then
    update public.review_batches batch
    set status = 'archived', closed_at = transaction_timestamp()
    from public.review_campaigns campaign
    where campaign.id = batch.campaign_id
      and starts_with(campaign.campaign_code, 'REREVIEW-')
      and campaign.campaign_code !~ ('^REREVIEW-' || round_code || '-[0-9]+$')
      and batch.status <> 'archived';

    update public.review_campaigns campaign
    set status = 'archived', updated_at = transaction_timestamp()
    where starts_with(campaign.campaign_code, 'REREVIEW-')
      and campaign.campaign_code !~ ('^REREVIEW-' || round_code || '-[0-9]+$')
      and campaign.status <> 'archived';
  end if;
end;
$round$;
