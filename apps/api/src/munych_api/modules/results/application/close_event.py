"""Caso de uso: cerrar el evento con una instantánea inmutable (sección 6.5)."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from munych_api.modules.results.application.compute_ranking import require_committee_data
from munych_api.modules.results.application.ports import (
    Clock,
    CommitteeResults,
    PublicUrls,
    ResultsRepository,
)
from munych_api.modules.results.domain.models import EventInfo
from munych_api.modules.results.domain.ranking import rank_committee
from munych_api.modules.results.domain.snapshot import build_snapshot
from munych_api.shared.kernel import DomainError, ErrorCode, NotFoundError


@dataclass(frozen=True, slots=True)
class ClosedEvent:
    event_id: UUID
    snapshot_id: UUID
    closed_at: datetime


async def require_event(
    repository: ResultsRepository, organization_id: UUID, event_id: UUID
) -> EventInfo:
    event = await repository.get_event(event_id, organization_id)
    if event is None:
        raise NotFoundError("Evento no encontrado")
    return event


async def committees_results(
    repository: ResultsRepository, organization_id: UUID, event_id: UUID
) -> list[CommitteeResults]:
    results = []
    for committee_id in await repository.committee_ids(event_id):
        data = await require_committee_data(repository, organization_id, committee_id)
        results.append(
            CommitteeResults(
                committee=data.committee,
                ranking=rank_committee(data),
                awards=await repository.get_awards(committee_id),
            )
        )
    return results


class CloseEvent:
    def __init__(self, repository: ResultsRepository, urls: PublicUrls, clock: Clock) -> None:
        self._repo = repository
        self._urls = urls
        self._clock = clock

    async def execute(self, organization_id: UUID, event_id: UUID, actor_id: UUID) -> ClosedEvent:
        """Exige todas las sesiones cerradas; después no se admiten más escrituras."""
        event = await require_event(self._repo, organization_id, event_id)
        if event.closed:
            raise DomainError(ErrorCode.EVENT_CLOSED, "El evento ya está cerrado")
        open_sessions = await self._repo.open_sessions_count(event_id)
        if open_sessions:
            raise DomainError(
                ErrorCode.SESSIONS_STILL_OPEN,
                f"No se puede cerrar el evento: quedan {open_sessions} sesiones abiertas",
            )

        closed_at = self._clock.now()
        committees = await committees_results(self._repo, organization_id, event_id)
        snapshot = build_snapshot(
            event,
            self._urls.logo_url(event.logo_path),
            [(c.committee, c.ranking, c.awards) for c in committees],
            event.publication_settings,
            closed_at,
        )
        snapshot_id, created_at = await self._repo.insert_snapshot(event_id, snapshot, actor_id)
        await self._repo.close_event(event_id)
        return ClosedEvent(event_id=event_id, snapshot_id=snapshot_id, closed_at=created_at)
