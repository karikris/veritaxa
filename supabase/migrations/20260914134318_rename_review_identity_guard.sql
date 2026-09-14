-- Reviews have supported versioned corrections since the editable-review
-- migration. Rename the guard without replacing its function or changing data,
-- trigger events, grants, or historical migrations.
alter trigger image_reviews_append_only on public.image_reviews
  rename to image_reviews_preserve_identity;
