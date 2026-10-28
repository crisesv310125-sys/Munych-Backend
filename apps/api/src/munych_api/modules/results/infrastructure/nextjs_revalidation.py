"""Webhook de revalidación del sitio público (sección 7.6)."""

import hashlib
import hmac
import json

import httpx
import structlog

logger = structlog.get_logger(__name__)

TIMEOUT_SECONDS = 5.0
RETRIES = 2


def sign(body: bytes, secret: str) -> str:
    """Valor de la cabecera `X-Signature`: `sha256=<hex HMAC-SHA256 del cuerpo>`."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class NextJsRevalidator:
    def __init__(
        self,
        site_url: str,
        secret: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        retries: int = RETRIES,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self._url = f"{site_url.rstrip('/')}/api/revalidate"
        self._secret = secret
        self._transport = transport
        self._retries = retries
        self._timeout = timeout

    async def revalidate(self, event_slug: str) -> bool:
        """POST firmado con 2 reintentos. Nunca lanza: devuelve si el sitio lo aceptó."""
        if not self._secret:
            logger.warning("revalidation_skipped", reason="REVALIDATE_SECRET vacío")
            return False
        body = json.dumps({"event_slug": event_slug}, separators=(",", ":")).encode()
        headers = {"Content-Type": "application/json", "X-Signature": sign(body, self._secret)}

        async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
            for attempt in range(1, self._retries + 2):
                try:
                    response = await client.post(self._url, content=body, headers=headers)
                except httpx.HTTPError as exc:
                    logger.warning(
                        "revalidation_failed", attempt=attempt, error_type=type(exc).__name__
                    )
                    continue
                if response.is_success:
                    return True
                logger.warning(
                    "revalidation_failed", attempt=attempt, status_code=response.status_code
                )
        return False
