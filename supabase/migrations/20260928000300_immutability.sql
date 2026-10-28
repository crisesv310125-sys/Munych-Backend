-- `result_snapshots` y `audit_log` son de solo inserción.

create or replace function app.prevent_mutation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'La tabla app.% es de solo inserción', tg_table_name
    using errcode = 'P0001';
end;
$$;

create trigger result_snapshots_immutable
  before update or delete on app.result_snapshots
  for each row execute function app.prevent_mutation();

create trigger result_snapshots_no_truncate
  before truncate on app.result_snapshots
  for each statement execute function app.prevent_mutation();

create trigger audit_log_immutable
  before update or delete on app.audit_log
  for each row execute function app.prevent_mutation();

create trigger audit_log_no_truncate
  before truncate on app.audit_log
  for each statement execute function app.prevent_mutation();
