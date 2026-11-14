-- Only the requested model name and cosine are exposed. Full source metadata stays private.
create function private.review_model_prediction(p_item_id uuid)
returns table(scientific_name text, cosine double precision)
language plpgsql stable security invoker set search_path=pg_catalog
as $$
declare metadata jsonb; name text; score text; value double precision;
begin
  select i.pipeline_metadata into metadata from public.review_items i where i.id=p_item_id;
  if metadata#>>'{bioclip,attestation,model}' is distinct from 'imageomics/bioclip-2.5-vith14' then return; end if;
  name := coalesce(metadata#>>'{bioclip,top10,0,scientific_name}',metadata#>>'{bioclip,top5,0,scientific_name}');
  score := coalesce(metadata#>>'{bioclip,top10,0,cosine}',metadata#>>'{bioclip,top5,0,cosine}');
  if name is null or length(name) not between 1 and 500 or btrim(name)<>name or score is null then return; end if;
  begin value:=score::double precision; exception when invalid_text_representation or numeric_value_out_of_range then return; end;
  if value not between -1 and 1 then return; end if;
  return query select name,value;
end;
$$;
revoke all on function private.review_model_prediction(uuid) from public,anon,authenticated;
alter table public.image_reviews drop constraint image_reviews_scientific_name_valid;
alter table public.image_reviews add constraint image_reviews_scientific_name_valid check (
 (label in ('target_scientific_name','model_scientific_name') and "scientificName" is not null
 and "scientificName"=btrim("scientificName") and length("scientificName") between 1 and 500)
 or (label not in ('target_scientific_name','model_scientific_name') and "scientificName" is null)
);

CREATE OR REPLACE FUNCTION private.save_image_review_v2(p_item_id uuid, p_label public.review_label, p_comment text, p_submission_id uuid, p_client_version text, p_expected_version integer)
 RETURNS TABLE(item_id uuid, image_id text, target_scientific_name text, display_url text, fallback_image_url text, "position" integer, current_label public.review_label, current_comment text, current_version integer, reviewed_count bigint, total_count bigint, complete boolean)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog'
AS $function$
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
    when p_label = 'model_scientific_name'::public.review_label
      then (select prediction.scientific_name from private.review_model_prediction(p_item_id) prediction)
    else null
  end;
  if p_label = 'model_scientific_name'::public.review_label and expected_scientific_name is null then
    raise exception using errcode='22023', message='No valid model prediction is available';
  end if;

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
$function$;


create function private.get_review_cursor_v3(p_batch_id uuid,p_anchor_position integer,p_direction text) returns table(item_id uuid, image_id text, target_scientific_name text, display_url text, fallback_image_url text,
"position" integer, current_label public.review_label, current_comment text, current_version integer,
reviewed_count bigint, total_count bigint, complete boolean, team_reviewed_count bigint, reviewed_by_anyone boolean,
model_scientific_name text, model_cosine double precision)
 language plpgsql volatile security definer set search_path=pg_catalog as $$
 declare cursor_row record;
 begin
   select * into cursor_row from private.get_review_cursor_v2(p_batch_id,p_anchor_position,p_direction);
   if cursor_row.item_id is null then return; end if;
   return query select cursor_row.item_id,cursor_row.image_id,cursor_row.target_scientific_name,
    cursor_row.display_url,cursor_row.fallback_image_url,cursor_row.position,cursor_row.current_label,
    cursor_row.current_comment,cursor_row.current_version,cursor_row.reviewed_count,cursor_row.total_count,
    cursor_row.complete,cursor_row.team_reviewed_count,cursor_row.reviewed_by_anyone,
    p.scientific_name,p.cosine from (select 1) singleton
    left join lateral private.review_model_prediction(cursor_row.item_id) p on true;
 end; $$;
 create function public.get_review_cursor_v3(p_batch_id uuid,p_anchor_position integer,p_direction text) returns table(item_id uuid, image_id text, target_scientific_name text, display_url text, fallback_image_url text,
"position" integer, current_label public.review_label, current_comment text, current_version integer,
reviewed_count bigint, total_count bigint, complete boolean, team_reviewed_count bigint, reviewed_by_anyone boolean,
model_scientific_name text, model_cosine double precision)
 language sql volatile security invoker set search_path=pg_catalog
 begin atomic select * from private.get_review_cursor_v3(p_batch_id,p_anchor_position,p_direction); end;
revoke all on function private.get_review_cursor_v3(uuid,integer,text),public.get_review_cursor_v3(uuid,integer,text) from public,anon,authenticated;
 grant execute on function private.get_review_cursor_v3(uuid,integer,text),public.get_review_cursor_v3(uuid,integer,text) to authenticated,service_role;

create function private.save_image_review_v4(p_item_id uuid,p_label public.review_label,p_comment text,p_submission_id uuid,p_client_version text,p_expected_version integer) returns table(item_id uuid, image_id text, target_scientific_name text, display_url text, fallback_image_url text,
"position" integer, current_label public.review_label, current_comment text, current_version integer,
reviewed_count bigint, total_count bigint, complete boolean, team_reviewed_count bigint, reviewed_by_anyone boolean,
model_scientific_name text, model_cosine double precision)
 language plpgsql volatile security definer set search_path=pg_catalog as $$
 declare cursor_row record;
 begin
   select * into cursor_row from private.save_image_review_v3(p_item_id,p_label,p_comment,p_submission_id,p_client_version,p_expected_version);
   if cursor_row.item_id is null then return; end if;
   return query select cursor_row.item_id,cursor_row.image_id,cursor_row.target_scientific_name,
    cursor_row.display_url,cursor_row.fallback_image_url,cursor_row.position,cursor_row.current_label,
    cursor_row.current_comment,cursor_row.current_version,cursor_row.reviewed_count,cursor_row.total_count,
    cursor_row.complete,cursor_row.team_reviewed_count,cursor_row.reviewed_by_anyone,
    p.scientific_name,p.cosine from (select 1) singleton
    left join lateral private.review_model_prediction(cursor_row.item_id) p on true;
 end; $$;
 create function public.save_image_review_v4(p_item_id uuid,p_label public.review_label,p_comment text,p_submission_id uuid,p_client_version text,p_expected_version integer) returns table(item_id uuid, image_id text, target_scientific_name text, display_url text, fallback_image_url text,
"position" integer, current_label public.review_label, current_comment text, current_version integer,
reviewed_count bigint, total_count bigint, complete boolean, team_reviewed_count bigint, reviewed_by_anyone boolean,
model_scientific_name text, model_cosine double precision)
 language sql volatile security invoker set search_path=pg_catalog
 begin atomic select * from private.save_image_review_v4(p_item_id,p_label,p_comment,p_submission_id,p_client_version,p_expected_version); end;
revoke all on function private.save_image_review_v4(uuid,public.review_label,text,uuid,text,integer),public.save_image_review_v4(uuid,public.review_label,text,uuid,text,integer) from public,anon,authenticated;
 grant execute on function private.save_image_review_v4(uuid,public.review_label,text,uuid,text,integer),public.save_image_review_v4(uuid,public.review_label,text,uuid,text,integer) to authenticated,service_role;

notify pgrst, 'reload schema';
