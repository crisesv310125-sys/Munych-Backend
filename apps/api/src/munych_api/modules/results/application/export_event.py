"""Caso de uso: exportar los resultados del evento (Excel en el MVP)."""

from dataclasses import dataclass
from uuid import UUID

from munych_api.modules.results.application.close_event import committees_results, require_event
from munych_api.modules.results.application.ports import (
    Clock,
    ExportData,
    Exporter,
    ResultsRepository,
)


@dataclass(frozen=True, slots=True)
class ExportFile:
    filename: str
    media_type: str
    content: bytes


class ExportEvent:
    def __init__(self, repository: ResultsRepository, exporter: Exporter, clock: Clock) -> None:
        self._repo = repository
        self._exporter = exporter
        self._clock = clock

    async def execute(self, organization_id: UUID, event_id: UUID) -> ExportFile:
        event = await require_event(self._repo, organization_id, event_id)
        data = ExportData(
            event_name=event.name,
            venue=event.venue,
            starts_on=event.starts_on,
            ends_on=event.ends_on,
            timezone=event.timezone,
            generated_at=self._clock.now(),
            committees=await committees_results(self._repo, organization_id, event_id),
            details=await self._repo.score_details(event_id),
        )
        return ExportFile(
            filename=f"{event.slug}-resultados.{self._exporter.extension}",
            media_type=self._exporter.media_type,
            content=self._exporter.export(data),
        )
