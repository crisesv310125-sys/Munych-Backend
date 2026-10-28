"""Traducción de errores a respuestas `application/problem+json` (RFC 9457)."""

from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from munych_api.shared.kernel import DomainError, ErrorCode

PROBLEM_JSON = "application/problem+json"

logger = structlog.get_logger(__name__)

_HTTP_CODES: dict[int, ErrorCode] = {
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
}

_HTTP_DETAILS: dict[int, str] = {
    401: "Se requiere autenticación",
    403: "No tienes permiso para realizar esta acción",
    404: "Recurso no encontrado",
    405: "Método no permitido",
    429: "Demasiadas peticiones; inténtalo de nuevo en unos segundos",
}


def problem(
    status: int,
    code: str,
    detail: str,
    errors: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://munych.org/problems/{code.lower().replace('_', '-')}",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "code": code,
        "detail": detail,
    }
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


async def _domain_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, DomainError):  # pragma: no cover — Starlette enruta por tipo
        raise exc
    return problem(exc.status, exc.code, exc.detail)


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # pragma: no cover
        raise exc
    errors = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]
    return problem(422, ErrorCode.VALIDATION_ERROR, "Los datos enviados no son válidos", errors)


async def _http_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover
        raise exc
    code = _HTTP_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail else None
    if detail is None or detail == HTTPStatus(exc.status_code).phrase:
        detail = _HTTP_DETAILS.get(exc.status_code, HTTPStatus(exc.status_code).phrase)
    response = problem(exc.status_code, code, detail)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def _unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error", error_type=type(exc).__name__)
    return problem(500, "INTERNAL_ERROR", "Error interno del servidor")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
