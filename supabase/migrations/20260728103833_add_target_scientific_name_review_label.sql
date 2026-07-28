alter type public.review_label
  add value if not exists 'target_scientific_name';
