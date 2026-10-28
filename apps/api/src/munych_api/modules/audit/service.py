"""Registro de auditoría de solo inserción (calificaciones y premios)."""

from typing import Any, Literal
from uuid import UUID

from munych_api.modules.audit.repository import AuditRepository

AuditEntity = Literal["score", "awards"]
AuditAction = Literal["create", "update", "replace"]


class AuditService:
    def __init__(self, repository: AuditRepository) -> None:
        self._repo = repository

    async def record(
        self,
        *,
        actor_id: UUID | None,
        entity: AuditEntity,
        entity_id: UUID | None,
        action: AuditAction,
        before: dict[str, Any] | list[Any] | None,
        after: dict[str, Any] | list[Any] | None,
    ) -> UUID:
        """`before`/`after` deben ser serializables a JSON."""
        return await self._repo.insert(
            {
                "actor_id": actor_id,
                "entity": entity,
                "entity_id": entity_id,
                "action": action,
                "before": before,
                "after": after,
            }
        )
