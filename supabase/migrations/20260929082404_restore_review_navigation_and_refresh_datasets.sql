-- Reduce the published data once. Subsequent reviews must not change dataset
-- membership: reviewers can navigate to saved images and correct their answers.
-- Keep every original item and review; only close affected old batches and
-- publish their remaining items in replacement batches.
set local lock_timeout = '5s';
lock table public.review_campaigns, public.review_batches,
  public.review_items, public.image_reviews in share row exclusive mode;

do $$
declare
  original_batch public.review_batches%rowtype;
  replacement_id uuid;
  remaining_count bigint;
  inserted_count bigint;
  original_item_ids uuid[];
  original_item_versions text;
  original_reviews_digest text;
  original_source_images bigint;
begin
  -- Row versions prove that all pre-existing item fields, including private
  -- source metadata, remain untouched without exporting or copying that data.
  select array_agg(item.id), md5(string_agg(item.id::text || ':' || item.xmin::text, ',' order by item.id))
  into original_item_ids, original_item_versions
  from public.review_items item;
  select md5(string_agg(to_jsonb(review)::text, ',' order by review.id))
  into original_reviews_digest from public.image_reviews review;
  select count(*) into original_source_images
  from (select distinct source_provider, image_id from public.review_items) images;

  for original_batch in
    select batch.*
    from public.review_batches batch
    join public.review_campaigns campaign on campaign.id = batch.campaign_id
    where batch.status = 'open' and campaign.status = 'open'
      and exists (
        select 1 from public.review_items item
        join private.reviewed_image_keys reviewed
          on reviewed.source_provider = item.source_provider
          and reviewed.image_id = item.image_id
        where item.batch_id = batch.id
      )
    order by batch.campaign_id, batch.position
  loop
    select count(*) into remaining_count
    from public.review_items item
    where item.batch_id = original_batch.id
      and not exists (
        select 1 from private.reviewed_image_keys reviewed
        where reviewed.source_provider = item.source_provider
          and reviewed.image_id = item.image_id
      );

    if remaining_count > 1000 then
      raise exception 'Replacement review batches must contain at most 1,000 images';
    end if;

    if remaining_count > 0 then
      insert into public.review_batches (
        campaign_id, batch_code, reviewer_name, position, status, opened_at
      )
      select original_batch.campaign_id, original_batch.batch_code || '-remaining',
        original_batch.reviewer_name, coalesce(max(batch.position), 0) + 1, 'open', now()
      from public.review_batches batch
      where batch.campaign_id = original_batch.campaign_id
      returning id into replacement_id;

      insert into public.review_items (
        batch_id, position, image_id, source_provider, source_record_id,
        display_url, image_url, source_page_url, flickr_search_term,
        source_labels, pipeline_metadata
      )
      select replacement_id, row_number() over (order by item.position)::integer,
        item.image_id, item.source_provider, item.source_record_id,
        item.display_url, item.image_url, item.source_page_url, item.flickr_search_term,
        item.source_labels, item.pipeline_metadata
      from public.review_items item
      where item.batch_id = original_batch.id
        and not exists (
          select 1 from private.reviewed_image_keys reviewed
          where reviewed.source_provider = item.source_provider
            and reviewed.image_id = item.image_id
        );
      get diagnostics inserted_count = row_count;
      if inserted_count <> remaining_count then
        raise exception 'Replacement review dataset count mismatch';
      end if;
    end if;

    update public.review_batches set status = 'closed', closed_at = now()
    where id = original_batch.id;
  end loop;

  if original_item_versions is distinct from (
    select md5(string_agg(item.id::text || ':' || item.xmin::text, ',' order by item.id))
    from public.review_items item where item.id = any(original_item_ids)
  ) then
    raise exception 'Historical source image records changed; aborting publication';
  end if;
  if original_reviews_digest is distinct from (
    select md5(string_agg(to_jsonb(review)::text, ',' order by review.id))
    from public.image_reviews review
  ) then
    raise exception 'Historical reviews changed; aborting publication';
  end if;
  if original_source_images <> (
    select count(*) from (select distinct source_provider, image_id from public.review_items) images
  ) then
    raise exception 'Source image inventory changed; aborting publication';
  end if;
end;
$$;

-- Already-open browser bundles may still call the short-lived pending APIs.
-- Preserve those signatures as aliases of the original workflow, including
-- saved answers, per-reviewer progress, retries, corrections and wraparound.
-- Public bound invoker wrappers and their existing grants remain unchanged.
create or replace function private.list_pending_review_batches()
returns table (
  batch_id uuid, reviewer_name text, batch_code text,
  reviewed_count bigint, total_count bigint, complete boolean
)
language sql stable security definer set search_path = pg_catalog
begin atomic
  select * from private.list_review_batches();
end;

create or replace function private.get_pending_review_cursor(
  p_batch_id uuid, p_anchor_position integer, p_direction text
)
returns table (
  item_id uuid, image_id text, target_scientific_name text,
  display_url text, fallback_image_url text, "position" integer,
  current_label public.review_label, current_comment text, current_version integer,
  reviewed_count bigint, total_count bigint, complete boolean
)
language sql volatile security definer set search_path = pg_catalog
begin atomic
  select * from private.get_review_cursor(p_batch_id, p_anchor_position, p_direction);
end;

create or replace function private.save_pending_image_review(
  p_item_id uuid, p_label public.review_label, p_comment text,
  p_submission_id uuid, p_client_version text, p_expected_version integer
)
returns table (
  item_id uuid, image_id text, target_scientific_name text,
  display_url text, fallback_image_url text, "position" integer,
  current_label public.review_label, current_comment text, current_version integer,
  reviewed_count bigint, total_count bigint, complete boolean
)
language sql volatile security definer set search_path = pg_catalog
begin atomic
  select * from private.save_image_review_v2(
    p_item_id, p_label, p_comment, p_submission_id, p_client_version, p_expected_version
  );
end;
