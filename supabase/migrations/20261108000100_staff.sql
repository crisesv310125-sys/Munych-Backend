-- Gestión de staff (handoff «Gestión de staff», 2026-11-08).
--
-- SOLO AGREGA: tablas nuevas, índices, triggers y permisos. No borra ni modifica
-- datos existentes (el evento SD-MUN 2026 ya tiene datos reales).
--
-- El staff es de la ORGANIZACIÓN, no de un evento: los tipos de staff (Prensa, Mesa
-- Directiva…), sus personas, miembros, rúbricas y premios se definen una vez y sirven
-- para todos los eventos. Lo que es de cada evento son los candidatos (delegaciones o
-- delegados de sus comités), las evaluaciones (van por candidato), la asignación de los
-- premios y su confirmación.
--
-- Cada tipo:
--   · evalúa a un grupo de candidatos (delegaciones, delegados, escritos de posición o
--     delegados de prensa) de todos los comités o de algunos;
--   · tiene su propia rúbrica (criterios con pesos que suman 100) y su escala;
--   · entrega premios propios (el ranking de la rúbrica solo sugiere; el admin asigna);
--   · opcionalmente cuenta en el ranking general: en el peso Staff (`counts_as = 'staff'`)
--     o en el de Mesa Directiva (`counts_as = 'chair'`). Si varios tipos cuentan para el
--     mismo peso, se promedian entre sí.
-- Las personas del staff entran con un enlace personal (token guardado como hash, igual
-- que los accesos de los delegados): no necesitan cuenta ni rol en la organización.
-- Quitar a un miembro no borra sus evaluaciones (`removed_at`); el admin decide si cuentan.

-- ---------------------------------------------------------------- tipos de staff

create table app.staff_types (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references app.organizations (id) on delete cascade,
  name text not null check (length(btrim(name)) between 1 and 80),
  code text not null check (code ~ '^[A-Z0-9]{1,3}$'),
  color text not null default '#98A6B5' check (color ~ '^#[0-9A-Fa-f]{6}$'),
  description text check (description is null or length(description) <= 300),
  -- null: aún sin configurar.
  evaluates text check (evaluates in ('delegations', 'delegates', 'position_papers', 'press')),
  all_committees boolean not null default true,
  -- Con all_committees = false: comités (de cualquier evento de la organización) del alcance.
  committee_ids uuid[] not null default '{}',
  min_evaluators smallint not null default 2 check (min_evaluators between 1 and 20),
  counts_as text not null default 'none' check (counts_as in ('none', 'staff', 'chair')),
  -- Rúbrica propia: escala del evaluador y criterios [{id, name, description, weight}]
  -- en el orden en que los ve el evaluador.
  scale_min numeric(6, 2) not null default 0,
  scale_max numeric(6, 2) not null default 10,
  scale_step numeric(6, 2) not null default 0.5 check (scale_step > 0),
  criteria jsonb not null default '[]' check (jsonb_typeof(criteria) = 'array'),
  position integer not null default 0,
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  check (scale_max > scale_min)
);

create unique index staff_types_org_name_idx
  on app.staff_types (organization_id, lower(name)) where archived_at is null;
create index staff_types_org_idx on app.staff_types (organization_id);

comment on table app.staff_types is
  'Tipos de staff de la organización: a quién evalúan, su rúbrica y si cuentan en el ranking.';
comment on column app.staff_types.counts_as is
  'none: solo premios; staff: entra en el peso Staff; chair: entra en el peso Mesa Directiva.';

-- ---------------------------------------------------------------- personas del staff

create table app.staff_people (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references app.organizations (id) on delete cascade,
  full_name text not null check (length(btrim(full_name)) between 1 and 120),
  email text check (email is null or email ~ '^[^@\s]+@[^@\s]+$'),
  title text check (title is null or length(title) <= 160),
  -- Enlace personal: SHA-256 del token en hexadecimal (el token solo se muestra al generarlo).
  token_hash text unique check (token_hash is null or token_hash ~ '^[0-9a-f]{64}$'),
  token_issued_at timestamptz,
  token_expires_at timestamptz,
  last_used_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create unique index staff_people_org_email_idx
  on app.staff_people (organization_id, lower(email)) where email is not null;
create index staff_people_org_idx on app.staff_people (organization_id);

comment on table app.staff_people is
  'Personas del staff de la organización. Una persona puede estar en varios tipos de staff.';

-- ---------------------------------------------------------------- miembros (persona × tipo)

create table app.staff_members (
  id uuid primary key default gen_random_uuid(),
  staff_type_id uuid not null references app.staff_types (id) on delete cascade,
  person_id uuid not null references app.staff_people (id) on delete cascade,
  role text not null default 'evaluator' check (role in ('coordinator', 'evaluator')),
  -- Comités asignados; vacío = todos los del alcance del tipo.
  committee_ids uuid[] not null default '{}',
  removed_at timestamptz,
  -- Para exmiembros: si sus evaluaciones siguen contando.
  evaluations_count boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  unique (staff_type_id, person_id)
);

create index staff_members_person_idx on app.staff_members (person_id);

-- ---------------------------------------------------------------- evaluaciones

create table app.staff_evaluations (
  id uuid primary key default gen_random_uuid(),
  member_id uuid not null references app.staff_members (id) on delete cascade,
  -- Delegación o delegado (de un evento), según `staff_types.evaluates`.
  candidate_id uuid not null,
  -- {criterion_id: valor en la escala del tipo}
  "values" jsonb not null default '{}' check (jsonb_typeof("values") = 'object'),
  comment text check (comment is null or length(comment) <= 2000),
  client_updated_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  unique (member_id, candidate_id)
);

create index staff_evaluations_candidate_idx on app.staff_evaluations (candidate_id);

-- ---------------------------------------------------------------- premios propios

create table app.staff_awards (
  id uuid primary key default gen_random_uuid(),
  staff_type_id uuid not null references app.staff_types (id) on delete cascade,
  name text not null check (length(btrim(name)) between 1 and 80),
  winners smallint not null default 1 check (winners between 1 and 20),
  scope text not null default 'event' check (scope in ('event', 'per_committee')),
  tiebreak_criterion_id text,
  position integer not null default 0,
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create index staff_awards_type_idx on app.staff_awards (staff_type_id);

-- Quién ganó cada premio en cada evento.
create table app.staff_award_assignments (
  id uuid primary key default gen_random_uuid(),
  award_id uuid not null references app.staff_awards (id) on delete cascade,
  event_id uuid not null references app.events (id) on delete cascade,
  -- Solo en premios «por comité».
  committee_id uuid references app.committees (id) on delete cascade,
  position smallint not null check (position between 1 and 20),
  -- null: lugar sin asignar (se «desasigna» con un update, no se borra la fila).
  candidate_id uuid,
  suggested_candidate_id uuid,
  override_reason text check (override_reason is null or length(override_reason) <= 500),
  assigned_by uuid references auth.users (id) on delete set null,
  assigned_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create unique index staff_award_assignments_slot_idx
  on app.staff_award_assignments (
    award_id, event_id,
    coalesce(committee_id, '00000000-0000-0000-0000-000000000000'::uuid), position
  );

-- «Confirmar premios» de un tipo de staff en un evento (null = abiertos).
create table app.staff_award_confirmations (
  staff_type_id uuid not null references app.staff_types (id) on delete cascade,
  event_id uuid not null references app.events (id) on delete cascade,
  confirmed_at timestamptz,
  confirmed_by uuid references auth.users (id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  primary key (staff_type_id, event_id)
);

-- ---------------------------------------------------------------- triggers y seguridad

create trigger set_updated_at before update on app.staff_types
  for each row execute function app.set_updated_at();
create trigger set_updated_at before update on app.staff_people
  for each row execute function app.set_updated_at();
create trigger set_updated_at before update on app.staff_members
  for each row execute function app.set_updated_at();
create trigger set_updated_at before update on app.staff_evaluations
  for each row execute function app.set_updated_at();
create trigger set_updated_at before update on app.staff_awards
  for each row execute function app.set_updated_at();
create trigger set_updated_at before update on app.staff_award_assignments
  for each row execute function app.set_updated_at();
create trigger set_updated_at before update on app.staff_award_confirmations
  for each row execute function app.set_updated_at();

-- Solo el backend (service role) lee y escribe estas tablas.
revoke all on app.staff_types, app.staff_people, app.staff_members, app.staff_evaluations,
  app.staff_awards, app.staff_award_assignments, app.staff_award_confirmations
  from public, anon, authenticated;
alter table app.staff_types enable row level security;
alter table app.staff_people enable row level security;
alter table app.staff_members enable row level security;
alter table app.staff_evaluations enable row level security;
alter table app.staff_awards enable row level security;
alter table app.staff_award_assignments enable row level security;
alter table app.staff_award_confirmations enable row level security;
