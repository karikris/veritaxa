-- The deployed 05e7dec client is the minimum supported version. Stale clients
-- must refresh; external clients must use get_review_cursor/save_image_review_v2.
-- Retire API definitions only: preserve all review data, provenance, labels,
-- client_version history, schema versions and previously applied migrations.
drop function public.get_review_queue(uuid, integer),
  public.submit_image_review(uuid, public.review_label, text, uuid, text)
  restrict;
