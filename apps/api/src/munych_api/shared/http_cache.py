"""Cabeceras de caché HTTP por defecto de la API.

Las respuestas de la API dependen del JWT y pueden llevar datos de menores, así que
ningún CDN ni navegador debe guardarlas. El sitio público no lee la API: se cachea
en su propio CDN a partir de `public_results`.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_CACHE_CONTROL = "no-store"


class NoStoreMiddleware:
    """Añade `Cache-Control: no-store` a toda respuesta que no declare el suyo."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_cache_control(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).setdefault("Cache-Control", DEFAULT_CACHE_CONTROL)
            await send(message)

        await self.app(scope, receive, send_with_cache_control)
