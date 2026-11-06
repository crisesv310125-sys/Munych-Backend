from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from munych_api.modules.voting.repository import VotingRepository
from munych_api.modules.voting.service import INVALID_ACCESS, Voter, VotingService
from munych_api.shared.database import DbSession
from munych_api.shared.kernel import DomainError, ErrorCode, SystemClock


def get_voting_service(session: DbSession) -> VotingService:
    return VotingService(VotingRepository(session), SystemClock())


VotingServiceDep = Annotated[VotingService, Depends(get_voting_service)]

_voter_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="VoterToken",
    description="Token de acceso del delegado (el del enlace o QR), no un JWT",
)


async def get_voter(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_voter_bearer)],
    service: VotingServiceDep,
) -> Voter:
    if credentials is None:
        raise DomainError(ErrorCode.UNAUTHORIZED, INVALID_ACCESS)
    return await service.authenticate(credentials.credentials)


CurrentVoter = Annotated[Voter, Depends(get_voter)]
