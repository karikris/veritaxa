-- Keep the current RPC contract but separate API entry points from privileged
-- implementations. Moving the functions preserves their bodies and identities.
alter function public.is_authorized_reviewer() set schema private;
alter function public.list_review_batches() set schema private;
alter function public.get_review_cursor(uuid, integer, text) set schema private;
alter function public.save_image_review_v2(uuid, public.review_label, text, uuid, text, integer)
  set schema private;

-- SQL-standard bodies bind the private function at definition time. Callers
-- need EXECUTE on that function, but still receive no USAGE on private and no
-- table privileges. Do not replace these bodies with late-parsed string bodies
-- or grant private-schema access to make a wrapper work.
create function public.is_authorized_reviewer()
returns boolean
language sql stable security invoker set search_path = pg_catalog
return private.is_authorized_reviewer();

create function public.list_review_batches()
returns table (
  batch_id uuid, reviewer_name text, batch_code text,
  reviewed_count bigint, total_count bigint, complete boolean
)
language sql stable security invoker set search_path = pg_catalog
begin atomic
  select * from private.list_review_batches();
end;

create function public.get_review_cursor(
  p_batch_id uuid, p_anchor_position integer, p_direction text
)
returns table (
  item_id uuid, image_id text, target_scientific_name text,
  display_url text, fallback_image_url text, "position" integer,
  current_label public.review_label, current_comment text, current_version integer,
  reviewed_count bigint, total_count bigint, complete boolean
)
language sql volatile security invoker set search_path = pg_catalog
begin atomic
  select * from private.get_review_cursor(p_batch_id, p_anchor_position, p_direction);
end;

create function public.save_image_review_v2(
  p_item_id uuid, p_label public.review_label, p_comment text,
  p_submission_id uuid, p_client_version text, p_expected_version integer
)
returns table (
  item_id uuid, image_id text, target_scientific_name text,
  display_url text, fallback_image_url text, "position" integer,
  current_label public.review_label, current_comment text, current_version integer,
  reviewed_count bigint, total_count bigint, complete boolean
)
language sql volatile security invoker set search_path = pg_catalog
begin atomic
  select * from private.save_image_review_v2(
    p_item_id, p_label, p_comment, p_submission_id, p_client_version, p_expected_version
  );
end;

revoke all on function
  public.is_authorized_reviewer(), public.list_review_batches(),
  public.get_review_cursor(uuid, integer, text),
  public.save_image_review_v2(uuid, public.review_label, text, uuid, text, integer),
  private.is_authorized_reviewer(), private.list_review_batches(),
  private.get_review_cursor(uuid, integer, text),
  private.save_image_review_v2(uuid, public.review_label, text, uuid, text, integer)
  from public, anon, authenticated;

grant execute on function
  public.is_authorized_reviewer(), public.list_review_batches(),
  public.get_review_cursor(uuid, integer, text),
  public.save_image_review_v2(uuid, public.review_label, text, uuid, text, integer),
  private.is_authorized_reviewer(), private.list_review_batches(),
  private.get_review_cursor(uuid, integer, text),
  private.save_image_review_v2(uuid, public.review_label, text, uuid, text, integer)
  to authenticated, service_role;

-- Make the existing RPC-only/default-deny table boundary explicit. Restrictive
-- policies also prevent a future permissive browser policy from opening access.
create policy review_rpc_only on public.review_campaigns
  as restrictive for all to anon, authenticated using (false) with check (false);
create policy review_rpc_only on public.review_batches
  as restrictive for all to anon, authenticated using (false) with check (false);
create policy review_rpc_only on public.review_items
  as restrictive for all to anon, authenticated using (false) with check (false);
create policy review_rpc_only on public.image_reviews
  as restrictive for all to anon, authenticated using (false) with check (false);
create policy review_rpc_only on private.reviewer_profiles
  as restrictive for all to anon, authenticated using (false) with check (false);
create policy review_rpc_only on private.reviewer_allowlist
  as restrictive for all to anon, authenticated using (false) with check (false);

-- Hosted projects may install this event-trigger helper outside our migrations.
-- Keep its definition, owner and event trigger, but remove browser execution.
-- It need not exist in a clean local database or a non-hosted deployment.
do $$
begin
  if to_regprocedure('public.rls_auto_enable()') is not null then
    revoke all on function public.rls_auto_enable() from public, anon, authenticated;
  end if;
end;
$$;
