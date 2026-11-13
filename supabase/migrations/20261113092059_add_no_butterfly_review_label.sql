-- Distinguish absence of any butterfly from absence of the campaign target.
alter type public.review_label
  add value if not exists 'no_butterfly';
