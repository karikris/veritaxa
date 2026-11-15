-- Canonical source identity survives imports and round-two copies. Only a
-- boolean reaches the client; prior answers, reviewer identity and source
-- metadata remain private.
create index review_items_source_record_identity_idx
  on public.review_items (source_provider, (coalesce(nullif(source_record_id, ''), image_id)))
  include (id);

create function private.has_other_review(p_item_id uuid)
returns boolean language sql stable security invoker set search_path=pg_catalog
begin atomic
  select exists (
    select 1 from public.review_items current_item
    join public.review_items earlier_item
      on earlier_item.source_provider=current_item.source_provider
      and coalesce(nullif(earlier_item.source_record_id,''),earlier_item.image_id)
        =coalesce(nullif(current_item.source_record_id,''),current_item.image_id)
      and earlier_item.id<>current_item.id
      and earlier_item.batch_id<>current_item.batch_id
    join public.image_reviews review on review.item_id=earlier_item.id
    where current_item.id=p_item_id
  );
end;
revoke all on function private.has_other_review(uuid) from public,anon,authenticated,service_role;

create function private.get_review_cursor_v4(p_batch_id uuid,p_anchor_position integer,p_direction text)
returns table(item_id uuid, image_id text, target_scientific_name text, display_url text, fallback_image_url text,
  "position" integer, current_label public.review_label, current_comment text, current_version integer,
  reviewed_count bigint, total_count bigint, complete boolean, team_reviewed_count bigint,
  reviewed_by_anyone boolean, model_scientific_name text, model_cosine double precision,
  previously_reviewed boolean)
language sql volatile security definer set search_path=pg_catalog
begin atomic
  -- The existing API enforces authorization, open-batch access and save retries.
  select cursor_row.*,private.has_other_review(cursor_row.item_id)
  from private.get_review_cursor_v3(p_batch_id,p_anchor_position,p_direction) cursor_row;
end;
create function public.get_review_cursor_v4(p_batch_id uuid,p_anchor_position integer,p_direction text)
returns table(item_id uuid, image_id text, target_scientific_name text, display_url text, fallback_image_url text,
  "position" integer, current_label public.review_label, current_comment text, current_version integer,
  reviewed_count bigint, total_count bigint, complete boolean, team_reviewed_count bigint,
  reviewed_by_anyone boolean, model_scientific_name text, model_cosine double precision,
  previously_reviewed boolean)
language sql volatile security invoker set search_path=pg_catalog
begin atomic
  select * from private.get_review_cursor_v4(p_batch_id,p_anchor_position,p_direction);
end;
revoke all on function private.get_review_cursor_v4(uuid,integer,text),
  public.get_review_cursor_v4(uuid,integer,text) from public,anon,authenticated;
grant execute on function private.get_review_cursor_v4(uuid,integer,text),
  public.get_review_cursor_v4(uuid,integer,text) to authenticated,service_role;

create function private.save_image_review_v5(p_item_id uuid,p_label public.review_label,p_comment text,p_submission_id uuid,p_client_version text,p_expected_version integer)
returns table(item_id uuid, image_id text, target_scientific_name text, display_url text, fallback_image_url text,
  "position" integer, current_label public.review_label, current_comment text, current_version integer,
  reviewed_count bigint, total_count bigint, complete boolean, team_reviewed_count bigint,
  reviewed_by_anyone boolean, model_scientific_name text, model_cosine double precision,
  previously_reviewed boolean)
language sql volatile security definer set search_path=pg_catalog
begin atomic
  -- The existing API enforces authorization, open-batch access and save retries.
  select cursor_row.*,private.has_other_review(cursor_row.item_id)
  from private.save_image_review_v4(p_item_id,p_label,p_comment,p_submission_id,p_client_version,p_expected_version) cursor_row;
end;
create function public.save_image_review_v5(p_item_id uuid,p_label public.review_label,p_comment text,p_submission_id uuid,p_client_version text,p_expected_version integer)
returns table(item_id uuid, image_id text, target_scientific_name text, display_url text, fallback_image_url text,
  "position" integer, current_label public.review_label, current_comment text, current_version integer,
  reviewed_count bigint, total_count bigint, complete boolean, team_reviewed_count bigint,
  reviewed_by_anyone boolean, model_scientific_name text, model_cosine double precision,
  previously_reviewed boolean)
language sql volatile security invoker set search_path=pg_catalog
begin atomic
  select * from private.save_image_review_v5(p_item_id,p_label,p_comment,p_submission_id,p_client_version,p_expected_version);
end;
revoke all on function private.save_image_review_v5(uuid,public.review_label,text,uuid,text,integer),
  public.save_image_review_v5(uuid,public.review_label,text,uuid,text,integer) from public,anon,authenticated;
grant execute on function private.save_image_review_v5(uuid,public.review_label,text,uuid,text,integer),
  public.save_image_review_v5(uuid,public.review_label,text,uuid,text,integer) to authenticated,service_role;

notify pgrst, 'reload schema';
