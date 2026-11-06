from uuid import UUID

from fastapi import APIRouter, Request

from munych_api.modules.voting.dependencies import CurrentVoter, VotingServiceDep
from munych_api.modules.voting.schemas import (
    BallotOut,
    GeneratedTokenOut,
    GenerateTokensIn,
    RevokeTokensIn,
    RevokeTokensOut,
    VoterAccessOut,
    VotesIn,
)
from munych_api.shared.auth import AdminUser, OrganizationId
from munych_api.shared.rate_limit import BALLOT_LIMIT, VOTES_LIMIT, limiter, voter_key

router = APIRouter(tags=["voting"])


# ---------------------------------------------------------------- accesos (admin)


@router.get("/events/{event_id}/voter-tokens")
async def list_voter_tokens(
    event_id: UUID, _: AdminUser, organization_id: OrganizationId, service: VotingServiceDep
) -> list[VoterAccessOut]:
    """Delegados del evento y el estado de su acceso de votación (sin los tokens)."""
    return await service.list_access(organization_id, event_id)


@router.post("/events/{event_id}/voter-tokens", status_code=201)
async def generate_voter_tokens(
    event_id: UUID,
    body: GenerateTokensIn,
    user: AdminUser,
    organization_id: OrganizationId,
    service: VotingServiceDep,
) -> list[GeneratedTokenOut]:
    """Genera accesos (enlace + QR). Los tokens solo se devuelven aquí: descárgalos ya.

    Sin `delegate_ids`, genera para quien no tenga un acceso vigente. Con `delegate_ids`,
    regenera esos accesos y revoca los anteriores.
    """
    return await service.generate(organization_id, event_id, body, user.user_id)


@router.post("/events/{event_id}/voter-tokens/revoke")
async def revoke_voter_tokens(
    event_id: UUID,
    body: RevokeTokensIn,
    _: AdminUser,
    organization_id: OrganizationId,
    service: VotingServiceDep,
) -> RevokeTokensOut:
    return RevokeTokensOut(
        revoked=await service.revoke(organization_id, event_id, body.delegate_ids)
    )


# ---------------------------------------------------------------- boleta (delegado)


@router.get("/vote/ballot")
@limiter.limit(BALLOT_LIMIT, key_func=voter_key)
async def get_ballot(request: Request, voter: CurrentVoter, service: VotingServiceDep) -> BallotOut:
    """Boleta del delegado autenticado con su token. Se consulta cada 15-30 s."""
    return await service.ballot(voter)


@router.put("/vote/ballot")
@limiter.limit(VOTES_LIMIT, key_func=voter_key)
async def submit_votes(
    request: Request, body: VotesIn, voter: CurrentVoter, service: VotingServiceDep
) -> BallotOut:
    """Guarda los votos en la sesión abierta (la decide el servidor) y devuelve la boleta."""
    return await service.vote(voter, body.items)
