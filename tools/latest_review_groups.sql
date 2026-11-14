-- Run in a transaction after setting veritaxa.round_code and veritaxa.target_name.
-- Copy queue memberships; retain every historical item and saved review unchanged.
do $publish$
declare
  round_code text := current_setting('veritaxa.round_code');
  target_name text := current_setting('veritaxa.target_name');
  group_row record;
  new_campaign_id uuid;
  new_batch_id uuid;
  saved_review_count bigint;
begin
  if round_code !~ '^[A-Z0-9][A-Z0-9-]{0,29}$' or length(target_name) not between 1 and 500 then
    raise exception 'Invalid round code or target name';
  end if;
  set local lock_timeout = '5s';
  lock table public.review_campaigns, public.review_batches,
    public.review_items, public.image_reviews in share row exclusive mode;
  if exists (select 1 from public.review_campaigns c
    where c.campaign_code like 'REREVIEW-' || round_code || '-%') then
    raise exception 'Round already exists; choose a new code';
  end if;
  select count(*) into saved_review_count from public.image_reviews;
  create temporary table latest_group_originals on commit drop as
    select 'item'::text kind, id, xmin::text version from public.review_items
    union all select 'review', id, xmin::text from public.image_reviews;

  create temporary table latest_group_votes on commit drop as
  select i.id original_item_id, i.source_provider, i.image_id, r.id review_id,
    r.updated_at, r.label::text label, to_jsonb(r) review_snapshot
  from public.image_reviews r
  join public.review_items i on i.id = r.item_id
  join public.review_batches b on b.id = i.batch_id
  join public.review_campaigns c on c.id = b.campaign_id
  where c.target_scientific_name = target_name;
  create index on latest_group_votes (source_provider, image_id);
  analyze latest_group_votes;

  if not exists (select 1 from latest_group_votes) then
    raise exception 'No saved reviews for this target';
  end if;

  create temporary table latest_group_members on commit drop as
  select chosen.*,
    case when chosen.label = 'target_scientific_name' then 'yes_target'
      when chosen.label in ('adult_butterfly', 'target_not_present') then 'no_target'
      else 'no_butterfly' end as category,
    (select jsonb_agg(v.review_snapshot order by v.updated_at, v.review_id)
      from latest_group_votes v where v.source_provider = chosen.source_provider
        and v.image_id = chosen.image_id) source_reviews
  from (
    select distinct on (source_provider, image_id) *
    from latest_group_votes
    order by source_provider, image_id, updated_at desc, review_id desc
  ) chosen;
  create unique index on latest_group_members (source_provider, image_id);
  if exists (select 1 from latest_group_members where label = 'flickr_keyword_match') then
    raise exception 'Latest keyword answers require explicit resolution before three-way grouping';
  end if;

  for group_row in select * from (values
    (1, 'yes_target', 'Yes — ' || target_name),
    (2, 'no_target', 'No — other butterfly'),
    (3, 'no_butterfly', 'No butterfly / other or unresolved')
  ) as groups(position, category, name) order by position loop
    insert into public.review_campaigns (
      campaign_code, internal_name, reviewer_name, target_scientific_name, status
    ) values (
      'REREVIEW-' || round_code || '-' || lpad(group_row.position::text, 3, '0'),
      'Latest saved review grouping: ' || group_row.category,
      'Round 2: ' || left(group_row.name, 111), target_name, 'open'
    ) returning id into new_campaign_id;
    insert into public.review_batches (
      campaign_id, batch_code, reviewer_name, position, status, opened_at
    ) values (
      new_campaign_id, 'RR-' || round_code || '-' || lpad(group_row.position::text, 3, '0'),
      'Round 2: ' || left(group_row.name, 111), group_row.position, 'open', now()
    ) returning id into new_batch_id;
    insert into public.review_items (
      batch_id, position, image_id, source_provider, source_record_id,
      display_url, image_url, source_page_url, flickr_search_term, source_labels, pipeline_metadata
    )
    select new_batch_id,
      row_number() over (order by md5(jsonb_build_array(m.source_provider,m.image_id)::text),
        m.source_provider,m.image_id)::integer,
      i.image_id,i.source_provider,i.source_record_id,i.display_url,i.image_url,
      i.source_page_url,i.flickr_search_term,i.source_labels,
      (coalesce(i.pipeline_metadata, '{}'::jsonb) - '_veritaxa_rereview') ||
      jsonb_build_object('_veritaxa_rereview', jsonb_build_object(
        'round_code', round_code, 'category', m.category,
        'grouping_rule', 'latest_updated_at_then_review_id_desc',
        'snapshot_at', transaction_timestamp(), 'original_item_id', m.original_item_id,
        'effective_review_id', m.review_id, 'effective_label', m.label,
        'source_reviews', m.source_reviews))
    from latest_group_members m join public.review_items i on i.id = m.original_item_id
    where m.category = group_row.category;
  end loop;

  if (select count(*) from public.review_items i
    join public.review_batches b on b.id=i.batch_id
    join public.review_campaigns c on c.id=b.campaign_id
    where c.campaign_code like 'REREVIEW-' || round_code || '-%')
    <> (select count(*) from latest_group_members) then
    raise exception 'New membership count differs from latest reviewed image inventory';
  end if;
  if saved_review_count <> (select count(*) from public.image_reviews) or exists (
    select 1 from latest_group_originals o left join (
      select 'item'::text kind,id,xmin::text version from public.review_items
      union all select 'review',id,xmin::text from public.image_reviews
    ) current_row using (kind,id) where o.version is distinct from current_row.version
  ) then
    raise exception 'Historical items or reviews changed';
  end if;

  -- Retire older round-two menus after successful publication; keep all their data.
  update public.review_batches b set status='archived',closed_at=now()
  from public.review_campaigns c where c.id=b.campaign_id
    and c.target_scientific_name=target_name and c.campaign_code like 'REREVIEW-%'
    and c.campaign_code not like 'REREVIEW-' || round_code || '-%'
    and b.status <> 'archived';
  update public.review_campaigns c set status='archived',updated_at=now()
  where c.target_scientific_name=target_name and c.campaign_code like 'REREVIEW-%'
    and c.campaign_code not like 'REREVIEW-' || round_code || '-%'
    and c.status <> 'archived';

  -- Completed first-round batches leave the active menu after their reviews are copied.
  -- Partially reviewed batches remain accessible, with team progress shown in the UI.
  update public.review_batches b set status='closed',closed_at=now()
  from public.review_campaigns c where c.id=b.campaign_id
    and c.target_scientific_name=target_name and b.status='open'
    and c.campaign_code not like 'REREVIEW-%'
    and exists(select 1 from public.review_items i where i.batch_id=b.id)
    and not exists(select 1 from public.review_items i where i.batch_id=b.id
      and not exists(select 1 from public.image_reviews r where r.item_id=i.id));
end;
$publish$;
