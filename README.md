# MUNYCH — Backend del sistema de calificaciones

API FastAPI + Supabase para calificar a los delegados de un Modelo de Naciones Unidas por
criterio y por sesión, calcular rankings, asignar premios, exportar a Excel y publicar
resultados. Cliente: **MUNYCH Association**. Participan menores de edad: la privacidad es un
requisito de primer nivel.

- Especificación: [`docs/prompts/backend.md`](docs/prompts/backend.md)
- Decisiones de arquitectura y precisiones del contrato: [`docs/adr/0001-arquitectura-backend.md`](docs/adr/0001-arquitectura-backend.md)
- Casos del motor de cálculo (compartidos con el frontend): [`fixtures/scoring/README.md`](fixtures/scoring/README.md)

## Puesta en marcha (≈ 10 minutos)

### 1. Requisitos

| Herramienta | Para qué | Instalación (Windows) |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Python 3.12+ y dependencias | `winget install astral-sh.uv` |
| [just](https://github.com/casey/just) | tareas del proyecto | `winget install Casey.Just` |
| Node.js 20+ | CLI de Supabase (`npx supabase`) | `winget install OpenJS.NodeJS.LTS` |
| Docker Desktop | stack local de Supabase | requiere **WSL 2** (`wsl --install`, como administrador, y reiniciar) |

### 2. Instalar y levantar

```powershell
just setup                 # dependencias de Python (uv) y CLI de Supabase (npm)
Copy-Item .env.example .env
just db-start              # levanta Supabase local (la primera vez descarga imágenes)
just db-reset              # aplica supabase/migrations/*.sql y carga supabase/seed.sql
just db-status             # muestra las claves locales
```

Rellena `.env` con los valores locales que muestra `just db-status`:

```dotenv
DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres
SUPABASE_URL=http://127.0.0.1:54321
SUPABASE_SERVICE_ROLE_KEY=<service_role key de db-status>
```

### Actualización del sitio público (Cloudflare Pages)

El sitio público es estático: cada publicación necesita un build nuevo. La migración
`site_rebuild` lo agrupa en la base de datos: un trigger en `public_results` marca que hay
cambios y `pg_cron` llama al deploy hook de Cloudflare Pages cuando llevan 45 s sin cambios
(como máximo, 5 min después del primer cambio pendiente). Para activarlo, guarda la URL del
hook en Vault una vez por proyecto (SQL Editor de Supabase):

```sql
select vault.create_secret('<URL del deploy hook>', 'pages_deploy_hook_url');
```

Sin ese secreto no se llama a nada y `publish`/`unpublish` responden `revalidated: false`.
Para revisar el estado: `select * from app.site_rebuild;` y la respuesta de Cloudflare en
`select * from net._http_response where id = (select last_request_id from app.site_rebuild);`.

### 3. Ejecutar

```powershell
just dev                   # http://127.0.0.1:8000/api/v1/docs
```

Usuarios de desarrollo del `seed.sql` (solo local):

| Correo | Contraseña | Rol |
|---|---|---|
| `admin@munych.dev` | `munych-admin-dev` | admin |
| `juez1@munych.dev` | `munych-juez-dev` | judge |
| `juez2@munych.dev` | `munych-juez-dev` | judge |

Para obtener un token, inicia sesión contra Supabase Auth local (el *auth hook* añade el claim
`app_role`) y úsalo como `Authorization: Bearer <access_token>` en Swagger:

```powershell
$anon = "<anon key de db-status>"
$body = '{"email":"admin@munych.dev","password":"munych-admin-dev"}'
(Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:54321/auth/v1/token?grant_type=password" `
  -Headers @{ apikey = $anon } -ContentType "application/json" -Body $body).access_token
```

## Calidad y pruebas

| Tarea | Comando |
|---|---|
| lint + tipos + pruebas unitarias | `just check` |
| todas las pruebas (integración incluida) | `just test` |
| cobertura del motor y del dominio (≥ 90 %) | `just coverage` |
| formatear | `just fmt` |

- Las pruebas marcadas `integration` (repositorios, RLS, auth hook y API de extremo a extremo)
  se **saltan** si el stack local no responde. Para usar otra base de datos:
  `$env:TEST_DATABASE_URL = "postgresql+asyncpg://..."`.
- Las pruebas de API firman sus propios JWT con una clave RSA local y sustituyen Supabase
  (invitaciones, Storage) y la reconstrucción del sitio público por dobles.

## Estructura

```text
apps/api/src/munych_api/
├── main.py, config.py
├── shared/            kernel (errores, reloj, catálogos), auth, database, supabase, errors, observability
├── scoring_engine/    motor de cálculo PURO (solo biblioteca estándar)
└── modules/
    ├── identity/      /me, jueces e invitaciones                (router → service → repository)
    ├── events/        eventos, comités, delegaciones, CSV, logo (router → service → repository)
    ├── rubrics/       rúbricas (pesos = 100)                     (router → service → repository)
    ├── judging/       asignaciones juez–comité y panel del juez (router → service → repository)
    ├── audit/         registro de auditoría de solo inserción
    ├── scoring/       HEXAGONAL: sesiones, lote idempotente, progreso
    └── results/       HEXAGONAL: ranking, premios, cierre, Excel, publicación
supabase/migrations/   única fuente de verdad del esquema (sin Alembic)
fixtures/scoring/      casos JSON del motor
```

Las reglas de dependencias (dominio sin frameworks, motor puro, repositorios privados de cada
módulo) las comprueba import-linter en `just lint`.

## Preguntas abiertas del cliente

Implementadas con el valor por defecto de la sección 12 y marcadas en el código con
`TODO(cliente)`:

| Pregunta | Valor en el MVP | Dónde |
|---|---|---|
| ¿Por sesión o una vez? | Por sesión | `scoring_engine/final_score.py` |
| ¿Delegación doble? | Se califica a cada delegado; la delegación = media | `scoring_engine/ranking.py` |
| ¿Los jueces ven notas de otros? | No | `modules/scoring/application/get_progress.py` |
| ¿Papel de posición? | No se evalúa | `shared/kernel/catalog.py` |
| ¿Premios automáticos? | Manuales, con aviso de cupos | `shared/kernel/catalog.py` |
| ¿Ausencias? | La sesión sin notas no cuenta (se marca) | `scoring_engine/final_score.py` |
| ¿Qué se publica? | Premios, delegación, "Nombre I." e institución; sin ranking ni puntajes; `noindex` | `modules/results/domain/models.py` |
| Nombres compuestos en "Nombre I." | "María José Pérez" → "María J." | `modules/results/domain/public_view.py` |
