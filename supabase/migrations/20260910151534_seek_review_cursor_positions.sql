-- Seek and wrap using the existing batch/position B-trees. Position is unique
-- within a batch, so an ID tie-breaker is redundant and can add incremental sorts.
-- Authorization, resume ordering, response fields and exact per-reviewer progress
-- are unchanged. Progress still counts the batch; this is not a constant-time RPC.

create or replace function public.get_review_cursor(
  p_batch_id uuid,
  p_anchor_position integer,
  p_direction text
)
returns table (
  item_id uuid,
  image_id text,
  target_scientific_name text,
  display_url text,
  fallback_image_url text,
  "position" integer,
  current_label public.review_label,
  current_comment text,
  current_version integer,
  reviewed_count bigint,
  total_count bigint,
  complete boolean
)
language plpgsql
volatile
security definer
set search_path = pg_catalog
as $$
declare
  cursor_direction text := lower(btrim(p_direction));
  selected_item_id uuid;
begin
  if not public.is_authorized_reviewer() then
    raise exception using errcode = '42501', message = 'Reviewer is not authorised';
  end if;

  if cursor_direction is null
    or cursor_direction not in ('resume', 'next', 'previous')
  then
    raise exception using errcode = '22023', message = 'Review cursor direction is invalid';
  end if;

  if cursor_direction <> 'resume' and p_anchor_position is null then
    raise exception using errcode = '22023', message = 'Review cursor anchor is required';
  end if;

  if not exists (
    select 1
    from public.review_batches as batch
    join public.review_campaigns as campaign on campaign.id = batch.campaign_id
    where batch.id = p_batch_id
      and batch.status = 'open'::public.batch_status
      and campaign.status = 'open'::public.campaign_status
  ) then
    raise exception using errcode = '22023', message = 'Batch is not available for review';
  end if;

  if cursor_direction = 'resume' then
    select item.id
    into selected_item_id
    from public.review_items as item
    left join public.image_reviews as review
      on review.item_id = item.id
      and review.reviewer_id = auth.uid()
    where item.batch_id = p_batch_id
    order by (review.id is not null), item.position, item.id
    limit 1;
  elsif cursor_direction = 'next' then
    select item.id
    into selected_item_id
    from public.review_items as item
    where item.batch_id = p_batch_id
      and item.position > p_anchor_position
    order by item.position
    limit 1;

    if not found then
      select item.id
      into selected_item_id
      from public.review_items as item
      where item.batch_id = p_batch_id
      order by item.position
      limit 1;
    end if;
  else
    select item.id
    into selected_item_id
    from public.review_items as item
    where item.batch_id = p_batch_id
      and item.position < p_anchor_position
    order by item.position desc
    limit 1;

    if not found then
      select item.id
      into selected_item_id
      from public.review_items as item
      where item.batch_id = p_batch_id
      order by item.position desc
      limit 1;
    end if;
  end if;

  if selected_item_id is null then
    return;
  end if;

  return query
  with progress as (
    select
      count(review.id) as reviewed_count,
      count(item.id) as total_count
    from public.review_items as item
    left join public.image_reviews as review
      on review.item_id = item.id
      and review.reviewer_id = auth.uid()
    where item.batch_id = p_batch_id
  )
  select
    item.id as item_id,
    item.image_id,
    campaign.target_scientific_name,
    item.display_url,
    item.image_url as fallback_image_url,
    item.position as "position",
    case
      when review.label = 'flickr_keyword_match'::public.review_label then null
      else review.label
    end as current_label,
    review.comment as current_comment,
    coalesce(review.version, 0) as current_version,
    progress.reviewed_count,
    progress.total_count,
    progress.total_count > 0
      and progress.reviewed_count = progress.total_count as complete
  from public.review_items as item
  join public.review_batches as batch on batch.id = item.batch_id
  join public.review_campaigns as campaign on campaign.id = batch.campaign_id
  left join public.image_reviews as review
    on review.item_id = item.id
    and review.reviewer_id = auth.uid()
  cross join progress
  where item.id = selected_item_id;
end;
$$;

revoke all on function public.get_review_cursor(uuid, integer, text)
  from public, anon, authenticated;
grant execute on function public.get_review_cursor(uuid, integer, text)
  to authenticated;
