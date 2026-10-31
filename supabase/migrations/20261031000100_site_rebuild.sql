-- Reconstrucción agrupada del sitio público (Cloudflare Pages, export estático).
--
-- El sitio lee public_results solo durante el build, así que cada publicación necesita
-- un build nuevo. Para no lanzar uno por cada comité publicado en la clausura:
--   1. Un trigger en public_results marca que hay cambios pendientes (en la misma transacción).
--   2. pg_cron ejecuta app.dispatch_site_rebuild() cada 30 s. Llama al deploy hook cuando
--      lleva 45 s sin cambios, o cuando hay cambios pendientes desde hace 5 min aunque sigan
--      llegando (para que una ráfaga larga no retrase el sitio indefinidamente).
-- La URL del hook vive en Vault con el nombre 'pages_deploy_hook_url'. Sin ella no se llama
-- a nada y los cambios siguen pendientes hasta que se configure.

create extension if not exists pg_net with schema extensions;
create extension if not exists pg_cron;

create table app.site_rebuild (
  id boolean primary key default true check (id),
  -- Primer cambio todavía sin build; null si no hay nada pendiente.
  pending_since timestamptz,
  last_change_at timestamptz,
  last_triggered_at timestamptz,
  -- Id de la petición en net._http_response, para revisar la respuesta de Cloudflare.
  last_request_id bigint
);

insert into app.site_rebuild default values;

revoke all on app.site_rebuild from public, anon, authenticated;
alter table app.site_rebuild enable row level security;

create function app.request_site_rebuild()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  update app.site_rebuild
     set last_change_at = now(),
         pending_since = coalesce(pending_since, now());
  return null;
end;
$$;

create trigger request_site_rebuild
  after insert or update or delete on public.public_results
  for each row execute function app.request_site_rebuild();

create function app.site_rebuild_configured()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from vault.decrypted_secrets
    where name = 'pages_deploy_hook_url' and coalesce(decrypted_secret, '') <> ''
  );
$$;

create function app.dispatch_site_rebuild(
  quiet interval default interval '45 seconds',
  max_wait interval default interval '5 minutes'
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  state app.site_rebuild;
  hook_url text;
begin
  -- skip locked: si una publicación tiene la fila bloqueada, se revisa en la siguiente vuelta.
  select * into state from app.site_rebuild for update skip locked;
  if not found or state.pending_since is null then
    return false;
  end if;
  if state.last_change_at > now() - quiet and state.pending_since > now() - max_wait then
    return false;
  end if;

  select decrypted_secret into hook_url
    from vault.decrypted_secrets
   where name = 'pages_deploy_hook_url';
  if coalesce(hook_url, '') = '' then
    return false;
  end if;

  update app.site_rebuild
     set pending_since = null,
         last_triggered_at = now(),
         last_request_id = net.http_post(url := hook_url, body := '{}'::jsonb);
  return true;
end;
$$;

revoke all on function app.request_site_rebuild() from public, anon, authenticated;
revoke all on function app.site_rebuild_configured() from public, anon, authenticated;
revoke all on function app.dispatch_site_rebuild(interval, interval) from public, anon, authenticated;

select cron.schedule('site-rebuild', '30 seconds', 'select app.dispatch_site_rebuild()');
