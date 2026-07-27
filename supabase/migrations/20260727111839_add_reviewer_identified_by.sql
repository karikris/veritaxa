alter table private.reviewer_allowlist
  add column identified_by text;

update private.reviewer_allowlist
set identified_by = split_part(email, '@', 1)
where identified_by is null;

alter table private.reviewer_allowlist
  alter column identified_by set not null,
  add constraint reviewer_allowlist_identified_by_valid
    check (
      identified_by = btrim(identified_by)
      and identified_by <> ''
      and char_length(identified_by) <= 100
    );

alter table public.image_reviews
  add column "identifiedBy" text;

update public.image_reviews as review
set "identifiedBy" = coalesce(
  allowlist.identified_by,
  nullif(split_part(auth_user.email, '@', 1), ''),
  review.reviewer_id::text
)
from auth.users as auth_user
left join private.reviewer_allowlist as allowlist
  on lower(allowlist.email) = lower(auth_user.email)
where auth_user.id = review.reviewer_id
  and review."identifiedBy" is null;

update public.image_reviews
set "identifiedBy" = reviewer_id::text
where "identifiedBy" is null;

alter table public.image_reviews
  alter column "identifiedBy" set not null,
  add constraint image_reviews_identified_by_valid
    check (
      "identifiedBy" = btrim("identifiedBy")
      and "identifiedBy" <> ''
      and char_length("identifiedBy") <= 100
    );

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
  normalized_comment text := nullif(btrim(p_comment), '');
  normalized_client_version text := btrim(p_client_version);
  existing_review public.image_reviews%rowtype;
begin
  if current_reviewer is null then
    raise exception using errcode = '42501', message = 'Reviewer is not authorised';
  end if;

  select allowlist.identified_by
  into current_identified_by
  from private.reviewer_allowlist as allowlist
  where lower(allowlist.email) = lower(nullif(auth.jwt() ->> 'email', ''))
    and allowlist.active;

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

    raise exception using errcode = '23505', message = 'Submission ID conflicts with an existing review';
  end if;

  select item.batch_id
  into current_batch
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
    label,
    comment,
    submission_id,
    client_version
  )
  values (
    p_item_id,
    current_reviewer,
    current_identified_by,
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
