from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Path, Request

from munych_api.modules.scoring.api.dependencies import (
    GetJudgeScoresDep,
    GetProgressDep,
    ManageSessionsDep,
    SubmitScoresDep,
)
from munych_api.modules.scoring.api.schemas import (
    ProgressOut,
    RejectedScoreOut,
    ScoreOut,
    ScoresBatchIn,
    ScoresBatchOut,
    SessionOut,
    SessionProgressOut,
)
from munych_api.modules.scoring.domain.models import ScoreSubmission, ScoringSession
from munych_api.shared.auth import AdminUser, JudgeUser, OrganizationId
from munych_api.shared.rate_limit import SCORES_BATCH_LIMIT, limiter

router = APIRouter(tags=["scoring"])

SessionNumber = Path(ge=1, le=20)


def _session_out(session: ScoringSession) -> SessionOut:
    return SessionOut(**asdict(session))


# ---------------------------------------------------------------- administración


@router.get("/committees/{committee_id}/sessions")
async def list_committee_sessions(
    committee_id: UUID, _: AdminUser, organization_id: OrganizationId, sessions: ManageSessionsDep
) -> list[SessionOut]:
    return [_session_out(s) for s in await sessions.list(organization_id, committee_id)]


@router.post("/committees/{committee_id}/sessions/{number}/open")
async def open_session(
    committee_id: UUID,
    _: AdminUser,
    organization_id: OrganizationId,
    sessions: ManageSessionsDep,
    number: int = SessionNumber,
) -> SessionOut:
    return _session_out(await sessions.open(organization_id, committee_id, number))


@router.post("/committees/{committee_id}/sessions/{number}/close")
async def close_session(
    committee_id: UUID,
    _: AdminUser,
    organization_id: OrganizationId,
    sessions: ManageSessionsDep,
    number: int = SessionNumber,
) -> SessionOut:
    return _session_out(await sessions.close(organization_id, committee_id, number))


@router.get("/committees/{committee_id}/progress")
async def get_committee_progress(
    committee_id: UUID, _: AdminUser, organization_id: OrganizationId, progress: GetProgressDep
) -> ProgressOut:
    """Avance por sesión y juez. El frontend lo consulta periódicamente (polling)."""
    sessions = await progress.execute(organization_id, committee_id)
    return ProgressOut(sessions=[SessionProgressOut.model_validate(asdict(s)) for s in sessions])


# ---------------------------------------------------------------- panel del juez


@router.get("/judge/sessions/{session_id}/scores")
async def list_my_session_scores(
    session_id: UUID, user: JudgeUser, use_case: GetJudgeScoresDep
) -> list[ScoreOut]:
    """Calificaciones del juez autenticado en la sesión (nunca las de otros jueces)."""
    scores = await use_case.execute(user.user_id, session_id)
    return [ScoreOut.model_validate(s, from_attributes=True) for s in scores]


@router.post("/judge/scores/batch")
@limiter.limit(SCORES_BATCH_LIMIT)
async def submit_scores_batch(
    request: Request, body: ScoresBatchIn, user: JudgeUser, use_case: SubmitScoresDep
) -> ScoresBatchOut:
    """Lote idempotente: cada ítem se acepta o se rechaza por separado."""
    result = await use_case.execute(
        [ScoreSubmission(judge_id=user.user_id, **item.model_dump()) for item in body.items]
    )
    return ScoresBatchOut(
        accepted=result.accepted,
        rejected=[
            RejectedScoreOut(client_id=r.client_id, code=r.code, detail=r.detail)
            for r in result.rejected
        ],
    )
