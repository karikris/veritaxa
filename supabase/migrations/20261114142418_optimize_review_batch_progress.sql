-- Round detection must not read every image's potentially large private JSON
-- on each menu load. The partial index also preserves metadata-based detection
-- for custom campaign names; no reviewer-facing schema or grants change.
create index review_items_round_two_batch_idx
  on public.review_items (batch_id)
  where pipeline_metadata ? '_veritaxa_rereview';

create or replace function private.list_review_batches_v2()
returns table (
  batch_id uuid, reviewer_name text, batch_code text,
  reviewed_count bigint, total_count bigint, complete boolean,
  team_reviewed_count bigint, review_round integer
)
language plpgsql stable security definer set search_path = pg_catalog
as $$
declare
  requester uuid := auth.uid();
begin
  if not public.is_authorized_reviewer() then
    raise exception using errcode = '42501', message = 'Reviewer is not authorised';
  end if;
  return query
  select batch.id, batch.reviewer_name, batch.batch_code,
    progress.personal_count, progress.total_count,
    progress.total_count > 0 and progress.personal_count = progress.total_count,
    progress.team_count,
    case when exists (
      select 1 from public.review_items round_item
      where round_item.batch_id = batch.id
        and round_item.pipeline_metadata ? '_veritaxa_rereview'
    ) then 2 else 1 end
  from public.review_batches batch
  join public.review_campaigns campaign on campaign.id = batch.campaign_id
    and campaign.status = 'open'::public.campaign_status
  cross join lateral (
    select count(*) as total_count,
    count(*) filter (where exists (
      select 1 from public.image_reviews r
      where r.item_id = i.id and r.reviewer_id = requester
    )) as personal_count,
    count(*) filter (where exists (
      select 1 from public.image_reviews r where r.item_id = i.id
    )) as team_count
    from public.review_items i where i.batch_id = batch.id
  ) progress
  where batch.status = 'open'::public.batch_status
  order by (progress.team_count >= progress.total_count),
    case substring(upper(batch.batch_code) from '(?:^|-)([ABC])-[0-9]+(?:-|$)')
      when 'A' then 0 when 'B' then 1 when 'C' then 2 else 3
    end,
    batch.batch_code, batch.position, batch.id;
end;
$$;

notify pgrst, 'reload schema';
