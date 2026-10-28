"""Logs estructurados (structlog) y Sentry opcional.

Regla de privacidad (sección 9): nunca registrar tokens, la clave `service_role`
ni cuerpos de petición con datos personales. `redact_sensitive` es la última
barrera: sustituye cualquier clave sospechosa antes de emitir el log.
"""

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from munych_api.config import Settings

SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "token",
        "access_token",
        "refresh_token",
        "jwt",
        "password",
        "secret",
        "service_role",
        "service_role_key",
        "supabase_service_role_key",
        "api_key",
        "apikey",
        "body",
        "full_name",
        "email",
        "comment",
    }
)
REDACTED = "[REDACTADO]"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: REDACTED if str(k).lower() in SENSITIVE_KEYS else _redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact(v) for v in value]
    return value


def redact_sensitive(
    _: Any, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _redact(event_dict[key])
    return event_dict


def configure_logging(settings: Settings) -> None:
    renderer: structlog.types.Processor = (
        structlog.dev.ConsoleRenderer()
        if settings.environment == "development"
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_sensitive,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def configure_sentry(settings: Settings) -> None:
    if not settings.sentry_dsn:
        return
    import sentry_sdk  # noqa: PLC0415 — import perezoso: Sentry es opcional

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        send_default_pii=False,
        traces_sample_rate=0.0,
    )
