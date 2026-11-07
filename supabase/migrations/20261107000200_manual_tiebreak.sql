-- Desempate manual del admin (2026-11-07).
--
-- Tras el desempate automático (criterio de mayor peso), los empates que queden los
-- decide el admin (reunión del 2026-10-28). Se guarda el orden que eligió para las
-- delegaciones empatadas del comité; el backend lo aplica al calcular el ranking
-- (scoring en `results.domain.ranking.apply_manual_tiebreak`). Un empate solo se
-- resuelve si el orden incluye a todas sus delegaciones.

alter table app.committees
  add column tiebreak_order uuid[] not null default '{}';

comment on column app.committees.tiebreak_order is
  'Desempate manual: ids de delegaciones del comité en el orden que decidió el admin.';
