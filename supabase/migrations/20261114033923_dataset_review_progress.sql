-- Additive API: older tabs retain their existing cursor and save contracts.
-- Counts describe saved human reviews in this dataset, never species certainty.
create function private.list_review_batches_v2()
returns table (
  batch_id uuid, reviewer_name text, batch_code text,
  reviewed_count bigint, total_count bigint, complete boolean,
  team_reviewed_count bigint, review_round integer
)
language plpgsql stable security definer set search_path = pg_catalog
as $$
begin
  if not public.is_authorized_reviewer() then
    raise exception using errcode = '42501', message = 'Reviewer is not authorised';
  end if;
  return query
  select listed.batch_id, listed.reviewer_name, listed.batch_code,
    listed.reviewed_count, listed.total_count, listed.complete,
    progress.team_count, progress.round_number
  from private.list_review_batches() with ordinality listed
  cross join lateral (
    select count(*) filter (where exists (
      select 1 from public.image_reviews r where r.item_id = i.id
    )) as team_count,
    case when bool_or(i.pipeline_metadata ? '_veritaxa_rereview') then 2 else 1 end
      as round_number
    from public.review_items i where i.batch_id = listed.batch_id
  ) progress
  order by
    -- Keep pending work ahead of completed datasets; preserve established order within each.
    (progress.team_count >= listed.total_count),
    listed.ordinality;
end;
$$;

create function private.get_review_cursor_v2(
  p_batch_id uuid, p_anchor_position integer, p_direction text
)
returns table (
  item_id uuid, image_id text, target_scientific_name text,
  display_url text, fallback_image_url text, "position" integer,
  current_label public.review_label, current_comment text, current_version integer,
  reviewed_count bigint, total_count bigint, complete boolean,
  team_reviewed_count bigint, reviewed_by_anyone boolean
)
language plpgsql volatile security definer set search_path = pg_catalog
as $$
begin
  -- The existing cursor enforces reviewer authorization and open-batch access.
  return query
  select cursor_row.*, (
    select count(*) from public.review_items i where i.batch_id = p_batch_id
      and exists (select 1 from public.image_reviews r where r.item_id = i.id)
  ), exists (select 1 from public.image_reviews r where r.item_id = cursor_row.item_id)
  from private.get_review_cursor(p_batch_id, p_anchor_position, p_direction) cursor_row;
end;
$$;

create function private.save_image_review_v3(
  p_item_id uuid, p_label public.review_label, p_comment text,
  p_submission_id uuid, p_client_version text, p_expected_version integer
)
returns table (
  item_id uuid, image_id text, target_scientific_name text,
  display_url text, fallback_image_url text, "position" integer,
  current_label public.review_label, current_comment text, current_version integer,
  reviewed_count bigint, total_count bigint, complete boolean,
  team_reviewed_count bigint, reviewed_by_anyone boolean
)
language plpgsql volatile security definer set search_path = pg_catalog
as $$
declare
  saved_cursor record;
  current_batch uuid;
begin
  -- Keep optimistic locking, idempotent retries and next-image behavior unchanged.
  select * into saved_cursor from private.save_image_review_v2(
    p_item_id, p_label, p_comment, p_submission_id, p_client_version, p_expected_version
  );
  if saved_cursor.item_id is null then return; end if;
  select i.batch_id into current_batch from public.review_items i where i.id = p_item_id;
  return query
  select saved_cursor.item_id, saved_cursor.image_id, saved_cursor.target_scientific_name,
    saved_cursor.display_url, saved_cursor.fallback_image_url, saved_cursor.position,
    saved_cursor.current_label, saved_cursor.current_comment, saved_cursor.current_version,
    saved_cursor.reviewed_count, saved_cursor.total_count, saved_cursor.complete,
    (select count(*) from public.review_items i where i.batch_id = current_batch
      and exists (select 1 from public.image_reviews r where r.item_id = i.id)),
    exists (select 1 from public.image_reviews r where r.item_id = saved_cursor.item_id);
end;
$$;

create function public.list_review_batches_v2()
returns table (
  batch_id uuid, reviewer_name text, batch_code text,
  reviewed_count bigint, total_count bigint, complete boolean,
  team_reviewed_count bigint, review_round integer
)
language sql stable security invoker set search_path = pg_catalog
begin atomic
  select * from private.list_review_batches_v2();
end;

create function public.get_review_cursor_v2(
  p_batch_id uuid, p_anchor_position integer, p_direction text
)
returns table (
  item_id uuid, image_id text, target_scientific_name text,
  display_url text, fallback_image_url text, "position" integer,
  current_label public.review_label, current_comment text, current_version integer,
  reviewed_count bigint, total_count bigint, complete boolean,
  team_reviewed_count bigint, reviewed_by_anyone boolean
)
language sql volatile security invoker set search_path = pg_catalog
begin atomic
  select * from private.get_review_cursor_v2(p_batch_id, p_anchor_position, p_direction);
end;

create function public.save_image_review_v3(
  p_item_id uuid, p_label public.review_label, p_comment text,
  p_submission_id uuid, p_client_version text, p_expected_version integer
)
returns table (
  item_id uuid, image_id text, target_scientific_name text,
  display_url text, fallback_image_url text, "position" integer,
  current_label public.review_label, current_comment text, current_version integer,
  reviewed_count bigint, total_count bigint, complete boolean,
  team_reviewed_count bigint, reviewed_by_anyone boolean
)
language sql volatile security invoker set search_path = pg_catalog
begin atomic
  select * from private.save_image_review_v3(
    p_item_id, p_label, p_comment, p_submission_id, p_client_version, p_expected_version
  );
end;

revoke all on function private.list_review_batches_v2(),
  private.get_review_cursor_v2(uuid, integer, text),
  private.save_image_review_v3(uuid, public.review_label, text, uuid, text, integer)
  from public, anon, authenticated;
revoke all on function public.list_review_batches_v2(),
  public.get_review_cursor_v2(uuid, integer, text),
  public.save_image_review_v3(uuid, public.review_label, text, uuid, text, integer)
  from public, anon, authenticated;
grant execute on function private.list_review_batches_v2(),
  private.get_review_cursor_v2(uuid, integer, text),
  private.save_image_review_v3(uuid, public.review_label, text, uuid, text, integer)
  to authenticated, service_role;
grant execute on function public.list_review_batches_v2(),
  public.get_review_cursor_v2(uuid, integer, text),
  public.save_image_review_v3(uuid, public.review_label, text, uuid, text, integer)
  to authenticated, service_role;

notify pgrst, 'reload schema';
