-- Administrative regrouping only: retain item IDs, reviews and frozen provenance.
-- ROUND_CODE is replaced only after strict validation by create_rereview_round.py.
do $regroup$
declare
  round_code constant text := 'ROUND_CODE';
  position_offset bigint;
begin
  set local lock_timeout = '5s';
  lock table public.review_campaigns, public.review_batches,
    public.review_items, public.image_reviews in share row exclusive mode;

  if not exists (select 1 from public.review_campaigns
    where campaign_code ~ ('^REREVIEW-' || round_code || '-[0-9]+$')) then
    raise exception 'Re-review round does not exist';
  end if;
  if exists (select 1 from public.review_campaigns
    where campaign_code ~ ('^REREVIEW-' || round_code || '-[0-9]+$') and status <> 'open') then
    raise exception 'Only an open re-review round can be regrouped';
  end if;

  create temporary table regroup_original_versions on commit drop as
  select 'item'::text as kind, id, xmin::text as version from public.review_items
  union all
  select 'review', id, xmin::text from public.image_reviews;

  create temporary table regroup_members on commit drop as
  select item.id, item.batch_id, item.position,
    item.source_provider, item.image_id,
    item.pipeline_metadata->'_veritaxa_rereview'->>'round_code' as snapshot_round,
    item.pipeline_metadata->'_veritaxa_rereview'->>'category' as category,
    batch.campaign_id,
    first_value(batch.id) over (partition by batch.campaign_id
      order by (batch.status = 'open') desc, batch.position, batch.id) as destination,
    row_number() over (partition by batch.campaign_id
      order by batch.position, item.position, item.id)::integer as destination_position,
    md5((to_jsonb(item) - 'batch_id' - 'position')::text) as content_hash
  from public.review_items item
  join public.review_batches batch on batch.id = item.batch_id
  join public.review_campaigns campaign on campaign.id = batch.campaign_id
  where campaign.campaign_code ~ ('^REREVIEW-' || round_code || '-[0-9]+$');

  if not exists (select 1 from regroup_members) then
    raise exception 'Re-review round contains no images';
  end if;
  if exists (select 1 from regroup_members
    where snapshot_round is distinct from round_code or category is null)
    or exists (select 1 from regroup_members group by campaign_id
      having count(distinct category) <> 1) then
    raise exception 'Re-review folder contains missing or mixed option provenance';
  end if;
  if exists (select 1 from regroup_members group by campaign_id, image_id having count(*) > 1) then
    raise exception 'Re-review folder contains duplicate image IDs';
  end if;
  if exists (select 1 from public.review_batches batch
    where batch.id in (select destination from regroup_members) and batch.status <> 'open') then
    raise exception 'Re-review folder has no open destination';
  end if;

  -- Immediate uniqueness constraints require staging positions outside the
  -- existing range before moving rows into their contiguous final positions.
  select greatest(max(position), max(destination_position)) into position_offset
  from regroup_members;
  if position_offset + (select max(destination_position) from regroup_members) > 2147483647 then
    raise exception 'Re-review folder exceeds the supported position range';
  end if;

  update public.review_items item
  set position = (position_offset + member.destination_position)::integer
  from regroup_members member
  where item.id = member.id
    and (member.batch_id <> member.destination or member.position <> member.destination_position);

  update public.review_items item
  set batch_id = member.destination, position = member.destination_position
  from regroup_members member
  where item.id = member.id
    and (member.batch_id <> member.destination or member.position <> member.destination_position);

  update public.review_batches batch
  set status = 'closed', closed_at = transaction_timestamp()
  where batch.campaign_id in (select campaign_id from regroup_members)
    and batch.id not in (select destination from regroup_members)
    and batch.status <> 'closed';

  update public.review_batches batch
  set reviewer_name = campaign.reviewer_name || ' / folder '
    || substring(campaign.campaign_code from '[0-9]+$')
  from public.review_campaigns campaign
  where batch.campaign_id = campaign.id
    and batch.id in (select destination from regroup_members)
    and batch.reviewer_name is distinct from campaign.reviewer_name || ' / folder '
      || substring(campaign.campaign_code from '[0-9]+$');

  if exists (select 1 from regroup_members member
    left join public.review_items item on item.id = member.id
    where item.id is null or item.batch_id <> member.destination
      or item.position <> member.destination_position
      or md5((to_jsonb(item) - 'batch_id' - 'position')::text) <> member.content_hash) then
    raise exception 'Re-review folder verification failed';
  end if;
  if (select count(*) from regroup_original_versions) <>
    (select count(*) from public.review_items) + (select count(*) from public.image_reviews)
    or exists (
      select 1 from regroup_original_versions original
      left join (
        select 'item'::text as kind, id, xmin::text as version from public.review_items
        union all select 'review', id, xmin::text from public.image_reviews
      ) current_row using (kind, id)
      where (original.kind = 'review' or original.id not in (select id from regroup_members))
        and current_row.version is distinct from original.version
    ) then
    raise exception 'Historical records changed';
  end if;
end;
$regroup$;
