"""Engine async y unidad de trabajo (una transacción por petición)."""

from collections.abc import AsyncIterator
from typing import Annotated

import structlog
from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = structlog.get_logger(__name__)


class Database:
    def __init__(self, url: str) -> None:
        # Supavisor en modo sesión: admite sentencias preparadas de asyncpg.
        self.engine: AsyncEngine = create_async_engine(
            url, pool_pre_ping=True, pool_size=5, max_overflow=5
        )
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def warm_up(self) -> None:
        """Abre una conexión al arrancar para que la primera petición no pague el handshake."""
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("select 1"))
        except Exception as exc:  # se reintentará con la primera petición
            logger.warning("database_warm_up_failed", error_type=type(exc).__name__)

    async def dispose(self) -> None:
        await self.engine.dispose()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Abre una transacción: commit si el endpoint termina bien y rollback si falla."""
    database: Database = request.app.state.database
    async with database.sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


# scope="function": el commit se hace antes de enviar la respuesta.
DbSession = Annotated[AsyncSession, Depends(get_session, scope="function")]
