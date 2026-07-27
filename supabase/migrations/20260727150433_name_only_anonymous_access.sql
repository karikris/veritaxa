drop index private.reviewer_profiles_email_lower_key;

alter table private.reviewer_profiles
  alter column email drop not null;

create unique index reviewer_profiles_email_lower_key
  on private.reviewer_profiles (lower(email))
  where email is not null;

create or replace function private.create_reviewer_profile()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog
as $$
declare
  requested_name text := nullif(btrim(new.raw_user_meta_data ->> 'identified_by'), '');
  profile_name text;
begin
  profile_name := case
    when requested_name is not null and char_length(requested_name) <= 100
      then requested_name
    else coalesce(
      nullif(left(split_part(coalesce(new.email, ''), '@', 1), 100), ''),
      'Reviewer'
    )
  end;

  insert into private.reviewer_profiles (user_id, email, identified_by)
  values (new.id, new.email, profile_name)
  on conflict (user_id) do update
  set email = excluded.email;

  return new;
end;
$$;

revoke all on function private.create_reviewer_profile()
  from public, anon, authenticated;
