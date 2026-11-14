-- A human confirms the stored BioCLIP species, separately from the campaign target.
alter type public.review_label add value if not exists 'model_scientific_name';
