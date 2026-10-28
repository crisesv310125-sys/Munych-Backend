"""Caso de uso: lote de calificaciones idempotente (sección 7.3)."""

from dataclasses import dataclass, field, replace
from uuid import UUID

from munych_api.modules.scoring.application.ports import (
    AuditLog,
    Clock,
    ConcurrentWriteError,
    ScoringRepository,
)
from munych_api.modules.scoring.domain.models import ScoreSubmission, SessionContext
from munych_api.modules.scoring.domain.rules import (
    Outcome,
    Rejection,
    decide,
    validate_submission,
)
from munych_api.shared.kernel import ErrorCode


@dataclass(frozen=True, slots=True)
class RejectedItem:
    client_id: UUID
    code: ErrorCode
    detail: str


@dataclass(slots=True)
class BatchResult:
    accepted: list[UUID] = field(default_factory=list)
    rejected: list[RejectedItem] = field(default_factory=list)


class SubmitScores:
    def __init__(self, repository: ScoringRepository, audit: AuditLog, clock: Clock) -> None:
        self._repo = repository
        self._audit = audit
        self._clock = clock

    async def execute(self, items: list[ScoreSubmission]) -> BatchResult:
        """Procesa los ítems en orden; cada uno se acepta o se rechaza por separado.

        Un ítem más antiguo que lo guardado se **acepta sin cambios**: el cliente
        puede dejar de reintentarlo y gana la última escritura del mismo juez.
        """
        result = BatchResult()
        contexts: dict[UUID, SessionContext | None] = {}
        assignments: dict[tuple[UUID, UUID], bool] = {}
        now = self._clock.now()

        for raw in items:
            # Un reloj de cliente adelantado no puede bloquear ediciones posteriores.
            item = replace(raw, client_updated_at=min(raw.client_updated_at, now))

            if item.session_id not in contexts:
                contexts[item.session_id] = await self._repo.session_context(item.session_id)
            context = contexts[item.session_id]
            assigned = False
            if context is not None:
                key = (item.judge_id, context.session.committee_id)
                if key not in assignments:
                    assignments[key] = await self._repo.is_assigned(*key)
                assigned = assignments[key]

            rejection = validate_submission(item, context, assigned)
            if rejection is None:
                rejection = await self._apply(item)
            if rejection is None:
                result.accepted.append(item.client_id)
            else:
                result.rejected.append(
                    RejectedItem(item.client_id, rejection.code, rejection.detail)
                )
        return result

    async def _apply(self, item: ScoreSubmission) -> Rejection | None:
        by_client_id = await self._repo.get_by_client_id(item.client_id)
        by_key = None if by_client_id is not None else await self._repo.get_by_key(item.key)
        decision = decide(item, by_client_id, by_key)

        try:
            if decision.outcome is Outcome.INSERT:
                score = await self._repo.insert(item)
                await self._audit.record_score_change(
                    actor_id=item.judge_id,
                    score_id=score.id,
                    action="create",
                    before=None,
                    after=score.audit_view(),
                )
            elif decision.outcome is Outcome.UPDATE and decision.target is not None:
                score = await self._repo.update(decision.target.id, item)
                await self._audit.record_score_change(
                    actor_id=item.judge_id,
                    score_id=score.id,
                    action="update",
                    before=decision.target.audit_view(),
                    after=score.audit_view(),
                )
        except ConcurrentWriteError:
            return Rejection(
                ErrorCode.CONFLICT, "Otra petición guardó esta calificación a la vez; reintenta"
            )
        return decision.rejection
