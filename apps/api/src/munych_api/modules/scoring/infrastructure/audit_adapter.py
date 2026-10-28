from typing import Any
from uuid import UUID

from munych_api.modules.audit.service import AuditService


class AuditServiceAdapter:
    """Implementa el puerto `AuditLog` con el servicio público del módulo `audit`."""

    def __init__(self, service: AuditService) -> None:
        self._service = service

    async def record_score_change(
        self,
        *,
        actor_id: UUID,
        score_id: UUID,
        action: str,
        before: dict[str, Any] | None,
        after: dict[str, Any],
    ) -> None:
        await self._service.record(
            actor_id=actor_id,
            entity="score",
            entity_id=score_id,
            action="create" if action == "create" else "update",
            before=before,
            after=after,
        )
