-- Image identity is provider + image ID across all campaigns/batches.
-- Keep historical reviews and the owner-scoped correction API intact.
create index review_items_provider_image_idx
  on public.review_items (source_provider, image_id) include (id);

create view private.reviewed_image_keys with (security_invoker = true) as
select distinct item.source_provider, item.image_id
from public.review_items item
join public.image_reviews review on review.item_id = item.id;
revoke all on private.reviewed_image_keys from public, anon, authenticated;

create function private.list_pending_review_batches()
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
    count(reviewed.image_id), count(item.id), false
  from public.review_batches batch
  join public.review_campaigns campaign on campaign.id = batch.campaign_id
  join public.review_items item on item.batch_id = batch.id
  left join private.reviewed_image_keys reviewed
    on reviewed.source_provider = item.source_provider and reviewed.image_id = item.image_id
  where batch.status = 'open' and campaign.status = 'open'
  group by batch.id, batch.reviewer_name, batch.batch_code, batch.position
  having count(reviewed.image_id) < count(item.id)
  order by batch.position, batch.batch_code;
end;
$$;

create function private.get_pending_review_cursor(p_batch_id uuid, p_anchor_position integer, p_direction text)
returns table (
  item_id uuid, image_id text, target_scientific_name text,
  display_url text, fallback_image_url text, "position" integer,
  current_label public.review_label, current_comment text, current_version integer,
  reviewed_count bigint, total_count bigint, complete boolean
)
language plpgsql volatile security definer set search_path = pg_catalog
as $$
declare
  direction text := lower(btrim(p_direction));
  selected_id uuid;
begin
  if not public.is_authorized_reviewer() then
    raise exception using errcode = '42501', message = 'Reviewer is not authorised';
  end if;
  if direction is null or direction not in ('resume', 'next', 'previous') then
    raise exception using errcode = '22023', message = 'Review cursor direction is invalid';
  end if;
  if direction <> 'resume' and p_anchor_position is null then
    raise exception using errcode = '22023', message = 'Review cursor anchor is required';
  end if;
  if not exists (
    select 1 from public.review_batches batch
    join public.review_campaigns campaign on campaign.id = batch.campaign_id
    where batch.id = p_batch_id and batch.status = 'open' and campaign.status = 'open'
  ) then
    raise exception using errcode = '22023', message = 'Batch is not available for review';
  end if;

  -- Each batch is bounded to 1,000 images. Sort only its unreviewed candidates,
  -- wrapping at either end without ever falling back to a reviewed image.
  select item.id into selected_id
  from public.review_items item
  where item.batch_id = p_batch_id
    and not exists (
      select 1 from private.reviewed_image_keys reviewed
      where reviewed.source_provider = item.source_provider and reviewed.image_id = item.image_id
    )
  order by
    case
      when direction = 'resume' then 0
      when direction = 'next' and item.position > p_anchor_position then 0
      when direction = 'previous' and item.position < p_anchor_position then 0
      else 1
    end,
    case when direction = 'previous' then item.position end desc,
    item.position
  limit 1;
  if selected_id is null then return; end if;

  return query
  with progress as (
    select count(reviewed.image_id) as reviewed_count, count(item.id) as total_count
    from public.review_items item
    left join private.reviewed_image_keys reviewed
      on reviewed.source_provider = item.source_provider and reviewed.image_id = item.image_id
    where item.batch_id = p_batch_id
  )
  select item.id, item.image_id, campaign.target_scientific_name,
    item.display_url, item.image_url, item.position,
    null::public.review_label, null::text, 0,
    progress.reviewed_count, progress.total_count, false
  from public.review_items item
  join public.review_batches batch on batch.id = item.batch_id
  join public.review_campaigns campaign on campaign.id = batch.campaign_id
  cross join progress
  where item.id = selected_id;
end;
$$;

create function private.save_pending_image_review(
  p_item_id uuid, p_label public.review_label, p_comment text,
  p_submission_id uuid, p_client_version text, p_expected_version integer
)
returns table (
  item_id uuid, image_id text, target_scientific_name text,
  display_url text, fallback_image_url text, "position" integer,
  current_label public.review_label, current_comment text, current_version integer,
  reviewed_count bigint, total_count bigint, complete boolean
)
language plpgsql volatile security definer set search_path = pg_catalog
as $$
declare
  selected_item public.review_items%rowtype;
begin
  if not public.is_authorized_reviewer() then
    raise exception using errcode = '42501', message = 'Reviewer is not authorised';
  end if;
  select * into selected_item from public.review_items where id = p_item_id;
  if not found then
    raise exception using errcode = '22023', message = 'Item is not available for review';
  end if;

  -- Serialize submissions for the same image, including copies in other batches.
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    jsonb_build_array(selected_item.source_provider, selected_item.image_id)::text, 0
  ));
  if exists (
    select 1 from private.reviewed_image_keys reviewed
    where reviewed.source_provider = selected_item.source_provider
      and reviewed.image_id = selected_item.image_id
  ) and not exists (
    select 1 from public.image_reviews review
    where review.item_id = p_item_id and review.reviewer_id = auth.uid()
  ) then
    raise exception using errcode = 'PT409', message = 'Image has already been reviewed';
  end if;

  -- Reuse established validation, optimistic versioning and retry idempotency.
  -- An owner's pending retry/correction remains valid even after the image leaves the queue.
  perform public.save_image_review_v2(
    p_item_id, p_label, p_comment, p_submission_id, p_client_version, p_expected_version
  );
  return query select * from private.get_pending_review_cursor(
    selected_item.batch_id, selected_item.position, 'next'
  );
end;
$$;

create function public.list_pending_review_batches()
returns table (
  batch_id uuid, reviewer_name text, batch_code text,
  reviewed_count bigint, total_count bigint, complete boolean
)
language sql stable security invoker set search_path = pg_catalog
begin atomic
  select * from private.list_pending_review_batches();
end;

create function public.get_pending_review_cursor(p_batch_id uuid, p_anchor_position integer, p_direction text)
returns table (
  item_id uuid, image_id text, target_scientific_name text,
  display_url text, fallback_image_url text, "position" integer,
  current_label public.review_label, current_comment text, current_version integer,
  reviewed_count bigint, total_count bigint, complete boolean
)
language sql volatile security invoker set search_path = pg_catalog
begin atomic
  select * from private.get_pending_review_cursor(p_batch_id, p_anchor_position, p_direction);
end;

create function public.save_pending_image_review(p_item_id uuid, p_label public.review_label, p_comment text,
  p_submission_id uuid, p_client_version text, p_expected_version integer)
returns table (
  item_id uuid, image_id text, target_scientific_name text,
  display_url text, fallback_image_url text, "position" integer,
  current_label public.review_label, current_comment text, current_version integer,
  reviewed_count bigint, total_count bigint, complete boolean
)
language sql volatile security invoker set search_path = pg_catalog
begin atomic
  select * from private.save_pending_image_review(p_item_id, p_label, p_comment, p_submission_id, p_client_version, p_expected_version);
end;

revoke all on function public.list_pending_review_batches() from public, anon, authenticated;
grant execute on function public.list_pending_review_batches() to authenticated, service_role;

revoke all on function public.get_pending_review_cursor(uuid, integer, text) from public, anon, authenticated;
grant execute on function public.get_pending_review_cursor(uuid, integer, text) to authenticated, service_role;

revoke all on function public.save_pending_image_review(uuid, public.review_label, text, uuid, text, integer) from public, anon, authenticated;
grant execute on function public.save_pending_image_review(uuid, public.review_label, text, uuid, text, integer) to authenticated, service_role;

revoke all on function private.list_pending_review_batches() from public, anon, authenticated;
grant execute on function private.list_pending_review_batches() to authenticated, service_role;

revoke all on function private.get_pending_review_cursor(uuid, integer, text) from public, anon, authenticated;
grant execute on function private.get_pending_review_cursor(uuid, integer, text) to authenticated, service_role;

revoke all on function private.save_pending_image_review(uuid, public.review_label, text, uuid, text, integer) from public, anon, authenticated;
grant execute on function private.save_pending_image_review(uuid, public.review_label, text, uuid, text, integer) to authenticated, service_role;
