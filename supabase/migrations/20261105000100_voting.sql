-- Votación por roles (spec «Tipos de evento y votación de delegados», 2026-11-05).
--
-- 1. Tipos de evento definitivos (mensaje de Héctor del 2026-11-05):
--      judges_only            solo jueces (el flujo de siempre)
--      mun_regular            mesa 30 % · delegados 50 % · staff 20 % (sin jueces)
--      national_championship  jueces 50 % · mesa 15 % · delegados 25 % · staff 10 %
--    Los pesos viven en el backend (munych_api.shared.kernel.catalog.EVENT_TYPES).
--    El tipo provisional `voting` se convierte en `mun_regular`.
-- 2. Rol `staff` en committee_judges (la mesa ya existía: chair y moderator).
-- 3. Accesos de los delegados sin cuenta: un token por delegado, guardado como hash.
-- 4. Votos de los delegados: por delegación votada, sesión y criterio.

-- ---------------------------------------------------------------- 1. tipos de evento

alter table app.events drop constraint if exists events_event_type_check;

update app.events set event_type = 'mun_regular' where event_type = 'voting';

alter table app.events
  add constraint events_event_type_check
    check (event_type in ('judges_only', 'mun_regular', 'national_championship'));

comment on column app.events.event_type is
  'Tipo de evento: judges_only, mun_regular o national_championship. '
  'Los roles que votan y su peso se configuran en el backend.';

-- ---------------------------------------------------------------- 2. rol staff

alter table app.committee_judges drop constraint if exists committee_judges_role_check;

alter table app.committee_judges
  add constraint committee_judges_role_check
    check (role in ('chair', 'moderator', 'judge', 'staff'));

-- ---------------------------------------------------------------- 3. accesos de delegados

create table app.voter_tokens (
  id uuid primary key default gen_random_uuid(),
  delegate_id uuid not null references app.delegates (id) on delete cascade,
  event_id uuid not null references app.events (id) on delete cascade,
  -- SHA-256 del token en hexadecimal: el token en claro solo se muestra al generarlo.
  token_hash text not null unique check (token_hash ~ '^[0-9a-f]{64}$'),
  expires_at timestamptz not null,
  revoked_at timestamptz,
  last_used_at timestamptz,
  created_by uuid references auth.users (id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

-- Un solo token vigente (no revocado) por delegado.
create unique index voter_tokens_active_delegate_idx
  on app.voter_tokens (delegate_id) where revoked_at is null;
create index voter_tokens_event_idx on app.voter_tokens (event_id);

-- ---------------------------------------------------------------- 4. votos de delegados

create table app.delegate_votes (
  id uuid primary key default gen_random_uuid(),
  voter_delegate_id uuid not null references app.delegates (id) on delete cascade,
  delegation_id uuid not null references app.delegations (id) on delete cascade,
  session_id uuid not null references app.scoring_sessions (id) on delete cascade,
  criterion_id uuid not null references app.criteria (id),
  value smallint not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  -- Un voto por votante, delegación, sesión y criterio: sin votos dobles,
  -- ni desde otro dispositivo.
  unique (voter_delegate_id, delegation_id, session_id, criterion_id)
);

create index delegate_votes_session_delegation_idx
  on app.delegate_votes (session_id, delegation_id);

-- Defensa en profundidad (el backend ya lo valida): nadie vota por su propia
-- delegación ni por una de otro comité.
create or replace function app.check_delegate_vote()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  voter_delegation uuid;
  voter_committee uuid;
  voted_committee uuid;
  session_committee uuid;
begin
  select d.delegation_id, dl.committee_id
    into voter_delegation, voter_committee
    from app.delegates d
    join app.delegations dl on dl.id = d.delegation_id
   where d.id = new.voter_delegate_id;

  if voter_delegation = new.delegation_id then
    raise exception 'Un delegado no puede votar por su propia delegación';
  end if;

  select committee_id into voted_committee from app.delegations where id = new.delegation_id;
  select committee_id into session_committee from app.scoring_sessions where id = new.session_id;

  if voted_committee is distinct from voter_committee
     or session_committee is distinct from voter_committee then
    raise exception 'El voto debe ser para una delegación y una sesión del comité del votante';
  end if;

  return new;
end;
$$;

create trigger check_delegate_vote before insert or update on app.delegate_votes
  for each row execute function app.check_delegate_vote();

-- ---------------------------------------------------------------- triggers y seguridad

create trigger set_updated_at before update on app.voter_tokens
  for each row execute function app.set_updated_at();
create trigger set_updated_at before update on app.delegate_votes
  for each row execute function app.set_updated_at();

revoke all on app.voter_tokens, app.delegate_votes from public, anon, authenticated;
revoke all on function app.check_delegate_vote() from public, anon, authenticated;
alter table app.voter_tokens enable row level security;
alter table app.delegate_votes enable row level security;
