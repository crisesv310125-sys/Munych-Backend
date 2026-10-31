"""Reconstrucción del sitio público en Cloudflare Pages (migración `site_rebuild`).

El sitio es un export estático: cada cambio en `public_results` necesita un build nuevo. No se
llama al deploy hook desde aquí: el trigger de `public_results` marca el cambio en la misma
transacción y pg_cron llama al hook cuando dejan de llegar cambios, para agrupar en un solo
build las publicaciones seguidas de la clausura (y porque en Vercel no hay tareas de fondo).
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PagesRebuildScheduler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def revalidate(self, event_slug: str) -> bool:
        """True si el build quedará agendado, es decir, si el deploy hook está en Vault."""
        configured = await self._session.scalar(text("select app.site_rebuild_configured()"))
        return bool(configured)
