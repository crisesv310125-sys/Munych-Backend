-- Voto de los delegados por premios (handoff «Votación de delegados», 2026-11-06).
--
-- Los delegados ya no califican con la rúbrica. Votan una sola vez por comité, al
-- final de las sesiones, eligiendo tres delegaciones distintas (ninguna la suya):
--   best_delegate         Mejor delegado         3 puntos
--   outstanding_delegate  Delegado distinguido   2 puntos
--   honorable_mention     Mención de honor       1 punto
-- Nota del rol «delegados» = puntos recibidos / (3 × votantes del comité) × 100.
-- Los puntos y el cálculo viven en el backend (scoring_engine.peer_awards).
--
-- 1. Ventana de votación por comité (la abre y la cierra el admin).
-- 2. Se elimina `app.delegate_votes` (votos por criterio de rúbrica).
-- 3. Tabla `app.peer_votes`: un voto por premio y votante; no se puede modificar.

-- ---------------------------------------------------------------- 1. ventana de votación

alter table app.committees
  add column peer_vote_opens_at timestamptz,
  add column peer_vote_closes_at timestamptz,
  add constraint committees_peer_vote_window_check
    check (peer_vote_closes_at is null
           or (peer_vote_opens_at is not null and peer_vote_closes_at > peer_vote_opens_at));

comment on column app.committees.peer_vote_opens_at is
  'Apertura del voto entre pares del comité. null: aún no se programa.';
comment on column app.committees.peer_vote_closes_at is
  'Cierre del voto entre pares. null: abierto hasta que el admin lo cierre.';

-- ---------------------------------------------------------------- 2. adiós a los votos por rúbrica

drop table if exists app.delegate_votes;
drop function if exists app.check_delegate_vote();

-- ---------------------------------------------------------------- 3. votos por premio

create table app.peer_votes (
  id uuid primary key default gen_random_uuid(),
  voter_delegate_id uuid not null references app.delegates (id) on delete cascade,
  committee_id uuid not null references app.committees (id) on delete cascade,
  award_type text not null
    check (award_type in ('best_delegate', 'outstanding_delegate', 'honorable_mention')),
  delegation_id uuid not null references app.delegations (id) on delete cascade,
  created_at timestamptz not null default now(),
  -- Un premio por votante, y una delegación no puede recibir dos premios del mismo votante.
  unique (voter_delegate_id, award_type),
  unique (voter_delegate_id, delegation_id)
);

create index peer_votes_committee_delegation_idx
  on app.peer_votes (committee_id, delegation_id);

-- Defensa en profundidad (el backend ya lo valida): nadie vota por su propia
-- delegación ni fuera de su comité.
create or replace function app.check_peer_vote()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  voter_delegation uuid;
  voter_committee uuid;
  voted_committee uuid;
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

  if voted_committee is distinct from voter_committee
     or new.committee_id is distinct from voter_committee then
    raise exception 'El voto debe ser para una delegación del comité del votante';
  end if;

  return new;
end;
$$;

create trigger check_peer_vote before insert on app.peer_votes
  for each row execute function app.check_peer_vote();

-- Una vez enviado, el voto no cambia (sí se borra en cascada si se elimina la delegación).
create trigger peer_votes_immutable before update on app.peer_votes
  for each row execute function app.prevent_mutation();

revoke all on app.peer_votes from public, anon, authenticated;
revoke all on function app.check_peer_vote() from public, anon, authenticated;
alter table app.peer_votes enable row level security;
