"""Errores de dominio compartidos. Sin dependencias de frameworks."""

from enum import StrEnum


class ErrorCode(StrEnum):
    """Códigos de error del contrato de la API (sección 7.3)."""

    SESSION_CLOSED = "SESSION_CLOSED"
    EVENT_CLOSED = "EVENT_CLOSED"
    JUDGE_NOT_ASSIGNED = "JUDGE_NOT_ASSIGNED"
    VALUE_OUT_OF_RANGE = "VALUE_OUT_OF_RANGE"
    NOT_FOUND = "NOT_FOUND"
    WEIGHTS_MUST_SUM_100 = "WEIGHTS_MUST_SUM_100"
    DELEGATES_LIMIT_EXCEEDED = "DELEGATES_LIMIT_EXCEEDED"
    EVENT_NOT_CLOSED = "EVENT_NOT_CLOSED"
    SESSIONS_STILL_OPEN = "SESSIONS_STILL_OPEN"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    # Códigos transversales de autenticación y conflicto.
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"


_DEFAULT_STATUS: dict[ErrorCode, int] = {
    ErrorCode.SESSION_CLOSED: 409,
    ErrorCode.EVENT_CLOSED: 409,
    ErrorCode.JUDGE_NOT_ASSIGNED: 403,
    ErrorCode.VALUE_OUT_OF_RANGE: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.WEIGHTS_MUST_SUM_100: 422,
    ErrorCode.DELEGATES_LIMIT_EXCEEDED: 422,
    ErrorCode.EVENT_NOT_CLOSED: 409,
    ErrorCode.SESSIONS_STILL_OPEN: 409,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.CONFLICT: 409,
    ErrorCode.RATE_LIMITED: 429,
}


class DomainError(Exception):
    """Error de negocio con código estable y mensaje en español para el usuario."""

    def __init__(self, code: ErrorCode, detail: str, *, status: int | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status if status is not None else _DEFAULT_STATUS[code]


class NotFoundError(DomainError):
    def __init__(self, detail: str = "Recurso no encontrado") -> None:
        super().__init__(ErrorCode.NOT_FOUND, detail)
