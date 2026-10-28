"""Casos de uso: ver y reemplazar los premios de un comité (asignación manual)."""

from dataclasses import dataclass
from uuid import UUID

from munych_api.modules.results.application.compute_ranking import require_committee_data
from munych_api.modules.results.application.ports import AwardsAudit, Clock, ResultsRepository
from munych_api.modules.results.domain.awards import quota_warnings, sort_awards, validate_awards
from munych_api.modules.results.domain.models import Award
from munych_api.shared.kernel import DomainError, ErrorCode


@dataclass(frozen=True, slots=True)
class CommitteeAwards:
    items: list[Award]
    quota_warnings: list[str]


def _audit_view(awards: list[Award]) -> list[dict[str, object]]:
    return [
        {"award_type": a.award_type, "delegation_id": str(a.delegation_id), "position": a.position}
        for a in sort_awards(awards)
    ]


class ManageAwards:
    def __init__(self, repository: ResultsRepository, audit: AwardsAudit, clock: Clock) -> None:
        self._repo = repository
        self._audit = audit
        self._clock = clock

    async def get(self, organization_id: UUID, committee_id: UUID) -> CommitteeAwards:
        data = await require_committee_data(self._repo, organization_id, committee_id)
        awards = sort_awards(await self._repo.get_awards(committee_id))
        return CommitteeAwards(awards, quota_warnings(awards, data.committee.award_quotas))

    async def replace(
        self, organization_id: UUID, committee_id: UUID, awards: list[Award], actor_id: UUID
    ) -> CommitteeAwards:
        """Reemplaza todos los premios. Superar un cupo genera un aviso, no un error."""
        data = await require_committee_data(self._repo, organization_id, committee_id)
        if data.committee.event_closed:
            raise DomainError(ErrorCode.EVENT_CLOSED, "El evento está cerrado")
        validate_awards(awards, (d.id for d in data.delegations))

        before = await self._repo.get_awards(committee_id)
        await self._repo.replace_awards(committee_id, awards, actor_id, self._clock.now())
        await self._audit.record_awards_change(
            actor_id=actor_id,
            committee_id=committee_id,
            before=_audit_view(before),
            after=_audit_view(awards),
        )
        items = sort_awards(awards)
        return CommitteeAwards(items, quota_warnings(items, data.committee.award_quotas))
