---
proyecto: "[[sistema-calificaciones-munych]]"
tipo: prompt para Claude Code
alcance: backend — fase 1 (MVP)
version: 1.0
fecha: 2026-09-27
basado_en: "propuesta técnica v0.4 · requerimientos v0.3"
---

# Prompt para Claude Code — Backend del sistema de calificaciones MUNYCH (fase 1)

> **Cómo usar este archivo**: cópialo a la raíz del repositorio de código (por ejemplo, como `docs/prompts/backend.md`) y en Claude Code escribe:
> *"Lee `docs/prompts/backend.md` y ejecuta la tarea. Empieza en modo plan."*

---

## 0. Tu rol y cómo debes trabajar

Eres un ingeniero backend senior en Python. Vas a construir la **primera versión funcional (MVP)** del backend de un sistema de calificaciones para Modelos de Naciones Unidas (MUN).

**Forma de trabajo obligatoria**:
1. **Empieza en modo plan**. Lee este documento completo, revisa el repositorio y presenta un plan por hitos (sección 13). No escribas código hasta que el plan esté aprobado.
2. Implementa **hito por hito**. Al terminar cada uno: ejecuta lint, tipos y pruebas, y haz un commit con *conventional commits* (`feat(scoring): ...`).
3. **No inventes requisitos**. Si algo no está definido aquí, usa el valor por defecto de la sección 12 y deja un comentario `# TODO(cliente): <pregunta>`.
4. **No implementes lo que está fuera de alcance** (sección 2.2), aunque parezca fácil. Deja la estructura preparada si se indica.
5. Crea un `CLAUDE.md` en la raíz del repo con los comandos del proyecto (dev, test, lint, migraciones) y las convenciones de este documento, y un ADR `docs/adr/0001-arquitectura-backend.md` que resuma las decisiones de la sección 3.
6. Toda la documentación y los mensajes de error visibles al usuario van **en español**. El código (identificadores) va en inglés.

---

## 1. Contexto del producto

- **Cliente**: **MUNYCH Association** (*Models of the United Nations for the Youth and Childhood Association*), organización mexicana que organiza MUN y experiencias internacionales bajo la marca **GRAND International** (eventos en México, Santo Domingo, Nueva York…).
- **Problema**: hoy los jueces califican a los delegados en papel u hojas de cálculo, y los premios dependen de impresiones subjetivas.
- **Solución**: un sistema web con:
  - **Panel de administración**: crea eventos, comités y delegaciones, configura rúbricas, asigna jueces a comités, abre y cierra sesiones, ve rankings, asigna premios, exporta y publica.
  - **Panel de jueces**: califica a los delegados de sus comités asignados por criterio de la rúbrica y por sesión.
  - **Página pública de resultados**: muestra los premios publicados de cada evento.
- **Participan menores de edad.** La privacidad es un requisito de primer nivel (sección 9).

**Glosario mínimo**:

| Término | Significado |
|---|---|
| Evento / conferencia | Encuentro de 1–3 días con varios comités |
| Comité | Órgano simulado (Asamblea General, Consejo de Seguridad, crisis, especializado) |
| Delegación | País (o personaje, en comités de crisis) representado en un comité |
| Delegado | Estudiante que representa a una delegación. Una delegación **doble** tiene 2 delegados |
| Sesión | Bloque de trabajo del comité; un evento tiene varias (típicamente 4–8) |
| Rúbrica | Criterios ponderados con escala (p. ej. 1–4) que usan los jueces |
| Mesa / juez | Personas que califican; un comité puede tener varios jueces |

---

## 2. Alcance

### 2.1 Incluido en esta fase (MVP)

1. Autenticación con **Supabase Auth**: administradores con correo + contraseña y jueces con enlace mágico. FastAPI **verifica el JWT**.
2. CRUD de eventos, comités, delegaciones y delegados, más la **importación CSV** de delegaciones y delegados.
3. Gestión de jueces (invitación por correo con Supabase) y **asignación de jueces a comités**.
4. Rúbricas por evento (criterios, pesos que suman 100, escala, descriptores), con rúbrica por defecto y sobrescritura por comité.
5. Sesiones de calificación por comité: abrir y cerrar.
6. **Calificación por lotes idempotente** desde el panel del juez.
7. Avance de calificación por comité y por juez (consulta; el frontend hace *polling*).
8. **Ranking** por comité, calculado con el motor de cálculo puro.
9. **Asignación manual de premios** por el administrador (con aviso si supera los cupos).
10. **Exportación a Excel** de los resultados de un evento.
11. Cierre del evento con **instantánea inmutable** de resultados.
12. **Publicación**: configuración de privacidad, vista previa, publicar y despublicar en `public_results`, y aviso de revalidación al sitio público.
13. Registro de auditoría de cambios en calificaciones y premios.

### 2.2 Fuera de alcance (fases posteriores; NO implementar)

- Tiempo real con Supabase Realtime (fase 2). El frontend hará *polling* a `/progress`.
- Exportación PDF, normalización z-score, premios **sugeridos** automáticamente y mejor delegación (fases 2–3). Deja el puerto `Exporter` y el motor preparados para crecer.
- MFA obligatorio (fase 2; puede dejarse habilitado en `config.toml` pero no forzado).
- Inscripciones, pagos, lista de oradores, votaciones, portal de delegados.

---

## 3. Stack y decisiones de arquitectura

| Pieza | Elección |
|---|---|
| Lenguaje | **Python 3.12+** (preferencia del equipo) |
| Framework | **FastAPI** + Uvicorn (Gunicorn con workers Uvicorn en producción) |
| Validación y configuración | Pydantic v2 + pydantic-settings |
| Plataforma de datos | **Supabase**: PostgreSQL, Auth y Storage (logos) |
| Acceso a datos | SQLAlchemy 2.0 **async** + asyncpg, vía el **pooler de Supabase (Supavisor) en modo sesión** |
| Migraciones | **Supabase CLI** (`supabase/migrations/*.sql`), única fuente de verdad del esquema. **No uses Alembic** |
| Verificación de JWT | PyJWT con las claves públicas **JWKS** del proyecto. Si el proyecto usa el secreto HS256 heredado, soporta `SUPABASE_JWT_SECRET` como alternativa |
| Cliente Supabase (servidor) | supabase-py con clave `service_role` (invitaciones y Storage) |
| Excel | openpyxl |
| HTTP saliente | httpx (webhook de revalidación) |
| Límite de peticiones | slowapi |
| Logs y errores | structlog + Sentry (opcional por variable de entorno) |
| Calidad | **uv**, Ruff (lint y formato), **mypy estricto** |
| Pruebas | pytest, pytest-asyncio, **Hypothesis**, httpx `AsyncClient`, stack local de Supabase (`supabase start`) |

**Arquitectura: monolito modular**. Los módulos CRUD usan **3 capas** (router → service → repository). Los módulos con reglas de negocio (`scoring`, `results`) usan **arquitectura hexagonal** (dominio puro sin FastAPI ni SQLAlchemy, casos de uso, puertos como `typing.Protocol` y adaptadores en `infrastructure/`). El cableado se hace **solo** en `api/dependencies.py` con `Depends`.

**Reglas de dependencias**:
- `domain/` no importa nada de `fastapi`, `sqlalchemy`, `supabase` ni `httpx`.
- `scoring_engine/` es **puro** (solo biblioteca estándar) y no importa nada del resto de la aplicación.
- Un módulo no importa del `repository` de otro módulo; si necesita datos, usa un puerto (hexagonal) o el `service` público del otro módulo (3 capas).

**Supabase: reglas de uso**:
- Todas las **escrituras** pasan por FastAPI. El frontend usa Supabase solo para autenticación.
- Las tablas del dominio van en el esquema **`app`**, que **no** se expone en la Data API.
- En el esquema `public` solo existe `public_results`, con **RLS** (`select` para `anon` si `published = true`).
- **RLS activado en todas las tablas**, también las de `app`, como defensa en profundidad.
- La clave `service_role` solo existe en el backend. Nunca en logs, respuestas ni código del frontend.
- Los roles se guardan en `app.user_roles` y se añaden al JWT como claim `app_role` mediante un **Custom Access Token Hook** (función SQL en una migración). **Nunca** uses `user_metadata` para roles.

---

## 4. Estructura del repositorio

Monorepo. Si la raíz no existe, créala. El frontend **ya existe** (puede estar en este monorepo o en otro repositorio): **no toques** ninguno de sus archivos.

```text
munych-calificaciones/
├── apps/
│   ├── api/                     # ← TU TRABAJO
│   └── ...                      # (frontend EXISTENTE: puede vivir aquí o en otro repositorio; no lo toques)
├── fixtures/scoring/            # ← TU TRABAJO: casos JSON del motor (sección 7.3)
├── supabase/                    # ← TU TRABAJO
│   ├── config.toml
│   ├── migrations/
│   └── seed.sql
├── docs/adr/
├── justfile                     # ← TU TRABAJO (tareas del backend; deja espacio para las del frontend)
├── .env.example
└── CLAUDE.md
```

```text
apps/api/
├── pyproject.toml
├── src/munych_api/
│   ├── main.py                  # App FastAPI, routers en /api/v1, CORS, manejadores de errores
│   ├── config.py                # Settings (sección 11)
│   ├── shared/
│   │   ├── kernel/              # DomainError, Clock, tipos base
│   │   ├── auth/                # verify_jwt (JWKS), CurrentUser, require_role, require_committee_assignment
│   │   ├── database/            # engine y sesión async, unidad de trabajo
│   │   ├── supabase/            # cliente service_role (invite_user_by_email, storage)
│   │   ├── errors.py            # Respuestas problem+json (sección 8.1)
│   │   └── observability/       # structlog, Sentry
│   ├── scoring_engine/          # PURO: weights, session_score, final_score, ranking, tiebreak
│   └── modules/
│       ├── identity/            # 3 capas: /me, jueces, invitaciones, roles
│       ├── events/              # 3 capas: eventos, comités, delegaciones, delegados, import CSV, logo
│       ├── judging/             # 3 capas: asignaciones juez–comité
│       ├── rubrics/             # 3 capas + validación (pesos = 100)
│       ├── scoring/             # HEXAGONAL
│       │   ├── domain/          # Score, ScoringSession, Grade, errores
│       │   ├── application/     # ports.py, submit_scores.py, open_close_session.py, get_progress.py
│       │   ├── infrastructure/  # sqlalchemy_*_repository.py
│       │   └── api/             # router.py, schemas.py, dependencies.py
│       ├── results/             # HEXAGONAL
│       │   ├── domain/          # Ranking, Award, ResultSnapshot, PublicationSettings
│       │   ├── application/     # compute_ranking, set_awards, close_event, export_event,
│       │   │                    #   build_public_view, publish, unpublish
│       │   ├── infrastructure/  # sqlalchemy repos, excel_exporter.py, nextjs_revalidation.py
│       │   └── api/
│       └── audit/               # registro de auditoría
└── tests/
    ├── unit/                    # scoring_engine (fixtures + Hypothesis), dominio, public_view_builder
    ├── integration/             # repositorios y políticas RLS contra `supabase start`
    └── api/                     # endpoints end-to-end con JWT de prueba
```

---

## 5. Modelo de datos (esquema `app`)

Crea las migraciones SQL con estas tablas. Todas con `id uuid primary key default gen_random_uuid()` salvo que se indique, más `created_at timestamptz default now()` y `updated_at timestamptz` (con trigger). Fechas **siempre en UTC** (`timestamptz`).

| Tabla | Columnas clave | Restricciones |
|---|---|---|
| `organizations` | name | Semilla: "MUNYCH Association". Preparado para varias organizaciones en el futuro |
| `user_roles` | user_id → `auth.users`, organization_id, role (`admin` \| `judge`) | PK (user_id, organization_id) |
| `judges` | user_id → `auth.users` (PK), organization_id, full_name, active | — |
| `events` | organization_id, slug, name, brand (`munych` \| `grand_international`), logo_path, venue, country_code (ISO-3166 alfa-2), timezone (IANA), starts_on, ends_on, status (`draft` \| `active` \| `closed`), default_rubric_id, publication_settings jsonb | `slug` único; `ends_on >= starts_on` |
| `committees` | event_id, name, acronym, slug, type (`general_assembly` \| `security_council` \| `crisis` \| `specialized`), delegation_mode (`single` \| `double`), sessions_count, rubric_id (nullable; sobrescribe la del evento), award_quotas jsonb | `unique(event_id, slug)`; `sessions_count between 1 and 20` |
| `delegations` | committee_id, country_code (nullable), character_name (nullable), institution | `check` exactamente uno de country_code o character_name; `unique(committee_id, country_code)` |
| `delegates` | delegation_id, full_name, institution | Máximo 2 por delegación si el comité es `double`, 1 si es `single` (validar en el servicio) |
| `committee_judges` | committee_id, judge_id, role (`chair` \| `moderator` \| `judge`) | PK (committee_id, judge_id) |
| `rubrics` | event_id, name, scale_min, scale_max | `scale_min < scale_max` |
| `criteria` | rubric_id, name, description, weight numeric(5,2), position, level_descriptors jsonb (`{"1": "...", "4": "..."}`) | `weight > 0`; la suma = 100 se valida en el dominio |
| `scoring_sessions` | committee_id, number, status (`open` \| `closed`), opened_at, closed_at | `unique(committee_id, number)` |
| `scores` | client_id uuid, judge_id, delegate_id, session_id, criterion_id, value smallint, comment text, client_updated_at | `unique(client_id)`; `unique(judge_id, delegate_id, session_id, criterion_id)` |
| `awards` | committee_id, award_type (`best_delegate` \| `outstanding_delegate` \| `honorable_mention` \| `verbal_commendation`), delegation_id, position, assigned_by, assigned_at | `unique(committee_id, award_type, delegation_id)` |
| `result_snapshots` | event_id, data jsonb, created_by | Inmutable (sin UPDATE ni DELETE: revócalo por grants o con un trigger) |
| `audit_log` | actor_id, entity, entity_id, action, before jsonb, after jsonb, at | Solo inserción |

**Esquema `public`**:

| Tabla | Columnas | RLS |
|---|---|---|
| `public_results` | event_slug (PK), event_id, published bool, version int, data jsonb (forma en 7.5), published_at | `anon` y `authenticated`: `select` solo si `published`; escritura solo con `service_role` |

**Storage**: bucket público `event-logos` (solo PNG/SVG/WebP, máximo 2 MB); solo el backend escribe.

**Índices**: `scores(session_id, delegate_id)`, `scores(judge_id, session_id)`, `delegations(committee_id)`, `committee_judges(judge_id)`.

**`seed.sql`**: organización MUNYCH, un usuario admin de desarrollo, un evento de ejemplo (*SD-MUN 2026*, `America/Santo_Domingo`) con 2 comités (uno `single` y uno `double`), 6 delegaciones por comité, 2 jueces asignados, la rúbrica por defecto (sección 6.1) y 2 sesiones.

---

## 6. Reglas de negocio

### 6.1 Rúbrica por defecto (se crea al crear un evento)

Escala **1–4**. Descriptores de nivel: 4 = Excepcional, 3 = Competente, 2 = En desarrollo, 1 = Inicial.

| Criterio | Peso |
|---|---|
| Conocimiento del tema y posición del país | 20 |
| Oratoria (debate formal) | 20 |
| Negociación y liderazgo (debate informal) | 20 |
| Contribución a resoluciones | 15 |
| Diplomacia y conducta | 15 |
| Uso del reglamento | 10 |

### 6.2 Calificación

- Un juez solo califica delegados de comités donde está **asignado** (`JUDGE_NOT_ASSIGNED`).
- Solo se califica en sesiones **abiertas** (`SESSION_CLOSED`) de eventos **no cerrados** (`EVENT_CLOSED`).
- `value` dentro de `[scale_min, scale_max]` (`VALUE_OUT_OF_RANGE`).
- El lote es **idempotente**:
  - Upsert por `(judge_id, delegate_id, session_id, criterion_id)`.
  - Si llega un `client_id` repetido con datos iguales, se acepta sin cambios.
  - Si `client_updated_at` es más antiguo que el guardado, se ignora (gana la última escritura del mismo juez).
- **Cada ítem se valida por separado**: el lote devuelve aceptados y rechazados con su código; un ítem inválido no invalida el resto.
- Un juez **no puede leer** las calificaciones de otros jueces.
- Toda creación o modificación de una calificación genera una entrada en `audit_log`.

### 6.3 Cálculo (`scoring_engine`, funciones puras)

1. **Nota ponderada** de un delegado, por un juez, en una sesión: `Σ (value_i / scale_max) × weight_i` → 0–100. Solo cuenta si el juez calificó **todos** los criterios de ese delegado en esa sesión; si no, esa terna se marca `incomplete` y se excluye.
2. **Nota de sesión** del delegado = media de las notas ponderadas de los jueces completos.
3. **Nota final** del delegado = media de sus notas de sesión. Las sesiones sin notas no cuentan (y se marcan).
4. **Nota de la delegación** = media de las notas finales de sus delegados.
5. **Ranking del comité** por nota de la delegación, descendente. **Desempate**:
   1. Mayor media en el criterio de mayor peso (si hay varios con el mismo peso, el de menor `position`).
   2. Si persiste el empate, misma posición y marca `tied: true` para que decida el administrador.
6. Redondeo **solo al presentar** (2 decimales); los cálculos internos usan `Decimal`.

### 6.4 Premios

- En el MVP los asigna el administrador **manualmente** desde el ranking.
- `award_quotas` del comité (por defecto según el tipo, tabla siguiente) se usa para **avisar**, no para bloquear.

| Tipo de comité | best | outstanding | honorable | verbal |
|---|---|---|---|---|
| general_assembly | 1 | 2 | 2 | 3 |
| security_council | 1 | 1 | 2 | 2 |
| crisis | 1 | 1 | 1 | 2 |
| specialized | 1 | 1 | 2 | 3 |

### 6.5 Cierre y publicación

- **Cerrar evento**:
  - Exige todas las sesiones cerradas.
  - Crea un `result_snapshot` (rankings + premios + configuración).
  - Pone el evento en `closed`: a partir de ahí ninguna escritura sobre calificaciones o premios.
- **`publication_settings`** (valores por defecto conservadores, porque hay menores):
  ```json
  { "name_format": "first_name_initial", "show_institution": true, "show_ranking": false,
    "show_scores": false, "indexable": false }
  ```
  - `name_format` admite `full` | `first_name_initial` | `hidden`.
  - Ejemplo de `first_name_initial`: "Ana Pérez López" → "Ana P.".
- **Vista previa**: devuelve exactamente el JSON que se publicaría, sin guardarlo.
- **Publicar**:
  1. Solo con el evento `closed`.
  2. `build_public_view(snapshot, settings)` genera el documento (sección 7.5), que **nunca** incluye jueces, comentarios, IDs internos de personas ni puntajes si `show_scores = false`.
  3. Upsert en `public.public_results` con `published = true` y `version + 1`.
  4. Llama al webhook de revalidación (sección 7.6). Si el webhook falla, la publicación queda hecha, se registra el error y el endpoint devuelve `revalidated: false`.
- **Despublicar**: `published = false` + webhook.

---

## 7. Contrato de la API

Este contrato (rutas, formas y códigos) es **el mismo** que en el prompt del frontend; solo cambian las notas de implementación de cada lado. Si necesitas cambiarlo, documenta el cambio en el ADR y avisa, porque el frontend depende de él.

### 7.1 Convenciones

- Prefijo `/api/v1`. JSON en `snake_case`. IDs `uuid`. Fechas ISO 8601 en UTC.
- Autenticación: `Authorization: Bearer <access_token de Supabase>`. Rol en el claim `app_role`.
- OpenAPI en `/api/v1/openapi.json`, con `operation_id` estables (`list_events`, `submit_scores_batch`…) porque el frontend genera su cliente con Orval.
- Paginación de listas: `?limit=&offset=` → `{ "items": [...], "total": n }`.
- Errores en `application/problem+json`: `{ "type", "title", "status", "code", "detail", "errors"? }`.

### 7.2 Endpoints

**Comunes**

| Método | Ruta | Rol | Descripción |
|---|---|---|---|
| GET | `/me` | cualquiera | `{ user_id, email, role, full_name }` |

**Administración** (rol `admin`)

| Método | Ruta | Descripción |
|---|---|---|
| GET, POST | `/events` | Listar / crear (crea la rúbrica por defecto) |
| GET, PATCH, DELETE | `/events/{event_id}` | Detalle / editar / borrar (solo `draft`) |
| POST | `/events/{event_id}/logo` | Subir logo (multipart) → Storage `event-logos` |
| POST | `/events/{event_id}/close` | Cerrar evento + instantánea |
| GET, POST | `/events/{event_id}/committees` | Listar / crear |
| GET, PATCH, DELETE | `/committees/{committee_id}` | Detalle / editar / borrar |
| GET, POST | `/committees/{committee_id}/delegations` | Listar (con delegados) / crear |
| POST | `/committees/{committee_id}/delegations/import` | CSV (sección 7.4) → `{ created, skipped, errors: [{ row, message }] }` |
| PATCH, DELETE | `/delegations/{delegation_id}` | Editar / borrar |
| POST | `/delegations/{delegation_id}/delegates` | Añadir delegado |
| PATCH, DELETE | `/delegates/{delegate_id}` | Editar / borrar |
| GET, POST | `/judges` | Listar / invitar (`{ email, full_name }` → invitación de Supabase) |
| PATCH | `/judges/{judge_id}` | Editar nombre / `active` |
| GET, PUT | `/committees/{committee_id}/judges` | Ver / reemplazar asignaciones `[{ judge_id, role }]` |
| GET | `/events/{event_id}/rubrics` | Listar rúbricas del evento |
| GET, PUT | `/rubrics/{rubric_id}` | Ver / reemplazar (nombre, escala, criterios) |
| GET | `/committees/{committee_id}/sessions` | Sesiones con estado |
| POST | `/committees/{committee_id}/sessions/{number}/open` | Abrir |
| POST | `/committees/{committee_id}/sessions/{number}/close` | Cerrar |
| GET | `/committees/{committee_id}/progress` | `{ sessions: [{ number, status, judges: [{ judge_id, full_name, scored, expected }] }] }` |
| GET | `/committees/{committee_id}/ranking` | Ver 7.5 (`RankingEntry`) + `quota_warnings` |
| GET, PUT | `/committees/{committee_id}/awards` | Ver / reemplazar `[{ award_type, delegation_id, position }]` |
| GET | `/events/{event_id}/export.xlsx` | Excel: hoja por comité (ranking + premios) + hoja de detalle por criterio |
| GET, PUT | `/events/{event_id}/publication-settings` | Ver / editar |
| GET | `/events/{event_id}/publication/preview` | Documento público (7.5) sin guardar |
| POST | `/events/{event_id}/publish` | `{ version, published_at, revalidated }` |
| POST | `/events/{event_id}/unpublish` | `{ revalidated }` |

**Jueces** (rol `judge`, siempre limitado a sus asignaciones)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/judge/committees` | Comités asignados `[{ committee_id, name, acronym, event: { name, logo_url, timezone }, role }]` |
| GET | `/judge/committees/{committee_id}` | Delegaciones + delegados + rúbrica (con descriptores) + sesiones con estado |
| GET | `/judge/sessions/{session_id}/scores` | **Sus** calificaciones de esa sesión |
| POST | `/judge/scores/batch` | Lote (7.3) |

### 7.3 Lote de calificaciones

```json
// POST /api/v1/judge/scores/batch
{ "items": [ { "client_id": "uuid", "delegate_id": "uuid", "session_id": "uuid",
               "criterion_id": "uuid", "value": 3, "comment": "opcional",
               "client_updated_at": "2026-10-10T15:04:05Z" } ] }
// 200
{ "accepted": ["client_id", "..."],
  "rejected": [ { "client_id": "uuid", "code": "SESSION_CLOSED", "detail": "La sesión 2 está cerrada" } ] }
```

Códigos de error: `SESSION_CLOSED`, `EVENT_CLOSED`, `JUDGE_NOT_ASSIGNED`, `VALUE_OUT_OF_RANGE`, `NOT_FOUND`, `WEIGHTS_MUST_SUM_100`, `DELEGATES_LIMIT_EXCEEDED`, `EVENT_NOT_CLOSED`, `SESSIONS_STILL_OPEN`, `VALIDATION_ERROR`.

**Fixtures del motor** (`fixtures/scoring/*.json`): crea al menos 8 casos con la forma `{ "name", "rubric": {...}, "scores": [...], "expected": { "delegates": {...}, "ranking": [...] } }`. Cubre: caso básico, delegación doble, juez incompleto, sesión sin notas, empate resuelto por criterio, empate no resuelto, escala distinta de 1–4 y un solo juez. El frontend reutilizará estos fixtures en fase 2, así que la forma debe ser estable y estar documentada en `fixtures/scoring/README.md`.

### 7.4 CSV de importación

Codificación UTF-8, separador `,`, con cabecera:

```csv
country_code,character_name,institution,delegate_1,delegate_2
MX,,Colegio Ejemplo,Ana Pérez López,
US,,Instituto Norte,John Smith,Mary Jones
,Ministro de Defensa,Colegio Sur,Luis Gómez,
```

- Si `delegate_2` tiene valor en un comité `single`, la fila es un error.
- Si el país ya existe en el comité, la fila se omite.
- Las filas válidas se importan aunque otras fallen.

### 7.5 Formas compartidas

```jsonc
// RankingEntry (GET /committees/{id}/ranking → { items: RankingEntry[], quota_warnings: string[] })
{ "position": 1, "tied": false, "delegation_id": "uuid", "country_code": "MX", "character_name": null,
  "institution": "Colegio Ejemplo", "delegates": [{ "delegate_id": "uuid", "full_name": "Ana Pérez López", "final_score": 87.5 }],
  "score": 87.5, "criteria_averages": { "<criterion_id>": 3.5 }, "incomplete_flags": [] }

// Documento público (public.public_results.data y /publication/preview)
{ "event": { "slug": "sd-mun-2026", "name": "SD-MUN 2026", "brand": "grand_international",
             "logo_url": "https://...", "venue": "Santo Domingo", "starts_on": "2026-10-09",
             "ends_on": "2026-10-11", "timezone": "America/Santo_Domingo" },
  "settings": { "name_format": "first_name_initial", "show_institution": true,
                "show_ranking": false, "show_scores": false, "indexable": false },
  "committees": [ { "slug": "disec", "name": "Primera Comisión", "acronym": "DISEC", "type": "general_assembly",
      "awards": [ { "award_type": "best_delegate", "position": 1,
                    "delegation": { "country_code": "MX", "character_name": null, "institution": "Colegio Ejemplo" },
                    "delegates": ["Ana P."] } ],
      "ranking": null } ],
  "published_at": "2026-10-11T23:00:00Z", "version": 1 }
```

- `ranking` es `null` si `show_ranking = false`. Si no, es una lista con `{ position, delegation, delegates, score }`, donde `score` es `null` salvo que `show_scores = true`.
- `institution` es `null` si `show_institution = false`.
- Con `name_format = hidden`, `delegates` es `[]`.

### 7.6 Webhook de revalidación (FastAPI → página pública)

- Petición: `POST {PUBLIC_SITE_URL}/api/revalidate` con cuerpo `{ "event_slug": "sd-mun-2026" }`.
- Cabecera `X-Signature: sha256=<hex HMAC-SHA256 del cuerpo con REVALIDATE_SECRET>`.
- *Timeout* de 5 s y 2 reintentos.

---

## 8. Detalles de implementación

### 8.1 Autenticación y autorización

- `verify_jwt`:
  - Descarga y cachea el JWKS de `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`.
  - Valida firma, `exp`, `aud = authenticated` e `iss`.
  - Construye `CurrentUser(user_id, role, email)`.
- `require_role("admin" | "judge")` → 403 si no coincide.
- `require_committee_assignment(committee_id)` → comprueba `committee_judges`; 403 con `JUDGE_NOT_ASSIGNED`.
- **Invitar juez**:
  1. `auth.admin.invite_user_by_email` (clave `service_role`).
  2. Crea `judges` y `user_roles(role='judge')`.
  3. Si el correo ya existe, reutiliza el usuario.
- Pruebas: genera JWT de prueba firmados con una clave local y sobrescribe la dependencia de verificación.

### 8.2 Errores

- Las excepciones de dominio (`DomainError(code, detail)`) se traducen a problem+json en un único manejador.
- Validaciones de Pydantic → 422 con `code = VALIDATION_ERROR` y `errors`.
- Mensajes `detail` en español.

### 8.3 Excel

Una hoja **Resumen** con el evento y los premios por comité. Por cada comité, una hoja con el ranking. Una hoja **Detalle** con una fila por delegado, sesión, juez y criterio. Encabezados en español, fechas en la zona horaria del evento.

---

## 9. Seguridad y privacidad (hay menores)

- **Minimización**: del delegado solo `full_name`, `institution` y su delegación. **No** guardes correo, teléfono, fecha de nacimiento ni fotos.
- La salida pública la construye **solo** `build_public_view` y **tiene pruebas** que verifican:
  - Nunca incluye jueces, comentarios, UUID de personas ni apellidos completos con `first_name_initial`.
  - No incluye puntajes con `show_scores = false`.
- CORS solo para los orígenes de `CORS_ORIGINS`. Límite de peticiones en `/judge/scores/batch` y en invitaciones.
- **Secretos solo por variables de entorno**. `.env.example` sin valores reales.
- **Nunca** registres en los logs tokens, la clave `service_role` ni cuerpos con datos personales.
- Pruebas de **RLS**: con la clave `anon` solo se puede leer `public_results` publicados; las tablas de `app` no son accesibles.

---

## 10. Pruebas (mínimo exigido)

- `scoring_engine`:
  - Todos los fixtures.
  - Propiedades con Hypothesis: la nota siempre está en [0, 100]; subir un `value` nunca baja la nota; el ranking es una permutación estable ante el reordenado de la entrada.
- Casos de uso de `scoring`: sesión cerrada, juez no asignado, fuera de rango, idempotencia (el mismo lote dos veces), gana la última escritura.
- `build_public_view`: los 3 formatos de nombre y todas las combinaciones de `show_*`.
- Integración con `supabase start`: repositorios, RLS y *auth hook* (el claim `app_role` aparece en el JWT).
- API: flujo completo (crear evento → comité → importar CSV → invitar y asignar juez → abrir sesión → calificar → cerrar → ranking → premios → cerrar evento → publicar → la vista previa coincide con `public_results`).
- Cobertura ≥ 90 % en `scoring_engine` y `domain/`.

---

## 11. Configuración (`.env.example`)

```dotenv
DATABASE_URL=postgresql+asyncpg://postgres.<ref>:<password>@<pooler-host>:5432/postgres
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_JWT_SECRET=            # solo si el proyecto usa el secreto HS256 heredado
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
PUBLIC_SITE_URL=http://localhost:3000
REVALIDATE_SECRET=
SENTRY_DSN=
ENVIRONMENT=development
```

---

## 12. Valores por defecto para preguntas abiertas del cliente

| Pregunta abierta | Valor por defecto en el MVP |
|---|---|
| ¿Por sesión o una vez? | **Por sesión** |
| ¿Delegación doble: se califica a cada delegado o al par? | **A cada delegado**; la delegación = media |
| ¿Los jueces ven notas de otros? | **No** |
| ¿Papel de posición? | No se evalúa en el MVP |
| ¿Premios automáticos? | **Manuales**, con aviso de cupos |
| ¿Ausencias? | La sesión sin notas no cuenta (se marca) |
| ¿Qué se publica? | Premios, delegación, "Nombre I." e institución; sin ranking ni puntajes; `noindex` |

Marca cada uno en el código con `# TODO(cliente): confirmar <tema>`.

---

## 13. Hitos y criterios de aceptación

| # | Hito | Hecho cuando… |
|---|---|---|
| 1 | Andamiaje | uv, FastAPI con `/health`, Ruff y mypy en verde, `supabase start` funciona, `justfile` con `dev`, `test`, `lint`, `db-reset`; `CLAUDE.md` y ADR 0001 creados |
| 2 | Esquema | Migraciones de las secciones 5 y 3 (RLS, auth hook, bucket); `supabase db reset` carga `seed.sql`; pruebas de RLS en verde |
| 3 | Auth | `verify_jwt`, `/me`, `require_role`, invitación de jueces; pruebas con JWT de prueba |
| 4 | CRUD | Eventos, comités, delegaciones y delegados, importación CSV, logo, rúbricas (pesos = 100), asignaciones |
| 5 | Motor | `scoring_engine` + fixtures + Hypothesis; cobertura ≥ 90 % |
| 6 | Calificación | Sesiones abrir/cerrar, lote idempotente, lecturas del juez, progreso, auditoría |
| 7 | Resultados | Ranking, premios con avisos, cierre con instantánea, Excel |
| 8 | Publicación | Configuración, vista previa, publicar/despublicar, webhook; pruebas de privacidad |
| 9 | Entrega | Prueba del flujo completo en verde, OpenAPI revisado (operation_id estables), README con puesta en marcha en menos de 10 min |

Al terminar, entrega un resumen con qué se hizo, qué quedó con `TODO(cliente)` y los comandos para ejecutarlo.

---

## 🔗 Relacionado

*(Metadatos de la bóveda de Obsidian: ignóralos al implementar.)*

- [[sistema-calificaciones-munych]]
- [[propuesta-tecnica-sistema-calificaciones-munych]]
- [[requerimientos-sistema-calificaciones-munych]]
- [[prompt-frontend-munych]]

#tema/mun #tema/prompt #tema/backend
