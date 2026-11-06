"""Reglas de la calificación por lotes (sección 6.2). Funciones puras."""

from dataclasses import dataclass
from enum import StrEnum

from munych_api.modules.scoring.domain.models import Score, ScoreSubmission, SessionContext
from munych_api.shared.kernel import ErrorCode
from munych_api.shared.kernel.catalog import EVENT_TYPES


@dataclass(frozen=True, slots=True)
class Rejection:
    code: ErrorCode
    detail: str


def validate_submission(  # noqa: PLR0911 — una regla por cláusula de guarda
    item: ScoreSubmission, context: SessionContext | None, committee_role: str | None
) -> Rejection | None:
    """Valida un ítem por separado; un ítem inválido no invalida el resto del lote.

    `committee_role` es el rol de la cuenta en el comité (`None`: no asignada).
    """
    if context is None:
        return Rejection(ErrorCode.NOT_FOUND, "La sesión no existe")
    if committee_role is None:
        return Rejection(ErrorCode.JUDGE_NOT_ASSIGNED, "No estás asignado a este comité")
    if EVENT_TYPES[context.event_type].account_voter_role(committee_role) is None:
        return Rejection(
            ErrorCode.FORBIDDEN,
            f"Tu rol en este comité ({committee_role}) no califica en este tipo de evento",
        )
    if context.event_closed:
        return Rejection(ErrorCode.EVENT_CLOSED, "El evento está cerrado")
    if not context.session.is_open:
        return Rejection(
            ErrorCode.SESSION_CLOSED, f"La sesión {context.session.number} está cerrada"
        )
    if item.delegate_id not in context.delegate_ids:
        return Rejection(ErrorCode.NOT_FOUND, "El delegado no pertenece a este comité")
    if item.criterion_id not in context.criterion_ids:
        return Rejection(ErrorCode.NOT_FOUND, "El criterio no pertenece a la rúbrica del comité")
    if not context.scale_min <= item.value <= context.scale_max:
        return Rejection(
            ErrorCode.VALUE_OUT_OF_RANGE,
            f"El valor {item.value} está fuera de la escala "
            f"{context.scale_min}–{context.scale_max}",
        )
    return None


class Outcome(StrEnum):
    INSERT = "insert"
    UPDATE = "update"
    UNCHANGED = "unchanged"
    """Reintento de un ítem ya guardado con los mismos datos."""
    STALE = "stale"
    """El ítem es más antiguo que lo guardado: gana la última escritura del juez."""
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class Decision:
    outcome: Outcome
    target: Score | None = None
    rejection: Rejection | None = None


def decide(item: ScoreSubmission, by_client_id: Score | None, by_key: Score | None) -> Decision:
    """Idempotencia del lote: upsert por celda y última escritura gana.

    - `by_client_id`: calificación guardada con el mismo `client_id`.
    - `by_key`: calificación guardada en la misma celda (juez, delegado, sesión, criterio).
    """
    if by_client_id is not None and by_client_id.key != item.key:
        return Decision(
            Outcome.REJECT,
            rejection=Rejection(
                ErrorCode.VALIDATION_ERROR, "El client_id ya se usó para otra calificación"
            ),
        )
    target = by_client_id or by_key
    if target is None:
        return Decision(Outcome.INSERT)
    if item.client_updated_at < target.client_updated_at:
        return Decision(Outcome.STALE, target)
    if (
        item.client_id == target.client_id
        and item.value == target.value
        and item.comment == target.comment
    ):
        return Decision(Outcome.UNCHANGED, target)
    return Decision(Outcome.UPDATE, target)
