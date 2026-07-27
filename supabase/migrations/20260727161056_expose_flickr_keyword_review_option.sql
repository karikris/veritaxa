alter table public.review_items
  add constraint review_items_flickr_search_term_valid
  check (
    flickr_search_term is null
    or (
      flickr_search_term = btrim(flickr_search_term)
      and flickr_search_term <> ''
      and char_length(flickr_search_term) <= 1000
    )
  ) not valid;

alter table public.review_items
  validate constraint review_items_flickr_search_term_valid;

alter table public.image_reviews
  add column "flickrKeyword" text,
  add constraint image_reviews_flickr_keyword_valid
  check (
    (
      label = 'flickr_keyword_match'::public.review_label
      and "flickrKeyword" is not null
      and "flickrKeyword" = btrim("flickrKeyword")
      and "flickrKeyword" <> ''
      and char_length("flickrKeyword") <= 1000
    )
    or (
      label <> 'flickr_keyword_match'::public.review_label
      and "flickrKeyword" is null
    )
  );

drop function public.get_review_queue(uuid, integer);

create function public.get_review_queue(
  p_batch_id uuid,
  p_limit integer default 2
)
returns table (
  item_id uuid,
  image_id text,
  flickr_keyword text,
  display_url text,
  fallback_image_url text,
  "position" integer,
  reviewed_count bigint,
  total_count bigint
)
language plpgsql
stable
security definer
set search_path = pg_catalog
as $$
declare
  queue_limit integer := least(greatest(coalesce(p_limit, 2), 1), 2);
begin
  if not public.is_authorized_reviewer() then
    raise exception using errcode = '42501', message = 'Reviewer is not authorised';
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
    item.flickr_search_term as flickr_keyword,
    item.display_url,
    item.image_url as fallback_image_url,
    item.position as "position",
    progress.reviewed_count,
    progress.total_count
  from public.review_items as item
  cross join progress
  where item.batch_id = p_batch_id
    and not exists (
      select 1
      from public.image_reviews as review
      where review.item_id = item.id
        and review.reviewer_id = auth.uid()
    )
  order by item.position, item.id
  limit queue_limit;
end;
$$;

revoke all on function public.get_review_queue(uuid, integer)
  from public, anon, authenticated;
grant execute on function public.get_review_queue(uuid, integer) to authenticated;

create or replace function public.submit_image_review(
  p_item_id uuid,
  p_label public.review_label,
  p_comment text,
  p_submission_id uuid,
  p_client_version text
)
returns table (
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
  current_reviewer uuid := auth.uid();
  current_identified_by text;
  current_batch uuid;
  current_flickr_keyword text;
  normalized_comment text := nullif(btrim(p_comment), '');
  normalized_client_version text := btrim(p_client_version);
  existing_review public.image_reviews%rowtype;
begin
  if current_reviewer is null then
    raise exception using errcode = '42501', message = 'Reviewer is not authorised';
  end if;

  select profile.identified_by
  into current_identified_by
  from private.reviewer_profiles as profile
  where profile.user_id = current_reviewer
    and profile.active;

  if current_identified_by is null then
    raise exception using errcode = '42501', message = 'Reviewer is not authorised';
  end if;

  if p_submission_id is null then
    raise exception using errcode = '22023', message = 'Submission ID is required';
  end if;

  if p_label is null then
    raise exception using errcode = '22023', message = 'Review label is required';
  end if;

  if normalized_comment is not null and char_length(normalized_comment) > 1000 then
    raise exception using errcode = '22001', message = 'Comment exceeds 1000 characters';
  end if;

  if normalized_client_version is null
    or normalized_client_version = ''
    or char_length(normalized_client_version) > 100
  then
    raise exception using errcode = '22023', message = 'Client version is invalid';
  end if;

  select review.*
  into existing_review
  from public.image_reviews as review
  where review.submission_id = p_submission_id;

  if found then
    if existing_review.reviewer_id = current_reviewer
      and existing_review.item_id = p_item_id
      and existing_review.label = p_label
      and existing_review.comment is not distinct from normalized_comment
      and existing_review.client_version = normalized_client_version
    then
      select item.batch_id into current_batch
      from public.review_items as item
      where item.id = existing_review.item_id;

      return query
      select
        count(review.id) as reviewed_count,
        count(item.id) as total_count,
        count(item.id) > 0 and count(review.id) = count(item.id) as complete
      from public.review_items as item
      left join public.image_reviews as review
        on review.item_id = item.id
        and review.reviewer_id = current_reviewer
      where item.batch_id = current_batch;
      return;
    end if;

    raise exception using errcode = '23505',
      message = 'Submission ID conflicts with an existing review';
  end if;

  select
    item.batch_id,
    item.flickr_search_term
  into
    current_batch,
    current_flickr_keyword
  from public.review_items as item
  join public.review_batches as batch on batch.id = item.batch_id
  join public.review_campaigns as campaign on campaign.id = batch.campaign_id
  where item.id = p_item_id
    and batch.status = 'open'::public.batch_status
    and campaign.status = 'open'::public.campaign_status
  for share of item;

  if current_batch is null then
    raise exception using errcode = '22023', message = 'Item is not available for review';
  end if;

  if p_label = 'flickr_keyword_match'::public.review_label
    and current_flickr_keyword is null
  then
    raise exception using errcode = '22023',
      message = 'Item has no Flickr keyword to select';
  end if;

  if exists (
    select 1
    from public.image_reviews as review
    where review.item_id = p_item_id
      and review.reviewer_id = current_reviewer
  ) then
    raise exception using errcode = '23505', message = 'Item has already been reviewed';
  end if;

  insert into public.image_reviews (
    item_id,
    reviewer_id,
    "identifiedBy",
    "flickrKeyword",
    label,
    comment,
    submission_id,
    client_version
  )
  values (
    p_item_id,
    current_reviewer,
    current_identified_by,
    case
      when p_label = 'flickr_keyword_match'::public.review_label
        then current_flickr_keyword
      else null
    end,
    p_label,
    normalized_comment,
    p_submission_id,
    normalized_client_version
  );

  return query
  select
    count(review.id) as reviewed_count,
    count(item.id) as total_count,
    count(item.id) > 0 and count(review.id) = count(item.id) as complete
  from public.review_items as item
  left join public.image_reviews as review
    on review.item_id = item.id
    and review.reviewer_id = current_reviewer
  where item.batch_id = current_batch;
end;
$$;

revoke all on function public.submit_image_review(
  uuid,
  public.review_label,
  text,
  uuid,
  text
) from public, anon, authenticated;

grant execute on function public.submit_image_review(
  uuid,
  public.review_label,
  text,
  uuid,
  text
) to authenticated;
