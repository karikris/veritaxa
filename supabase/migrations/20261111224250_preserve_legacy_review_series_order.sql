-- Keep the reviewer API and access checks unchanged; prioritize queue purpose.
create or replace function private.list_review_batches()
returns table (
  batch_id uuid, reviewer_name text, batch_code text,
  reviewed_count bigint, total_count bigint, complete boolean
)
language plpgsql stable security definer set search_path = pg_catalog
as $$
begin
  if not public.is_authorized_reviewer() then
    raise exception using errcode = '42501', message = 'Reviewer is not authorised';
  end if;

  return query
  select batch.id, batch.reviewer_name, batch.batch_code,
    count(review.id), count(item.id),
    count(item.id) > 0 and count(review.id) = count(item.id)
  from public.review_batches batch
  join public.review_campaigns campaign
    on campaign.id = batch.campaign_id and campaign.status = 'open'::public.campaign_status
  left join public.review_items item on item.batch_id = batch.id
  left join public.image_reviews review
    on review.item_id = item.id and review.reviewer_id = auth.uid()
  where batch.status = 'open'::public.batch_status
  group by batch.id, batch.reviewer_name, batch.batch_code, batch.position
  order by
    case
      when min(campaign.campaign_code) like 'PDEM-GEOTAGGED-%' then 0
      when min(campaign.campaign_code) ~ '^PDEM-YOLOE-A-'
        or substring(upper(batch.batch_code) from '(?:^|-)([ABC])-[0-9]+(?:-|$)') = 'A' then 1
      when min(campaign.campaign_code) ~ '^PDEM-YOLOE-B-'
        or substring(upper(batch.batch_code) from '(?:^|-)([ABC])-[0-9]+(?:-|$)') = 'B' then 2
      when min(campaign.campaign_code) ~ '^PDEM-YOLOE-C-'
        or substring(upper(batch.batch_code) from '(?:^|-)([ABC])-[0-9]+(?:-|$)') = 'C' then 3
      when min(item.pipeline_metadata->'_veritaxa_rereview'->>'category')
        like 'scientific_name:%' then 4
      when min(item.pipeline_metadata->'_veritaxa_rereview'->>'category')
        = 'adult_butterfly' then 5
      when min(item.pipeline_metadata->'_veritaxa_rereview'->>'category')
        = 'caterpillar' then 6
      when min(item.pipeline_metadata->'_veritaxa_rereview'->>'category')
        = 'moth' then 7
      when min(item.pipeline_metadata->'_veritaxa_rereview'->>'category')
        = 'other_insect' then 8
      else 9
    end,
    batch.batch_code, batch.position, batch.id;
end;
$$;
