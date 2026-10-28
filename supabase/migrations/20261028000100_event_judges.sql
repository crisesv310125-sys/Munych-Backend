-- Jueces por evento. Un juez (cuenta de Auth) pertenece a la organización y
-- puede participar en varios eventos; esta tabla dice en cuáles.

create table app.event_judges (
  event_id uuid not null references app.events (id) on delete cascade,
  judge_id uuid not null references app.judges (user_id) on delete cascade,
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  primary key (event_id, judge_id)
);

create index event_judges_judge_idx on app.event_judges (judge_id);

create trigger set_updated_at before update on app.event_judges
  for each row execute function app.set_updated_at();

revoke all on app.event_judges from public, anon, authenticated;
alter table app.event_judges enable row level security;

-- Backfill 1: jueces ya asignados a algún comité pertenecen a ese evento.
insert into app.event_judges (event_id, judge_id)
select distinct c.event_id, cj.judge_id
from app.committee_judges cj
join app.committees c on c.id = cj.committee_id
on conflict do nothing;

-- Backfill 2: jueces sin comité se vinculan al evento más reciente de su
-- organización creado antes que el juez (o, si no hay, al primero).
insert into app.event_judges (event_id, judge_id)
select ev.id, j.user_id
from app.judges j
cross join lateral (
  select e.id
  from app.events e
  where e.organization_id = j.organization_id
  order by (e.created_at <= j.created_at) desc,
           case when e.created_at <= j.created_at then e.created_at end desc nulls last,
           e.created_at asc
  limit 1
) ev
where not exists (select 1 from app.event_judges ej where ej.judge_id = j.user_id)
on conflict do nothing;
