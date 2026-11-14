-- Cached generic plans regressed this parameterized count query from about
-- 80 ms to 3 s after the live menu grew to thirteen datasets. Plan for the
-- current reviewer and dataset inventory on each call; scope the setting to
-- this function so unrelated database workloads retain their existing policy.
alter function private.list_review_batches_v2()
  set plan_cache_mode = force_custom_plan;

notify pgrst, 'reload schema';
