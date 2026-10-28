-- Única tabla del esquema `public`: resultados publicados que lee el sitio público.
-- Su contenido lo genera solo `build_public_view` en el backend.

create table public.public_results (
  event_slug text primary key,
  event_id uuid not null unique references app.events (id) on delete cascade,
  published boolean not null default false,
  version integer not null default 0 check (version >= 0),
  data jsonb not null,
  published_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create trigger set_updated_at before update on public.public_results
  for each row execute function app.set_updated_at();

alter table public.public_results enable row level security;

revoke all on public.public_results from public, anon, authenticated;
grant select on public.public_results to anon, authenticated;
grant all on public.public_results to service_role;

create policy public_results_select_published
  on public.public_results
  for select
  to anon, authenticated
  using (published);
