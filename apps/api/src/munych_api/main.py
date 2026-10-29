"""Punto de entrada de la API FastAPI."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from slowapi.errors import RateLimitExceeded

from munych_api.config import Settings, get_settings
from munych_api.modules.events.router import router as events_router
from munych_api.modules.identity.router import router as identity_router
from munych_api.modules.judging.router import router as judging_router
from munych_api.modules.results.api.router import router as results_router
from munych_api.modules.results.infrastructure.nextjs_revalidation import NextJsRevalidator
from munych_api.modules.rubrics.router import router as rubrics_router
from munych_api.modules.scoring.api.router import router as scoring_router
from munych_api.shared.auth import JwtVerifier, SupabaseKeyResolver
from munych_api.shared.database import Database
from munych_api.shared.errors import register_error_handlers
from munych_api.shared.observability import configure_logging, configure_sentry
from munych_api.shared.rate_limit import limiter, rate_limit_exceeded_handler
from munych_api.shared.supabase import SupabaseAdmin
import os
import sys

# 1. Obtiene la ruta del directorio 'src' (dos niveles arriba de main.py)
current_dir = os.path.dirname(os.path.abspath(__file__))  # .../munych_api
src_dir = os.path.dirname(current_dir)  # .../src

# 2. Agrega 'src' al inicio del PYTHONPATH
if src_dir not in sys.path:
  sys.path.insert(0, src_dir)

# 3. Tus importaciones ahora funcionarán sin problemas
from munych_api.config import Settings, get_settings
API_PREFIX = "/api/v1"


def stable_operation_id(route: APIRoute) -> str:
    """El `operation_id` es el nombre de la función del endpoint (el frontend usa Orval)."""
    return route.name


health_router = APIRouter(tags=["health"])


@health_router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    configure_sentry(settings)

    database = Database(settings.database_url)
    key_resolver = SupabaseKeyResolver(
        jwks_url=f"{settings.supabase_issuer}/.well-known/jwks.json",
        hs256_secret=(
            settings.supabase_jwt_secret.get_secret_value()
            if settings.supabase_jwt_secret
            else None
        ),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Precalienta JWKS y BD en paralelo: la primera petición tras el login no espera red.
        if settings.environment != "test":
            await asyncio.gather(key_resolver.warm_up(), database.warm_up())
        yield
        await key_resolver.aclose()
        await database.dispose()

    app = FastAPI(
        title="MUNYCH — API de calificaciones",
        version="0.1.0",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        generate_unique_id_function=stable_operation_id,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.token_verifier = JwtVerifier(
        issuer=settings.supabase_issuer, key_resolver=key_resolver
    )
    app.state.supabase = SupabaseAdmin(settings)
    app.state.revalidator = NextJsRevalidator(
        settings.public_site_url, settings.revalidate_secret.get_secret_value()
    )

    limiter.enabled = settings.environment != "test"
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )
    register_error_handlers(app)

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health_router)
    api.include_router(identity_router)
    api.include_router(events_router)
    api.include_router(rubrics_router)
    api.include_router(judging_router)
    api.include_router(scoring_router)
    api.include_router(results_router)
    app.include_router(api)
    return app


app = create_app()
