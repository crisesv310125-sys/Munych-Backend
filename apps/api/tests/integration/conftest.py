from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from tests.support.seed import ADMIN_ID, DISEC_ID, EVENT_ID, JUDGE_1_ID, JUDGE_2_ID, ORG_ID

__all__ = ["ADMIN_ID", "DISEC_ID", "EVENT_ID", "JUDGE_1_ID", "JUDGE_2_ID", "ORG_ID"]


@pytest.fixture
async def conn(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Conexión dentro de una transacción que se deshace al terminar la prueba."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()
