create table private.reviewer_profiles (
  user_id uuid primary key references auth.users (id) on delete cascade,
  email text not null,
  identified_by text not null,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint reviewer_profiles_email_valid
    check (
      email = btrim(email)
      and email <> ''
      and char_length(email) <= 320
      and position('@' in email) > 1
    ),
  constraint reviewer_profiles_identified_by_valid
    check (
      identified_by = btrim(identified_by)
      and identified_by <> ''
      and char_length(identified_by) <= 100
    )
);

create unique index reviewer_profiles_email_lower_key
  on private.reviewer_profiles (lower(email));

alter table private.reviewer_profiles enable row level security;
revoke all on private.reviewer_profiles from public, anon, authenticated;

insert into private.reviewer_profiles (user_id, email, identified_by)
select
  auth_user.id,
  auth_user.email,
  coalesce(
    allowlist.identified_by,
    nullif(btrim(auth_user.raw_user_meta_data ->> 'identified_by'), ''),
    nullif(left(split_part(auth_user.email, '@', 1), 100), ''),
    'Reviewer'
  )
from auth.users as auth_user
left join private.reviewer_allowlist as allowlist
  on lower(allowlist.email) = lower(auth_user.email)
where auth_user.email is not null
on conflict (user_id) do nothing;

create trigger reviewer_profiles_set_updated_at
before update on private.reviewer_profiles
for each row execute function private.set_updated_at();

create function private.create_reviewer_profile()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog
as $$
declare
  requested_name text := nullif(btrim(new.raw_user_meta_data ->> 'identified_by'), '');
  profile_name text;
begin
  if new.email is null then
    return new;
  end if;

  profile_name := case
    when requested_name is not null and char_length(requested_name) <= 100
      then requested_name
    else coalesce(
      nullif(left(split_part(new.email, '@', 1), 100), ''),
      'Reviewer'
    )
  end;

  insert into private.reviewer_profiles (user_id, email, identified_by)
  values (new.id, new.email, profile_name)
  on conflict (user_id) do update
  set email = excluded.email;

  return new;
end;
$$;

revoke all on function private.create_reviewer_profile()
  from public, anon, authenticated;

create trigger auth_user_create_reviewer_profile
after insert or update of email on auth.users
for each row execute function private.create_reviewer_profile();

comment on table private.reviewer_allowlist is
  'Deprecated compatibility data. Reviewer access is now controlled by private.reviewer_profiles.';

create or replace function public.is_authorized_reviewer()
returns boolean
language sql
stable
security definer
set search_path = pg_catalog
as $$
  select
    auth.uid() is not null
    and exists (
      select 1
      from private.reviewer_profiles as profile
      where profile.user_id = auth.uid()
        and profile.active
    );
$$;

revoke all on function public.is_authorized_reviewer()
  from public, anon, authenticated;
grant execute on function public.is_authorized_reviewer() to authenticated;

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
