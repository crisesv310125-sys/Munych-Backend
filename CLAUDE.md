# CLAUDE.md — Backend MUNYCH

Backend del sistema de calificaciones para Modelos de Naciones Unidas (cliente: MUNYCH Association). La especificación completa está en `docs/prompts/backend.md`; las decisiones de arquitectura, en `docs/adr/`.

## Comandos (desde la raíz; requieren `uv`, `just` y Node)

| Tarea | Comando |
|---|---|
| Instalar dependencias | `just setup` |
| Servidor de desarrollo | `just dev` → http://127.0.0.1:8000/api/v1/docs |
| lint + tipos + pruebas unitarias | `just check` |
| Lint (ruff + import-linter) | `just lint` · formatear: `just fmt` |
| Tipos (mypy estricto) | `just typecheck` |
| Pruebas | `just test` (todas) · `just test-unit` (sin BD) · `just coverage` |
| Supabase local (requiere Docker) | `just db-start` · `just db-stop` · `just db-status` |
| Migraciones + seed | `just db-reset` · nueva migración: `just db-new <nombre>` |

- `git` no está en el PATH de esta máquina: usa el de GitHub Desktop (`%LOCALAPPDATA%\GitHubDesktop\app-*\resources\app\git\cmd\git.exe`).
- Las pruebas marcadas con `@pytest.mark.integration` se saltan si el stack local de Supabase no responde.

## Estructura

- `apps/api/src/munych_api/`: `main.py`, `config.py`, `shared/` (kernel, auth, database, supabase, errors, observability), `scoring_engine/` (puro) y `modules/`.
- `supabase/migrations/*.sql` es la **única** fuente de verdad del esquema. **No uses Alembic.**
- `fixtures/scoring/*.json`: casos del motor, compartidos con el frontend (forma estable, ver su README).

## Convenciones

- **Idioma**: identificadores en inglés; documentación, mensajes `detail`, textos de error y encabezados de Excel en **español**.
- **Arquitectura**: monolito modular.
  - Los módulos CRUD (`identity`, `events`, `judging`, `rubrics`, `audit`) siguen router → service → repository.
  - `scoring` y `results` son hexagonales: `domain/` puro, `application/` (casos de uso + `ports.py` con `typing.Protocol`), `infrastructure/` (adaptadores) y `api/`.
  - El cableado solo se hace en `api/dependencies.py` con `Depends`.
- **Reglas de dependencias** (las comprueba import-linter en `just lint`):
  - `domain/` no importa `fastapi`, `sqlalchemy`, `supabase` ni `httpx`.
  - `scoring_engine/` usa solo la biblioteca estándar y no importa nada de la app.
  - Un módulo no importa el `repository` de otro; usa un puerto o el `service` público.
- **Errores**: lanza `DomainError(ErrorCode.X, "mensaje en español")`; `shared/errors.py` lo traduce a problem+json. Los códigos del contrato están en `shared/kernel/errors.py`.
- **API**: prefijo `/api/v1`, JSON en snake_case, `operation_id` = nombre de la función del endpoint (el frontend genera su cliente con Orval, así que **no renombres endpoints sin actualizar el ADR**). Listas paginadas: `{items, total}` con `?limit=&offset=`.
- **Supabase**:
  - Tablas del dominio en el esquema `app` (no expuesto en la Data API); en `public` solo está `public_results`.
  - RLS activado en todas las tablas.
  - Todas las escrituras pasan por FastAPI.
  - El rol del usuario llega en el claim `app_role` (auth hook); nunca uses `user_metadata`.
- **Privacidad (participan menores)**:
  - Del delegado solo se guardan `full_name` e `institution`.
  - La salida pública se genera **solo** con `build_public_view`.
  - Nunca registres tokens, la `service_role` ni cuerpos con datos personales (`shared/observability`).
- **Cálculos**: se hacen con `Decimal` y se redondean a 2 decimales solo al presentar.
- **Fechas**: `timestamptz` en UTC; la zona horaria del evento solo se usa para presentar (Excel).
- **Preguntas abiertas del cliente**: usa el valor por defecto de la sección 12 y márcalo con `# TODO(cliente): confirmar <tema>`.
- **Commits**: conventional commits (`feat(scoring): ...`), uno por hito como mínimo, después de `just check`.
- **Fuera de alcance** (no implementar): Realtime, PDF, z-score, premios sugeridos, mejor delegación, MFA obligatorio, inscripciones, pagos, oradores, votaciones y portal de delegados.
