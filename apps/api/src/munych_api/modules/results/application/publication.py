"""Casos de uso de publicación: configuración, vista previa, publicar y despublicar."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog

from munych_api.modules.results.application.close_event import require_event
from munych_api.modules.results.application.ports import Clock, ResultsRepository, Revalidator
from munych_api.modules.results.domain.models import EventInfo, PublicationSettings
from munych_api.modules.results.domain.public_view import build_public_view
from munych_api.shared.kernel import DomainError, ErrorCode

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PublishResult:
    version: int
    published_at: datetime
    revalidated: bool


class Publication:
    def __init__(
        self, repository: ResultsRepository, revalidator: Revalidator, clock: Clock
    ) -> None:
        self._repo = repository
        self._revalidator = revalidator
        self._clock = clock

    # ------------------------------------------------------------ configuración

    async def get_settings(self, organization_id: UUID, event_id: UUID) -> PublicationSettings:
        return (await require_event(self._repo, organization_id, event_id)).publication_settings

    async def update_settings(
        self, organization_id: UUID, event_id: UUID, settings: PublicationSettings
    ) -> PublicationSettings:
        """Se puede cambiar también con el evento cerrado; afecta a la próxima publicación."""
        await require_event(self._repo, organization_id, event_id)
        await self._repo.save_publication_settings(event_id, settings)
        return settings

    # ------------------------------------------------------------ documento público

    async def _document(
        self, event: EventInfo, published_at: datetime
    ) -> tuple[dict[str, Any], int]:
        if not event.closed:
            raise DomainError(
                ErrorCode.EVENT_NOT_CLOSED, "Solo se pueden publicar resultados de eventos cerrados"
            )
        snapshot = await self._repo.latest_snapshot(event.id)
        if snapshot is None:  # pragma: no cover — cerrar el evento siempre crea una
            raise DomainError(ErrorCode.EVENT_NOT_CLOSED, "El evento no tiene instantánea")
        current = await self._repo.get_public_result(event.id)
        version = (current.version if current else 0) + 1
        document = build_public_view(
            snapshot, event.publication_settings, version=version, published_at=published_at
        )
        return document, version

    async def preview(self, organization_id: UUID, event_id: UUID) -> dict[str, Any]:
        """Exactamente el documento que se publicaría ahora, sin guardarlo."""
        event = await require_event(self._repo, organization_id, event_id)
        document, _ = await self._document(event, self._clock.now())
        return document

    async def publish(self, organization_id: UUID, event_id: UUID) -> PublishResult:
        event = await require_event(self._repo, organization_id, event_id)
        published_at = self._clock.now()
        document, version = await self._document(event, published_at)
        await self._repo.upsert_public_result(
            event_id=event.id,
            event_slug=event.slug,
            version=version,
            data=document,
            published_at=published_at,
        )
        # El sitio público debe leer el documento nuevo: se confirma antes de avisar.
        await self._repo.commit()
        revalidated = await self._revalidator.revalidate(event.slug)
        if not revalidated:
            logger.warning("publication_not_revalidated", event_id=str(event.id), version=version)
        return PublishResult(version=version, published_at=published_at, revalidated=revalidated)

    async def unpublish(self, organization_id: UUID, event_id: UUID) -> bool:
        """Idempotente: despublicar algo que no está publicado solo vuelve a avisar al sitio."""
        event = await require_event(self._repo, organization_id, event_id)
        await self._repo.unpublish(event.id)
        await self._repo.commit()
        return await self._revalidator.revalidate(event.slug)
