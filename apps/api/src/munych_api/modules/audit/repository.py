from typing import Any
from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from munych_api.shared.database.tables import audit_log


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, values: dict[str, Any]) -> UUID:
        audit_id = await self._session.scalar(
            insert(audit_log).values(**values).returning(audit_log.c.id)
        )
        return UUID(str(audit_id))
