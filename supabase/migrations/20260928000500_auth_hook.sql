-- Custom Access Token Hook: añade el claim `app_role` a partir de `app.user_roles`.
-- Nunca se usa `user_metadata` para roles (el usuario puede editarlo).
-- Un juez desactivado (`app.judges.active = false`) no recibe el rol `judge`.

create or replace function public.custom_access_token_hook(event jsonb)
returns jsonb
language plpgsql
stable
set search_path = ''
as $$
declare
  claims jsonb;
  user_role text;
begin
  select ur.role
    into user_role
    from app.user_roles ur
   where ur.user_id = (event ->> 'user_id')::uuid
     and (
       ur.role = 'admin'
       or exists (
         select 1 from app.judges j where j.user_id = ur.user_id and j.active
       )
     )
   order by case ur.role when 'admin' then 0 else 1 end
   limit 1;

  claims := coalesce(event -> 'claims', '{}'::jsonb);

  if user_role is null then
    claims := claims - 'app_role';
  else
    claims := jsonb_set(claims, '{app_role}', to_jsonb(user_role));
  end if;

  return jsonb_set(event, '{claims}', claims);
end;
$$;

grant usage on schema app to supabase_auth_admin;
grant select on app.user_roles, app.judges to supabase_auth_admin;
grant execute on function public.custom_access_token_hook(jsonb) to supabase_auth_admin;
revoke execute on function public.custom_access_token_hook(jsonb) from public, anon, authenticated;

create policy user_roles_select_auth_admin
  on app.user_roles
  for select
  to supabase_auth_admin
  using (true);

create policy judges_select_auth_admin
  on app.judges
  for select
  to supabase_auth_admin
  using (true);
