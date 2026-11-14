-- Reuse the standard fixture/publication/assertions, then run this setup,
-- rerun latest_review_groups.sql and execute the checks below inside a rollback.
do $setup$
begin
  perform set_config('veritaxa.other_model_campaigns',current_setting('veritaxa.source_campaigns'),true);
  perform set_config('veritaxa.append_existing','true',true);
end;
$setup$;
