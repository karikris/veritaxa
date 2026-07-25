create schema if not exists private;

revoke all on schema private from public, anon, authenticated;

create type public.review_label as enum (
  'adult_butterfly',
  'caterpillar',
  'moth',
  'other_insect',
  'arachnid',
  'other_arthropod',
  'plant',
  'mammal_or_person',
  'bird',
  'other_animal',
  'fungus',
  'artifact_or_illustration',
  'no_biological_subject',
  'uncertain',
  'image_unavailable'
);

create type public.campaign_status as enum ('draft', 'open', 'closed', 'archived');
create type public.batch_status as enum ('draft', 'open', 'closed', 'archived');

create table private.reviewer_allowlist (
  email text primary key,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  created_by text,
  notes text,
  constraint reviewer_allowlist_email_valid
    check (
      email = btrim(email)
      and email <> ''
      and char_length(email) <= 320
      and position('@' in email) > 1
    )
);

create unique index reviewer_allowlist_email_lower_key
  on private.reviewer_allowlist (lower(email));

alter table private.reviewer_allowlist enable row level security;
revoke all on private.reviewer_allowlist from public, anon, authenticated;

create table public.review_campaigns (
  id uuid primary key default gen_random_uuid(),
  internal_name text not null,
  reviewer_name text not null,
  campaign_code text unique not null,
  target_taxon_key text,
  target_scientific_name text,
  source_provider text,
  status public.campaign_status not null default 'draft',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint review_campaigns_internal_name_valid
    check (internal_name = btrim(internal_name) and internal_name <> ''),
  constraint review_campaigns_reviewer_name_valid
    check (
      reviewer_name = btrim(reviewer_name)
      and reviewer_name <> ''
      and char_length(reviewer_name) <= 120
    ),
  constraint review_campaigns_code_valid
    check (
      campaign_code = btrim(campaign_code)
      and campaign_code <> ''
      and char_length(campaign_code) <= 80
    )
);

create table public.review_batches (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references public.review_campaigns (id),
  batch_code text unique not null,
  reviewer_name text not null,
  position integer not null,
  status public.batch_status not null default 'draft',
  created_at timestamptz not null default now(),
  opened_at timestamptz,
  closed_at timestamptz,
  constraint review_batches_position_positive check (position > 0),
  constraint review_batches_campaign_position_key unique (campaign_id, position),
  constraint review_batches_code_valid
    check (
      batch_code = btrim(batch_code)
      and batch_code <> ''
      and char_length(batch_code) <= 80
    ),
  constraint review_batches_reviewer_name_valid
    check (
      reviewer_name = btrim(reviewer_name)
      and reviewer_name <> ''
      and char_length(reviewer_name) <= 120
    )
);

create table public.review_items (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null references public.review_batches (id),
  position integer not null,
  image_id text not null,
  source_provider text not null,
  source_record_id text,
  display_url text,
  image_url text not null,
  source_page_url text,
  flickr_search_term text,
  source_labels jsonb,
  pipeline_metadata jsonb,
  created_at timestamptz not null default now(),
  constraint review_items_batch_position_key unique (batch_id, position),
  constraint review_items_batch_image_key unique (batch_id, image_id),
  constraint review_items_position_positive check (position > 0),
  constraint review_items_image_id_valid
    check (image_id = btrim(image_id) and image_id <> '' and char_length(image_id) <= 500),
  constraint review_items_provider_valid
    check (
      source_provider = btrim(source_provider)
      and source_provider <> ''
      and char_length(source_provider) <= 120
    ),
  constraint review_items_image_url_https
    check (image_url ~ '^https://[^[:space:]]+$'),
  constraint review_items_display_url_https
    check (display_url is null or display_url ~ '^https://[^[:space:]]+$'),
  constraint review_items_source_page_url_https
    check (source_page_url is null or source_page_url ~ '^https://[^[:space:]]+$')
);

create table public.image_reviews (
  id uuid primary key default gen_random_uuid(),
  item_id uuid not null references public.review_items (id),
  reviewer_id uuid not null references auth.users (id),
  label public.review_label not null,
  comment text,
  submission_id uuid not null unique,
  client_version text not null,
  created_at timestamptz not null default now(),
  constraint image_reviews_item_reviewer_key unique (item_id, reviewer_id),
  constraint image_reviews_comment_valid
    check (
      comment is null
      or (
        comment = btrim(comment)
        and char_length(comment) between 1 and 1000
      )
    ),
  constraint image_reviews_client_version_valid
    check (
      client_version = btrim(client_version)
      and client_version <> ''
      and char_length(client_version) <= 100
    )
);

create index review_batches_campaign_id_idx on public.review_batches (campaign_id);
create index review_items_batch_unreviewed_idx on public.review_items (batch_id, position, id);
create index image_reviews_reviewer_item_idx on public.image_reviews (reviewer_id, item_id);

alter table public.review_campaigns enable row level security;
alter table public.review_batches enable row level security;
alter table public.review_items enable row level security;
alter table public.image_reviews enable row level security;

revoke all on public.review_campaigns from public, anon, authenticated;
revoke all on public.review_batches from public, anon, authenticated;
revoke all on public.review_items from public, anon, authenticated;
revoke all on public.image_reviews from public, anon, authenticated;

alter default privileges in schema public
  revoke all on tables from anon, authenticated;
alter default privileges in schema public
  revoke execute on functions from public, anon, authenticated;

create function private.set_updated_at()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

revoke all on function private.set_updated_at() from public, anon, authenticated;

create trigger review_campaigns_set_updated_at
before update on public.review_campaigns
for each row execute function private.set_updated_at();

create function private.prevent_review_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
begin
  raise exception using
    errcode = '55000',
    message = 'Image reviews are append-only';
end;
$$;

revoke all on function private.prevent_review_mutation() from public, anon, authenticated;

create trigger image_reviews_append_only
before update or delete on public.image_reviews
for each row execute function private.prevent_review_mutation();

create function public.is_authorized_reviewer()
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
      from private.reviewer_allowlist as allowlist
      where lower(allowlist.email) = lower(nullif(auth.jwt() ->> 'email', ''))
        and allowlist.active
    );
$$;

revoke all on function public.is_authorized_reviewer() from public, anon, authenticated;
grant execute on function public.is_authorized_reviewer() to authenticated;

create function public.list_review_batches()
returns table (
  batch_id uuid,
  reviewer_name text,
  batch_code text,
  reviewed_count bigint,
  total_count bigint,
  complete boolean
)
language plpgsql
stable
security definer
set search_path = pg_catalog
as $$
begin
  if not public.is_authorized_reviewer() then
    raise exception using errcode = '42501', message = 'Reviewer is not authorised';
  end if;

  return query
  select
    batch.id as batch_id,
    batch.reviewer_name,
    batch.batch_code,
    count(review.id) as reviewed_count,
    count(item.id) as total_count,
    count(item.id) > 0 and count(review.id) = count(item.id) as complete
  from public.review_batches as batch
  join public.review_campaigns as campaign
    on campaign.id = batch.campaign_id
    and campaign.status = 'open'::public.campaign_status
  left join public.review_items as item on item.batch_id = batch.id
  left join public.image_reviews as review
    on review.item_id = item.id
    and review.reviewer_id = auth.uid()
  where batch.status = 'open'::public.batch_status
  group by batch.id, batch.reviewer_name, batch.batch_code, batch.position
  order by batch.position, batch.batch_code;
end;
$$;

revoke all on function public.list_review_batches() from public, anon, authenticated;
grant execute on function public.list_review_batches() to authenticated;

create function public.get_review_queue(
  p_batch_id uuid,
  p_limit integer default 2
)
returns table (
  item_id uuid,
  image_id text,
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

create function public.submit_image_review(
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
  current_batch uuid;
  normalized_comment text := nullif(btrim(p_comment), '');
  normalized_client_version text := btrim(p_client_version);
  existing_review public.image_reviews%rowtype;
begin
  if current_reviewer is null or not public.is_authorized_reviewer() then
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
    label,
    comment,
    submission_id,
    client_version
  )
  values (
    p_item_id,
    current_reviewer,
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
