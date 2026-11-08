-- ============================================================================
-- VACIAR LOS DATOS DE MUNYCH (eventos, comités, calificaciones, votos, resultados…)
-- ============================================================================
-- ⚠️ NO SE PUEDE DESHACER. Haz un respaldo antes (Supabase → Database → Backups).
--
-- Borra:   eventos, rúbricas y criterios, comités, sesiones, delegaciones y delegados,
--          asignaciones de jueces, calificaciones, accesos y votos de delegados,
--          premios, instantáneas de cierre, bitácora de auditoría y resultados públicos.
-- Conserva: las tablas y su estructura, Auth (usuarios y sesiones), app.organizations,
--          app.user_roles (tu acceso de admin), app.judges (perfiles de los jueces) y
--          app.site_rebuild (configuración del redespliegue del sitio público).
--
-- Uso: pegarlo en Supabase → SQL Editor y ejecutarlo, o
--      psql "<cadena de conexión>" -f supabase/scripts/vaciar_datos.sql
-- Todo va en una transacción: si algo falla, no se borra nada.
-- ============================================================================

begin;

-- Estas dos tablas son de solo inserción (un trigger impide vaciarlas): se desactiva
-- ese trigger solo durante el borrado y se vuelve a activar abajo.
alter table app.result_snapshots disable trigger result_snapshots_no_truncate;
alter table app.audit_log disable trigger audit_log_no_truncate;

truncate table
  app.peer_votes,
  app.voter_tokens,
  app.awards,
  app.scores,
  app.scoring_sessions,
  app.committee_judges,
  app.event_judges,
  app.delegates,
  app.delegations,
  app.committees,
  app.criteria,
  app.rubrics,
  app.result_snapshots,
  app.audit_log,
  public.public_results,
  app.events;

-- Opcional: borrar también los perfiles de los jueces (sus cuentas de Auth y su rol en
-- app.user_roles se quedan; para borrar las cuentas, hazlo desde Supabase → Authentication).
-- truncate table app.judges;

alter table app.result_snapshots enable trigger result_snapshots_no_truncate;
alter table app.audit_log enable trigger audit_log_no_truncate;

commit;

-- Comprobación: todo debe salir en 0, salvo las tablas que se conservan.
select 'events' as tabla, count(*) from app.events
union all select 'committees', count(*) from app.committees
union all select 'delegations', count(*) from app.delegations
union all select 'scores', count(*) from app.scores
union all select 'peer_votes', count(*) from app.peer_votes
union all select 'public_results', count(*) from public.public_results
union all select 'audit_log', count(*) from app.audit_log
union all select '(se conserva) user_roles', count(*) from app.user_roles
union all select '(se conserva) judges', count(*) from app.judges;
