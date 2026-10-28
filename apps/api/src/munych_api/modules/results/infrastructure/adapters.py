"""Adaptadores pequeños: auditoría de premios y URLs públicas de Storage."""

from typing import Any
from uuid import UUID

from munych_api.modules.audit.service import AuditService
from munych_api.shared.kernel.catalog import EVENT_LOGOS_BUCKET
from munych_api.shared.supabase import ObjectStorage


class AwardsAuditAdapter:
    def __init__(self, service: AuditService) -> None:
        self._service = service

    async def record_awards_change(
        self,
        *,
        actor_id: UUID,
        committee_id: UUID,
        before: list[dict[str, Any]],
        after: list[dict[str, Any]],
    ) -> None:
        await self._service.record(
            actor_id=actor_id,
            entity="awards",
            entity_id=committee_id,
            action="replace",
            before=before,
            after=after,
        )


class StoragePublicUrls:
    def __init__(self, storage: ObjectStorage) -> None:
        self._storage = storage

    def logo_url(self, logo_path: str | None) -> str | None:
        return self._storage.public_url(EVENT_LOGOS_BUCKET, logo_path) if logo_path else None
