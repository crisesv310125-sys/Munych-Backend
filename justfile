# Tareas del monorepo MUNYCH. Ejecuta `just` para ver la lista.
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]
set dotenv-load := true

api := "apps/api"

default:
    @just --list

# ─────────────────────────────── Backend (apps/api)

# Instala dependencias de Python (uv) y el CLI de Supabase (npm)
setup:
    cd {{api}}; uv sync
    npm install --no-fund --no-audit

# Servidor de desarrollo con recarga en http://127.0.0.1:8000
dev:
    cd {{api}}; uv run uvicorn munych_api.main:app --reload --host 127.0.0.1 --port 8000

# Todas las pruebas (las de integración se saltan si el stack local no está levantado)
test *args:
    cd {{api}}; uv run pytest {{args}}

# Solo pruebas unitarias y de API sin base de datos
test-unit *args:
    cd {{api}}; uv run pytest -m "not integration" {{args}}

# Cobertura del motor y del dominio (mínimo 90 %)
coverage:
    cd {{api}}; uv run pytest tests/unit --cov=munych_api.scoring_engine --cov=munych_api.modules.scoring.domain --cov=munych_api.modules.results.domain --cov-report=term-missing --cov-fail-under=90

# Ruff (lint + formato en modo comprobación) e import-linter
lint:
    cd {{api}}; uv run ruff check .
    cd {{api}}; uv run ruff format --check .
    cd {{api}}; uv run lint-imports

# Aplica el formato de Ruff y las correcciones automáticas
fmt:
    cd {{api}}; uv run ruff format .
    cd {{api}}; uv run ruff check --fix .

# mypy estricto
typecheck:
    cd {{api}}; uv run mypy

# lint + tipos + pruebas unitarias
check: lint typecheck test-unit

# ─────────────────────────────── Supabase (requiere Docker)

# Levanta el stack local de Supabase
db-start:
    npx supabase start

# Detiene el stack local
db-stop:
    npx supabase stop

# Recrea la base local: migraciones + seed.sql
db-reset:
    npx supabase db reset

# Estado y claves del stack local
db-status:
    npx supabase status

# Crea una migración nueva: just db-new nombre_descriptivo
db-new name:
    npx supabase migration new {{name}}

# ─────────────────────────────── Frontend
# (reservado: el frontend vive en otro repositorio)
