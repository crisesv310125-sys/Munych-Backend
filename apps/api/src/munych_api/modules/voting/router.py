from uuid import UUID

from fastapi import APIRouter, Request

from munych_api.modules.voting.dependencies import CurrentVoter, VotingServiceDep
from munych_api.modules.voting.schemas import (
    BallotOut,
    CommitteePeerVoteOut,
    GeneratedTokenOut,
    GenerateTokensIn,
    PeerVotesIn,
    PeerVoteWindowIn,
    PeerVoteWindowOut,
    RevokeTokensIn,
    RevokeTokensOut,
    VoterAccessOut,
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


# ---------------------------------------------------------------- voto entre pares (admin)


@router.get("/events/{event_id}/peer-vote")
async def list_peer_vote_windows(
    event_id: UUID, _: AdminUser, organization_id: OrganizationId, service: VotingServiceDep
) -> list[CommitteePeerVoteOut]:
    """Estado del voto entre pares de cada comité del evento y cuántos delegados ya votaron."""
    return await service.list_windows(organization_id, event_id)


@router.put("/committees/{committee_id}/peer-vote")
async def open_peer_vote(
    committee_id: UUID,
    body: PeerVoteWindowIn,
    _: AdminUser,
    organization_id: OrganizationId,
    service: VotingServiceDep,
) -> PeerVoteWindowOut:
    """Abre el voto entre pares del comité (ahora o a una hora programada).

    Se usa al terminar la última sesión. Reabrir uno cerrado quita el cierre anterior;
    los votos ya enviados se conservan.
    """
    return await service.open_window(organization_id, committee_id, body)


@router.post("/committees/{committee_id}/peer-vote/close")
async def close_peer_vote(
    committee_id: UUID, _: AdminUser, organization_id: OrganizationId, service: VotingServiceDep
) -> PeerVoteWindowOut:
    """Cierra ya el voto entre pares del comité."""
    return await service.close_window(organization_id, committee_id)


# ---------------------------------------------------------------- boleta (delegado)


@router.get("/vote/ballot")
@limiter.limit(BALLOT_LIMIT, key_func=voter_key)
async def get_ballot(request: Request, voter: CurrentVoter, service: VotingServiceDep) -> BallotOut:
    """Boleta entre pares del delegado autenticado con su token. Se consulta cada 15-30 s."""
    return await service.ballot(voter)


@router.post("/vote/ballot")
@limiter.limit(VOTES_LIMIT, key_func=voter_key)
async def submit_peer_vote(
    request: Request, body: PeerVotesIn, voter: CurrentVoter, service: VotingServiceDep
) -> BallotOut:
    """Envía el voto entre pares (Mejor delegado, Delegado distinguido, Mención honorífica).

    Una sola vez y sin cambios: un segundo envío responde 409 CONFLICT.
    """
    return await service.vote(voter, body.picks)
