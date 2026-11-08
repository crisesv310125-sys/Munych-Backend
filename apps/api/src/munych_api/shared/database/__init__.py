"""Engine async y unidad de trabajo (una transacción por petición)."""

import os
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import uuid4

import structlog
from fastapi import Depends, Request
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

logger = structlog.get_logger(__name__)


TRANSACTION_POOLER_PORT = 6543
"""Puerto de Supavisor en modo transacción (muchos clientes, sin sentencias preparadas)."""


def engine_options(url: str, *, serverless: bool) -> dict[str, Any]:
    """Opciones del engine según dónde corre y a qué pooler se conecta.

    - **Serverless (Vercel)**: `NullPool`. Cada instancia es un proceso aparte; con un pool
      propio, las instancias tibias se quedaban con conexiones ociosas y Supavisor en modo
      sesión (límite de 15 clientes) respondía «EMAXCONNSESSION max clients reached».
      Sin pool, cada petición abre su conexión y la cierra al terminar.
    - **Modo transacción (puerto 6543)**: admite muchos más clientes, pero no sentencias
      preparadas: se desactiva la caché de asyncpg y cada sentencia lleva un nombre único.
    - **Servidor normal (local, Docker)**: pool pequeño y reutilizable, como antes.
    """
    options: dict[str, Any] = {"pool_pre_ping": True}
    if serverless:
        options["poolclass"] = NullPool
        options.pop("pool_pre_ping")  # sin pool no hay conexiones viejas que comprobar
    else:
        options |= {"pool_size": 5, "max_overflow": 5}
    if make_url(url).port == TRANSACTION_POOLER_PORT:
        options["connect_args"] = {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        }
    return options


class Database:
    def __init__(self, url: str, *, serverless: bool | None = None) -> None:
        if serverless is None:
            serverless = bool(os.environ.get("VERCEL"))
        self.serverless = serverless
        self.engine: AsyncEngine = create_async_engine(
            url, **engine_options(url, serverless=serverless)
        )
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def warm_up(self) -> None:
        """Abre una conexión al arrancar para que la primera petición no pague el handshake."""
        if self.serverless:
            return  # sin pool, la conexión de calentamiento se cerraría y no serviría de nada
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
