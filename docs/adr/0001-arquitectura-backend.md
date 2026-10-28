# ADR 0001 — Arquitectura del backend

- **Estado**: aceptado
- **Fecha**: 2026-09-28
- **Contexto de origen**: `docs/prompts/backend.md` (propuesta técnica v0.4, requerimientos v0.3)

## Contexto

MUNYCH necesita un sistema web para que los jueces califiquen a los delegados de un MUN por criterio y por sesión, y para que el administrador calcule rankings, asigne premios y publique resultados. Participan menores de edad, así que la privacidad es un requisito de primer nivel. El equipo prefiere Python. El frontend ya existe (en otro repositorio) y consume esta API con un cliente generado por Orval.

## Decisiones

### 1. Stack

| Pieza | Elección |
|---|---|
| Lenguaje y framework | Python 3.12+, FastAPI; Uvicorn en desarrollo y Gunicorn con workers Uvicorn en producción |
| Validación y configuración | Pydantic v2 + pydantic-settings |
| Plataforma de datos | Supabase: PostgreSQL, Auth y Storage |
| Acceso a datos | SQLAlchemy 2.0 async + asyncpg, a través de Supavisor en **modo sesión** |
| Migraciones | Supabase CLI (`supabase/migrations/*.sql`), única fuente de verdad. **Sin Alembic** |
| JWT | PyJWT con JWKS del proyecto; HS256 (`SUPABASE_JWT_SECRET`) como alternativa heredada |
| Integraciones | supabase-py (`service_role`: invitaciones y Storage), httpx (webhook), openpyxl (Excel) |
| Operación | slowapi (límite de peticiones), structlog, Sentry opcional |
| Calidad | uv, Ruff, mypy estricto, import-linter, pytest + Hypothesis |

### 2. Monolito modular con dos estilos internos

- **3 capas** (router → service → repository) en los módulos CRUD: `identity`, `events`, `judging`, `rubrics`, `audit`. Tienen poca lógica de negocio, así que la ceremonia hexagonal no compensa.
- **Hexagonal** en `scoring` y `results`: aquí viven las reglas de negocio (idempotencia, validación por ítem, cálculo, cierre, publicación).
  - Dominio puro.
  - Casos de uso en `application/`.
  - Puertos como `typing.Protocol`.
  - Adaptadores (SQLAlchemy, Excel, webhook) en `infrastructure/`.
  - Así se pueden probar con adaptadores en memoria.
- **`scoring_engine/`**: funciones puras sobre `Decimal`, solo con la biblioteca estándar. El frontend reutilizará sus fixtures JSON en fase 2.
- El cableado de dependencias se hace **solo** en `api/dependencies.py` con `Depends`.
- **Reglas de dependencias**, verificadas con import-linter en CI (`just lint`):
  - `domain/` no importa frameworks ni infraestructura.
  - `scoring_engine/` no importa nada de la app.
  - Ningún módulo importa el `repository` de otro.

### 3. Supabase

- **Todas las escrituras pasan por FastAPI.** El frontend usa Supabase solo para autenticarse.
- Tablas del dominio en el esquema **`app`**, **no expuesto** en la Data API. En `public` solo existe `public_results` (lectura `anon` si `published = true`).
- **RLS activado en todas las tablas** como defensa en profundidad. El backend conecta con el rol `postgres` (propietario), que no está sujeto a RLS.
- **Roles** en `app.user_roles`, copiados al JWT como claim `app_role` mediante un *Custom Access Token Hook* (función SQL). Nunca se usa `user_metadata` para roles.
- La clave `service_role` solo existe en el backend y se redacta en los logs.
- `result_snapshots` y `audit_log` son **solo inserción** (triggers que rechazan `UPDATE`/`DELETE`).

### 4. Contrato de API

- Prefijo `/api/v1`, snake_case, errores `application/problem+json` con `code` estable.
- `operation_id` = nombre de la función del endpoint (`generate_unique_id_function`), para que el cliente Orval sea estable.
- Consistencia: la escritura de calificaciones es **idempotente por lotes**. Cada ítem se valida por separado y la respuesta devuelve aceptados y rechazados.

### 5. Privacidad

- Minimización: del delegado solo se guardan nombre, institución y delegación.
- La salida pública la genera **solo** `build_public_view`, construida por lista blanca y con pruebas de privacidad. Los valores por defecto son conservadores (nombre "Ana P.", sin ranking, sin puntajes, `noindex`).

## Consecuencias

- **+** El dominio de calificación y resultados se prueba sin base de datos; el motor es portable al frontend.
- **+** El esquema versionado en SQL permite usar RLS, triggers y el auth hook sin salir de las herramientas de Supabase.
- **−** Sin Alembic no hay autogeneración de migraciones desde los modelos: las tablas SQLAlchemy se mantienen a mano a partir del SQL.
- **−** Las pruebas de integración y RLS requieren Docker (`supabase start`).
- **−** Sin Realtime en fase 1: el frontend hace *polling* a `/progress`.

## Cambios al contrato

No se ha cambiado ninguna ruta ni código del contrato de la sección 7. Cualquier cambio de rutas, formas o códigos se registra aquí y se avisa al equipo del frontend. `tests/api/test_openapi.py` fija las rutas y los `operation_id`.

### Precisiones (2026-09-28)

Aspectos que la especificación dejaba abiertos y que el backend fija así:

| Tema | Decisión |
|---|---|
| Ruta añadida | `POST /events/{event_id}/rubrics` (`create_rubric`) crea una rúbrica adicional para sobrescribir la del evento en un comité (`committees.rubric_id`). |
| Cuerpos de reemplazo | `PUT /committees/{id}/judges` y `PUT /committees/{id}/awards` reciben un **array JSON** tal cual (`[{ judge_id, role }]`, `[{ award_type, delegation_id, position }]`; `position` vale 1 por defecto). |
| Respuesta de asignaciones | `GET/PUT /committees/{id}/judges` → `[{ judge_id, role, full_name, email, active }]`. |
| Respuesta de premios | `GET/PUT /committees/{id}/awards` → `{ items: [...], quota_warnings: [string] }`. Superar un cupo no bloquea. |
| `incomplete_flags` | Objetos `{ kind, delegate_id, session_number, judge_id }` con `kind` ∈ `incomplete` \| `session_without_scores` \| `delegate_without_scores` (ver `fixtures/scoring/README.md`). |
| Ranking sin notas | `score = null`; esas delegaciones van al final y, si son varias, comparten posición con `tied: true`. `criteria_averages` usa `criterion_id` como clave. |
| Lote de calificaciones | Máximo 500 ítems. Un ítem con `client_updated_at` **anterior** al guardado se devuelve en `accepted` sin cambios (gana la última escritura; el cliente deja de reintentar). `client_updated_at` se acota a la hora del servidor para que un reloj adelantado no bloquee ediciones. Reutilizar un `client_id` para otra celda → `VALIDATION_ERROR`; dos escrituras simultáneas de la misma celda → `CONFLICT`. |
| Lecturas sin paginar | `GET /committees/{id}/sessions` y `GET /judge/sessions/{id}/scores` devuelven listas (son pequeñas y acotadas). |
| Sesiones | Abrir una sesión abierta o cerrar una cerrada es idempotente. No se abren ni cierran sesiones de eventos cerrados (`EVENT_CLOSED`). |
| Cierre | `POST /events/{id}/close` → `{ event_id, status: "closed", snapshot_id, closed_at }`. |
| Publicación | Se publica la **última instantánea** con la configuración **actual** (se puede cambiar tras el cierre). La vista previa usa `version` = versión actual + 1. `unpublish` es idempotente. La publicación se confirma en la BD **antes** de llamar al webhook. |
| Códigos adicionales | `UNAUTHORIZED` (401), `FORBIDDEN` (403), `CONFLICT` (409), `RATE_LIMITED` (429) e `INTERNAL_ERROR` (500), además de los de la sección 7.3. |
| Formato "Nombre I." | Primera palabra + inicial de la siguiente palabra que no sea partícula (`de`, `del`, `la`…): "Juan de la Cruz" → "Juan C.". |
| Excel | Los textos que empiezan por `=`, `+`, `-` o `@` se escriben con un apóstrofo delante para evitar inyección de fórmulas. |

### Invitaciones de jueces (2026-10-12)

| Tema | Decisión |
|---|---|
| Lista de jueces | `GET /judges` solo devuelve jueces que **aceptaron** la invitación (`auth.users.email_confirmed_at` no nulo). |
| Rutas añadidas | `GET /judges/invitations` (`list_judge_invitations`) → `{ items: [{ judge_id, email, full_name, invited_at }], total }` con las invitaciones pendientes. `POST /judges/{judge_id}/invitation` (`resend_judge_invitation`) reenvía el correo y devuelve la invitación; `404` si no es juez de la organización y `409 CONFLICT` si ya la aceptó. Comparte el límite de `POST /judges`. |
| Reinvitar | `POST /judges` con el correo de un juez pendiente reenvía la invitación (antes lo reutilizaba sin enviar nada). |
| Límite de correos | Si Supabase Auth rechaza el envío por límite de correos (429), la API responde `429 RATE_LIMITED` con un mensaje en español en lugar de `500`. |
| Destino del enlace | Las invitaciones redirigen a `PANEL_URL` (por defecto `http://localhost:5173`), que debe estar en las Redirect URLs de Supabase Auth. |
