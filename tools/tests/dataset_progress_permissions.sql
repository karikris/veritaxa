-- Run after the latest-review fixture/assertions, inside the same rollback transaction.
select set_config('request.jwt.claims',current_setting('veritaxa.test_claims'),true);
set local role authenticated;
do $test$
begin
  if (select team_reviewed_count from public.list_review_batches_v2()
    where batch_id=current_setting('veritaxa.test_batch')::uuid) <> 1 then
    raise exception 'Authenticated count API failed';
  end if;
  if not (select reviewed_by_anyone from public.get_review_cursor_v2(
    current_setting('veritaxa.test_batch')::uuid,null,'resume')) then
    raise exception 'Authenticated cursor API failed';
  end if;
end;
$test$;
reset role;
do $test$
begin
  if has_function_privilege('anon','public.list_review_batches_v2()','execute')
    or has_function_privilege('anon','public.get_review_cursor_v2(uuid,integer,text)','execute')
    or has_function_privilege('anon','public.save_image_review_v3(uuid,public.review_label,text,uuid,text,integer)','execute') then
    raise exception 'Anonymous API access was granted';
  end if;
end;
$test$;
