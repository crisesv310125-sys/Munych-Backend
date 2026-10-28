-- Defensa en profundidad: el esquema `app` no se expone en la Data API y,
-- aun así, `anon` y `authenticated` no tienen privilegios ni políticas.
-- El backend conecta como `postgres` (propietario), al que no afecta RLS.

revoke all on schema app from public, anon, authenticated;
revoke all on all tables in schema app from public, anon, authenticated;
revoke all on all sequences in schema app from public, anon, authenticated;
revoke all on all functions in schema app from public, anon, authenticated;

alter default privileges in schema app revoke all on tables from public, anon, authenticated;
alter default privileges in schema app revoke all on sequences from public, anon, authenticated;
alter default privileges in schema app revoke all on functions from public, anon, authenticated;

do $$
declare
  t record;
begin
  for t in select tablename from pg_tables where schemaname = 'app'
  loop
    execute format('alter table app.%I enable row level security', t.tablename);
  end loop;
end;
$$;
