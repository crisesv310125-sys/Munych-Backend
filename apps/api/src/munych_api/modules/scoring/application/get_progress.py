"""Casos de uso de lectura: avance del comité y calificaciones propias del juez."""

from dataclasses import dataclass
from uuid import UUID

from munych_api.modules.scoring.application.ports import ScoringRepository
from munych_api.modules.scoring.domain.models import Score
from munych_api.shared.kernel import DomainError, ErrorCode, NotFoundError
from munych_api.shared.kernel.catalog import SessionStatus


@dataclass(frozen=True, slots=True)
class JudgeSessionProgress:
    judge_id: UUID
    full_name: str
    scored: int
    expected: int


@dataclass(frozen=True, slots=True)
class SessionProgress:
    number: int
    status: SessionStatus
    judges: list[JudgeSessionProgress]


class GetProgress:
    def __init__(self, repository: ScoringRepository) -> None:
        self._repo = repository

    async def execute(self, organization_id: UUID, committee_id: UUID) -> list[SessionProgress]:
        """Por sesión y juez asignado: celdas calificadas frente a delegados × criterios."""
        if await self._repo.get_committee(committee_id, organization_id) is None:
            raise NotFoundError("Comité no encontrado")
        data = await self._repo.progress(committee_id)
        expected = data.delegates_count * data.criteria_count
        return [
            SessionProgress(
                number=session.number,
                status=session.status,
                judges=[
                    JudgeSessionProgress(
                        judge_id=judge.judge_id,
                        full_name=judge.full_name,
                        scored=judge.scored_by_session.get(session.id, 0),
                        expected=expected,
                    )
                    for judge in data.judges
                ],
            )
            for session in data.sessions
        ]


class GetJudgeScores:
    def __init__(self, repository: ScoringRepository) -> None:
        self._repo = repository

    async def execute(self, judge_id: UUID, session_id: UUID) -> list[Score]:
        """Solo las calificaciones del propio juez: nunca las de otros jueces."""
        # TODO(cliente): confirmar si los jueces ven notas de otros (MVP: no).
        session = await self._repo.get_session(session_id)
        if session is None:
            raise NotFoundError("La sesión no existe")
        if not await self._repo.is_assigned(judge_id, session.committee_id):
            raise DomainError(ErrorCode.JUDGE_NOT_ASSIGNED, "No estás asignado a este comité")
        return await self._repo.judge_scores(judge_id, session_id)
