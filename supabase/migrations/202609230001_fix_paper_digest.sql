-- Supabase installs pgcrypto in the extensions schema. The original RPC used
-- an unqualified digest() call while its security-definer search_path was
-- intentionally restricted to public, so paper writes failed at runtime.

create or replace function public.replace_user_papers(target_user uuid, paper_rows jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  item jsonb;
begin
  if coalesce(auth.role(), '') <> 'service_role' then
    raise exception 'service role required';
  end if;

  delete from public.user_papers where user_id = target_user;
  for item in select value from jsonb_array_elements(coalesce(paper_rows, '[]'::jsonb))
  loop
    insert into public.user_papers (
      user_id,
      paper_id,
      payload,
      first_seen_at,
      last_seen_at,
      collection_dates,
      updated_at
    ) values (
      target_user,
      coalesce(nullif(item->>'id', ''), encode(extensions.digest(item::text, 'sha256'), 'hex')),
      item,
      nullif(item->>'first_seen_at', '')::timestamptz,
      nullif(item->>'last_seen_at', '')::timestamptz,
      array(select value::date from jsonb_array_elements_text(coalesce(item->'collection_dates', '[]'::jsonb))),
      now()
    );
  end loop;
end;
$$;

revoke all on function public.replace_user_papers(uuid, jsonb) from public, anon, authenticated;
grant execute on function public.replace_user_papers(uuid, jsonb) to service_role;
