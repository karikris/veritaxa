alter table public.image_reviews
  add column version integer not null default 1,
  add column updated_at timestamptz;

alter table public.image_reviews
  disable trigger image_reviews_append_only;

update public.image_reviews
set updated_at = created_at
where updated_at is null;

alter table public.image_reviews
  enable trigger image_reviews_append_only;

alter table public.image_reviews
  alter column updated_at set default now(),
  alter column updated_at set not null,
  add constraint image_reviews_version_positive check (version > 0);

create or replace function private.prevent_review_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
begin
  if tg_op = 'DELETE' then
    raise exception using
      errcode = '55000',
      message = 'Image reviews cannot be deleted';
  end if;

  if new.id is distinct from old.id
    or new.item_id is distinct from old.item_id
    or new.reviewer_id is distinct from old.reviewer_id
    or new."identifiedBy" is distinct from old."identifiedBy"
    or new.created_at is distinct from old.created_at
  then
    raise exception using
      errcode = '55000',
      message = 'Image review identity cannot be changed';
  end if;

  if new."flickrKeyword" is distinct from old."flickrKeyword"
    and not (
      old.label = 'flickr_keyword_match'::public.review_label
      and new.label <> 'flickr_keyword_match'::public.review_label
      and new."flickrKeyword" is null
    )
  then
    raise exception using
      errcode = '55000',
      message = 'Legacy Flickr review context cannot be changed';
  end if;

  if new.version <> old.version + 1 or new.updated_at <= old.updated_at then
    raise exception using
      errcode = '55000',
      message = 'Image review corrections require the next version and update time';
  end if;

  return new;
end;
$$;

revoke all on function private.prevent_review_mutation()
  from public, anon, authenticated;

create function public.get_review_cursor(
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
    order by
      case when item.position > p_anchor_position then 0 else 1 end,
      item.position,
      item.id
    limit 1;
  else
    select item.id
    into selected_item_id
    from public.review_items as item
    where item.batch_id = p_batch_id
    order by
      case when item.position < p_anchor_position then 0 else 1 end,
      item.position desc,
      item.id desc
    limit 1;
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

create function public.save_image_review_v2(
  p_item_id uuid,
  p_label public.review_label,
  p_comment text,
  p_submission_id uuid,
  p_client_version text,
  p_expected_version integer
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
  current_reviewer uuid := auth.uid();
  current_identified_by text;
  current_batch uuid;
  current_position integer;
  current_target_scientific_name text;
  normalized_comment text := nullif(btrim(p_comment), '');
  normalized_client_version text := btrim(p_client_version);
  expected_scientific_name text;
  existing_review public.image_reviews%rowtype;
  has_existing_review boolean;
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

  if p_expected_version is null or p_expected_version < 0 then
    raise exception using errcode = '22023', message = 'Expected review version is invalid';
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

  if p_label = 'flickr_keyword_match'::public.review_label then
    raise exception using errcode = '22023',
      message = 'Flickr keyword classification is no longer supported';
  end if;

  select
    item.batch_id,
    item.position,
    campaign.target_scientific_name
  into
    current_batch,
    current_position,
    current_target_scientific_name
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

  if p_label = 'target_scientific_name'::public.review_label
    and current_target_scientific_name is null
  then
    raise exception using errcode = '22023',
      message = 'Campaign has no target scientific name to select';
  end if;

  expected_scientific_name := case
    when p_label = 'target_scientific_name'::public.review_label
      then current_target_scientific_name
    else null
  end;

  select review.*
  into existing_review
  from public.image_reviews as review
  where review.item_id = p_item_id
    and review.reviewer_id = current_reviewer
  for update;
  has_existing_review := found;

  if has_existing_review and existing_review.submission_id = p_submission_id then
    if existing_review.label = p_label
      and existing_review.comment is not distinct from normalized_comment
      and existing_review.client_version = normalized_client_version
      and existing_review."scientificName" is not distinct from expected_scientific_name
      and existing_review.version = p_expected_version + 1
    then
      return query
      select *
      from public.get_review_cursor(current_batch, current_position, 'next');
      return;
    end if;

    raise exception using errcode = '23505',
      message = 'Submission ID conflicts with an existing review';
  end if;

  if exists (
    select 1
    from public.image_reviews as review
    where review.submission_id = p_submission_id
  ) then
    raise exception using errcode = '23505',
      message = 'Submission ID conflicts with an existing review';
  end if;

  if has_existing_review then
    if existing_review.version <> p_expected_version then
      raise exception using errcode = '40001', message = 'Review version is stale';
    end if;

    update public.image_reviews as review
    set
      label = p_label,
      comment = normalized_comment,
      submission_id = p_submission_id,
      client_version = normalized_client_version,
      "flickrKeyword" = null,
      "scientificName" = expected_scientific_name,
      version = review.version + 1,
      updated_at = greatest(
        pg_catalog.clock_timestamp(),
        review.updated_at + interval '1 microsecond'
      )
    where review.id = existing_review.id;
  else
    if p_expected_version <> 0 then
      raise exception using errcode = '40001', message = 'Review version is stale';
    end if;

    insert into public.image_reviews (
      item_id,
      reviewer_id,
      "identifiedBy",
      "flickrKeyword",
      "scientificName",
      label,
      comment,
      submission_id,
      client_version,
      version,
      updated_at
    )
    values (
      p_item_id,
      current_reviewer,
      current_identified_by,
      null,
      expected_scientific_name,
      p_label,
      normalized_comment,
      p_submission_id,
      normalized_client_version,
      1,
      pg_catalog.clock_timestamp()
    );
  end if;

  return query
  select *
  from public.get_review_cursor(current_batch, current_position, 'next');
end;
$$;

revoke all on function public.save_image_review_v2(
  uuid,
  public.review_label,
  text,
  uuid,
  text,
  integer
) from public, anon, authenticated;

grant execute on function public.save_image_review_v2(
  uuid,
  public.review_label,
  text,
  uuid,
  text,
  integer
) to authenticated;
