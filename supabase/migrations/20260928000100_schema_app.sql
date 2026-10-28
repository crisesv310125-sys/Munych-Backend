-- Esquema del dominio (`app`). No se expone en la Data API: todas las
-- lecturas y escrituras pasan por FastAPI.

create schema if not exists app;

create or replace function app.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- ---------------------------------------------------------------- organizaciones y roles

create table app.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create table app.user_roles (
  user_id uuid not null references auth.users (id) on delete cascade,
  organization_id uuid not null references app.organizations (id) on delete cascade,
  role text not null check (role in ('admin', 'judge')),
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  primary key (user_id, organization_id)
);

create table app.judges (
  user_id uuid primary key references auth.users (id) on delete cascade,
  organization_id uuid not null references app.organizations (id) on delete cascade,
  full_name text not null check (length(trim(full_name)) > 0),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

-- ---------------------------------------------------------------- eventos y comités

create table app.events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references app.organizations (id) on delete cascade,
  slug text not null unique check (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  name text not null,
  brand text not null check (brand in ('munych', 'grand_international')),
  logo_path text,
  venue text,
  country_code char(2) check (country_code ~ '^[A-Z]{2}$'),
  timezone text not null,
  starts_on date not null,
  ends_on date not null,
  status text not null default 'draft' check (status in ('draft', 'active', 'closed')),
  default_rubric_id uuid,
  -- Valores conservadores por defecto: participan menores.
  publication_settings jsonb not null default jsonb_build_object(
    'name_format', 'first_name_initial',
    'show_institution', true,
    'show_ranking', false,
    'show_scores', false,
    'indexable', false
  ),
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  constraint events_dates_check check (ends_on >= starts_on)
);

create table app.rubrics (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references app.events (id) on delete cascade,
  name text not null,
  scale_min smallint not null,
  scale_max smallint not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  constraint rubrics_scale_check check (scale_min < scale_max)
);

alter table app.events
  add constraint events_default_rubric_fk
  foreign key (default_rubric_id) references app.rubrics (id) on delete set null;

create table app.criteria (
  id uuid primary key default gen_random_uuid(),
  rubric_id uuid not null references app.rubrics (id) on delete cascade,
  name text not null,
  description text,
  weight numeric(5, 2) not null check (weight > 0),
  position integer not null,
  level_descriptors jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create table app.committees (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references app.events (id) on delete cascade,
  name text not null,
  acronym text not null,
  slug text not null check (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  type text not null
    check (type in ('general_assembly', 'security_council', 'crisis', 'specialized')),
  delegation_mode text not null check (delegation_mode in ('single', 'double')),
  sessions_count integer not null check (sessions_count between 1 and 20),
  rubric_id uuid references app.rubrics (id) on delete set null,
  award_quotas jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  unique (event_id, slug)
);

create table app.delegations (
  id uuid primary key default gen_random_uuid(),
  committee_id uuid not null references app.committees (id) on delete cascade,
  country_code char(2) check (country_code ~ '^[A-Z]{2}$'),
  character_name text,
  institution text,
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  constraint delegations_identity_check
    check ((country_code is null) <> (character_name is null)),
  unique (committee_id, country_code)
);

-- Minimización de datos (sección 9): del delegado solo nombre e institución.
create table app.delegates (
  id uuid primary key default gen_random_uuid(),
  delegation_id uuid not null references app.delegations (id) on delete cascade,
  full_name text not null check (length(trim(full_name)) > 0),
  institution text,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create table app.committee_judges (
  committee_id uuid not null references app.committees (id) on delete cascade,
  judge_id uuid not null references app.judges (user_id) on delete cascade,
  role text not null default 'judge' check (role in ('chair', 'moderator', 'judge')),
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  primary key (committee_id, judge_id)
);

-- ---------------------------------------------------------------- calificación

create table app.scoring_sessions (
  id uuid primary key default gen_random_uuid(),
  committee_id uuid not null references app.committees (id) on delete cascade,
  number integer not null check (number >= 1),
  status text not null default 'closed' check (status in ('open', 'closed')),
  opened_at timestamptz,
  closed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  unique (committee_id, number)
);

create table app.scores (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null unique,
  judge_id uuid not null references app.judges (user_id),
  delegate_id uuid not null references app.delegates (id) on delete cascade,
  session_id uuid not null references app.scoring_sessions (id) on delete cascade,
  criterion_id uuid not null references app.criteria (id),
  value smallint not null,
  comment text,
  client_updated_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  unique (judge_id, delegate_id, session_id, criterion_id)
);

-- ---------------------------------------------------------------- resultados

create table app.awards (
  id uuid primary key default gen_random_uuid(),
  committee_id uuid not null references app.committees (id) on delete cascade,
  award_type text not null check (
    award_type in ('best_delegate', 'outstanding_delegate', 'honorable_mention', 'verbal_commendation')
  ),
  delegation_id uuid not null references app.delegations (id) on delete cascade,
  position integer not null default 1 check (position >= 1),
  assigned_by uuid references auth.users (id) on delete set null,
  assigned_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  unique (committee_id, award_type, delegation_id)
);

-- Solo inserción (ver migración de inmutabilidad): sin updated_at.
create table app.result_snapshots (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references app.events (id),
  data jsonb not null,
  created_by uuid references auth.users (id) on delete set null,
  created_at timestamptz not null default now()
);

create table app.audit_log (
  id uuid primary key default gen_random_uuid(),
  actor_id uuid,
  entity text not null,
  entity_id uuid,
  action text not null,
  before jsonb,
  after jsonb,
  at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- índices

create index scores_session_delegate_idx on app.scores (session_id, delegate_id);
create index scores_judge_session_idx on app.scores (judge_id, session_id);
create index delegations_committee_idx on app.delegations (committee_id);
create index committee_judges_judge_idx on app.committee_judges (judge_id);
create index delegates_delegation_idx on app.delegates (delegation_id);
create index committees_event_idx on app.committees (event_id);
create index criteria_rubric_idx on app.criteria (rubric_id, position);
create index awards_committee_idx on app.awards (committee_id);
create index result_snapshots_event_idx on app.result_snapshots (event_id, created_at desc);
create index audit_log_entity_idx on app.audit_log (entity, entity_id);

-- ---------------------------------------------------------------- triggers updated_at

do $$
declare
  t text;
begin
  foreach t in array array[
    'organizations', 'user_roles', 'judges', 'events', 'rubrics', 'criteria', 'committees',
    'delegations', 'delegates', 'committee_judges', 'scoring_sessions', 'scores', 'awards'
  ]
  loop
    execute format(
      'create trigger set_updated_at before update on app.%I '
      'for each row execute function app.set_updated_at()',
      t
    );
  end loop;
end;
$$;
