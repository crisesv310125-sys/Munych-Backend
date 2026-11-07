from uuid import UUID

from munych_api.modules.voting.service import VotingService


class PeerVoteAdapter:
    """Implementa el puerto `PeerVote` con el servicio público del módulo `voting`."""

    def __init__(self, service: VotingService) -> None:
        self._service = service

    async def open_with_session(self, organization_id: UUID, committee_id: UUID) -> None:
        await self._service.open_with_session(organization_id, committee_id)
