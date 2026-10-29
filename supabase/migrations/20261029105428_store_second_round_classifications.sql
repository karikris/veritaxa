-- Original first-round rows remain unchanged. Re-review copies have their own
-- per-reviewer rows; label remains the cursor API's current-answer field.
alter table public.image_reviews
  add column second_round_label public.review_label;

comment on column public.image_reviews.second_round_label is
  'Second-round classification on re-review copies, using the same review_label options. First-round rows remain null; label is retained for existing review APIs.';

create function private.capture_second_round_label()
returns trigger
language plpgsql security invoker set search_path = pg_catalog
as $$
begin
  select case when item.pipeline_metadata ? '_veritaxa_rereview'
    then new.label else null end
  into new.second_round_label
  from public.review_items item where item.id = new.item_id;
  return new;
end;
$$;

revoke all on function private.capture_second_round_label()
  from public, anon, authenticated;

create trigger image_reviews_capture_second_round
  before insert or update on public.image_reviews
  for each row execute function private.capture_second_round_label();

-- Support installations where re-review answers were saved before this column.
-- Preserve the answer and identity while following correction-version guards.
update public.image_reviews review
set second_round_label = review.label, version = review.version + 1,
  updated_at = greatest(clock_timestamp(), review.updated_at + interval '1 microsecond')
from public.review_items item
where item.id = review.item_id
  and item.pipeline_metadata ? '_veritaxa_rereview'
  and review.second_round_label is null;

alter table public.image_reviews add constraint image_reviews_second_round_matches_label
  check (second_round_label is null or second_round_label = label);
