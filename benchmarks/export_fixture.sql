-- Disposable synthetic database only. This reproduces export column/index types,
-- not Supabase Auth or security policies (which have their own pgTAP suite).
create table public.review_campaigns (
  id bigint primary key,
  campaign_code text unique not null,
  target_scientific_name text
);
create table public.review_batches (
  id bigint primary key,
  campaign_id bigint not null references public.review_campaigns,
  batch_code text unique not null,
  position integer not null,
  unique (campaign_id, position)
);
create table public.review_items (
  id bigint primary key,
  batch_id bigint not null references public.review_batches,
  position integer not null,
  image_id text not null,
  source_provider text not null,
  source_record_id text,
  image_url text not null,
  display_url text,
  flickr_search_term text,
  source_labels jsonb,
  pipeline_metadata jsonb not null,
  unique (batch_id, position),
  unique (batch_id, image_id)
);
create table public.image_reviews (
  id bigint primary key,
  item_id bigint not null references public.review_items,
  reviewer_id uuid not null,
  label text not null,
  comment text,
  "flickrKeyword" text,
  "scientificName" text,
  "identifiedBy" text,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  client_version text not null,
  unique (item_id, reviewer_id)
);
