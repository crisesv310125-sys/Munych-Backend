"""Cableado del módulo de calificación (único lugar donde se crean los adaptadores)."""

from typing import Annotated

from fastapi import Depends

from munych_api.modules.audit.dependencies import AuditServiceDep
from munych_api.modules.scoring.application.get_progress import GetJudgeScores, GetProgress
from munych_api.modules.scoring.application.open_close_session import ManageSessions
from munych_api.modules.scoring.application.ports import Clock
from munych_api.modules.scoring.application.submit_scores import SubmitScores
from munych_api.modules.scoring.infrastructure.audit_adapter import AuditServiceAdapter
from munych_api.modules.scoring.infrastructure.sqlalchemy_scoring_repository import (
    SqlAlchemyScoringRepository,
)
from munych_api.shared.database import DbSession
from munych_api.shared.kernel import SystemClock


def get_clock() -> Clock:
    return SystemClock()


ClockDep = Annotated[Clock, Depends(get_clock)]


def get_repository(session: DbSession) -> SqlAlchemyScoringRepository:
    return SqlAlchemyScoringRepository(session)


RepositoryDep = Annotated[SqlAlchemyScoringRepository, Depends(get_repository)]


def get_submit_scores(
    repository: RepositoryDep, audit: AuditServiceDep, clock: ClockDep
) -> SubmitScores:
    return SubmitScores(repository, AuditServiceAdapter(audit), clock)


def get_manage_sessions(repository: RepositoryDep, clock: ClockDep) -> ManageSessions:
    return ManageSessions(repository, clock)


def get_progress_use_case(repository: RepositoryDep) -> GetProgress:
    return GetProgress(repository)


def get_judge_scores_use_case(repository: RepositoryDep) -> GetJudgeScores:
    return GetJudgeScores(repository)


SubmitScoresDep = Annotated[SubmitScores, Depends(get_submit_scores)]
ManageSessionsDep = Annotated[ManageSessions, Depends(get_manage_sessions)]
GetProgressDep = Annotated[GetProgress, Depends(get_progress_use_case)]
GetJudgeScoresDep = Annotated[GetJudgeScores, Depends(get_judge_scores_use_case)]
