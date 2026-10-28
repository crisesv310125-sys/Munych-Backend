"""Caso de uso: ranking del comité con avisos de cupos de premios."""

from dataclasses import dataclass
from uuid import UUID

from munych_api.modules.results.application.ports import ResultsRepository
from munych_api.modules.results.domain.awards import quota_warnings
from munych_api.modules.results.domain.models import CommitteeData, RankingEntry
from munych_api.modules.results.domain.ranking import rank_committee
from munych_api.shared.kernel import NotFoundError


@dataclass(frozen=True, slots=True)
class CommitteeRanking:
    items: list[RankingEntry]
    quota_warnings: list[str]


async def require_committee_data(
    repository: ResultsRepository, organization_id: UUID, committee_id: UUID
) -> CommitteeData:
    data = await repository.committee_data(committee_id, organization_id)
    if data is None:
        raise NotFoundError("Comité no encontrado")
    return data


class ComputeRanking:
    def __init__(self, repository: ResultsRepository) -> None:
        self._repo = repository

    async def execute(self, organization_id: UUID, committee_id: UUID) -> CommitteeRanking:
        data = await require_committee_data(self._repo, organization_id, committee_id)
        awards = await self._repo.get_awards(committee_id)
        return CommitteeRanking(
            items=rank_committee(data),
            quota_warnings=quota_warnings(awards, data.committee.award_quotas),
        )
