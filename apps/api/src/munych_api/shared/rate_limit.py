"""Límite de peticiones (slowapi) para el lote de calificaciones y las invitaciones."""

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from munych_api.shared.errors import problem

limiter = Limiter(key_func=get_remote_address)

SCORES_BATCH_LIMIT = "120/minute"
INVITES_LIMIT = "20/minute"


async def rate_limit_exceeded_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RateLimitExceeded):  # pragma: no cover
        raise exc
    return problem(
        429, "RATE_LIMITED", "Demasiadas peticiones; inténtalo de nuevo en unos segundos"
    )
