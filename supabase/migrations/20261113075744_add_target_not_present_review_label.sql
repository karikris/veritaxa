-- A negative target answer makes no claim about other species or biological content.
-- Existing save RPCs retain the campaign context and store scientificName only for Yes.
alter type public.review_label
  add value if not exists 'target_not_present';
