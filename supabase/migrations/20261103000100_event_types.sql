-- Tipos de evento (spec «Tipos de evento y votación de delegados», 2026-11-03).
--
-- judges_only: el flujo actual (solo califican los jueces).
-- voting:      votan delegados, staff y jueces.
--
-- Qué roles votan en cada tipo (y su peso) se configura en el backend
-- (munych_api.shared.kernel.catalog.EVENT_TYPES); aquí solo se restringe el valor.
-- Los eventos existentes quedan como judges_only, así que no cambia nada para ellos.

alter table app.events
  add column event_type text not null default 'judges_only'
    check (event_type in ('judges_only', 'voting'));

comment on column app.events.event_type is
  'Tipo de evento: judges_only (solo jueces) o voting (delegados + staff + jueces).';
