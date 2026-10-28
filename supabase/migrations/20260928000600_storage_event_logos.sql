-- Bucket público de logos de eventos. Solo el backend escribe (con la clave
-- service_role): no se crean políticas de escritura para anon/authenticated.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'event-logos',
  'event-logos',
  true,
  2097152,
  array['image/png', 'image/svg+xml', 'image/webp']
)
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;
