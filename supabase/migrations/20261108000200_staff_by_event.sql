-- Staff: tipos de la organización, personas por evento (2026-11-08, segunda parte).
--
-- NO BORRA DATOS. Agrega columnas, rellena las nuevas con UPDATE y cambia una restricción
-- única por un índice único más amplio (eso no elimina filas).
--
-- 1. `staff_types.access`: cómo entra la gente de ese tipo.
--      account → cuenta con contraseña (correo de invitación) y califica en el panel del
--                juez, como Mesa Directiva (rol de mesa en su comité).
--      link    → sin cuenta: enlace personal / QR que llega por correo.
-- 2. `staff_members.event_id`: las personas se asignan por evento (desde la pantalla de
--    jueces del evento). Null = miembro anterior a este cambio, válido en todos los eventos.
-- 3. `staff_members.judge_id`: para tipos con cuenta, la cuenta (juez) de la persona.
-- 4. Una persona puede estar en el mismo tipo en varios eventos.

-- ---------------------------------------------------------------- 1. acceso por tipo

alter table app.staff_types
  add column access text not null default 'link' check (access in ('link', 'account'));

comment on column app.staff_types.access is
  'account: cuenta con contraseña y panel del juez (p. ej. Mesa Directiva); link: QR sin cuenta.';

update app.staff_types
   set access = 'account'
 where lower(name) = 'mesa directiva' and archived_at is null;

-- ---------------------------------------------------------------- 2-3. miembros por evento

alter table app.staff_members
  add column event_id uuid references app.events (id) on delete cascade,
  add column judge_id uuid references app.judges (user_id) on delete set null;

create index staff_members_event_idx on app.staff_members (event_id);

-- Los miembros que ya existen: al evento de su primer comité asignado…
update app.staff_members m
   set event_id = c.event_id
  from app.committees c
 where m.event_id is null
   and cardinality(m.committee_ids) > 0
   and c.id = m.committee_ids[1];

-- …y si no tienen comité, al único evento de su organización (si solo hay uno).
update app.staff_members m
   set event_id = only_event.id
  from app.staff_types t,
       lateral (
         select (array_agg(e.id))[1] as id, count(*) as n
           from app.events e
          where e.organization_id = t.organization_id
       ) only_event
 where m.event_id is null
   and t.id = m.staff_type_id
   and only_event.n = 1;

-- ---------------------------------------------------------------- 4. unicidad por evento

alter table app.staff_members drop constraint if exists staff_members_staff_type_id_person_id_key;

create unique index staff_members_type_person_event_idx
  on app.staff_members (
    staff_type_id, person_id,
    coalesce(event_id, '00000000-0000-0000-0000-000000000000'::uuid)
  );
