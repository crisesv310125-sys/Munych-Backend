"""Límite de peticiones (slowapi) para el lote de calificaciones, invitaciones y la boleta."""

import hashlib

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from munych_api.shared.errors import problem

limiter = Limiter(key_func=get_remote_address)

SCORES_BATCH_LIMIT = "120/minute"
INVITES_LIMIT = "20/minute"
# Los delegados comparten la IP del lugar (NAT): su límite va por token, no por IP.
BALLOT_LIMIT = "20/minute"
VOTES_LIMIT = "30/minute"


def voter_key(request: Request) -> str:
    """Clave del límite para la boleta: un hash corto del token (nunca el token)."""
    auth = request.headers.get("authorization", "")
    if not auth:
        return get_remote_address(request)
    return "voter:" + hashlib.sha256(auth.encode()).hexdigest()[:16]


async def rate_limit_exceeded_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RateLimitExceeded):  # pragma: no cover
        raise exc
    return problem(
        429, "RATE_LIMITED", "Demasiadas peticiones; inténtalo de nuevo en unos segundos"
    )
