"""Entidades de calificación. Dominio puro: sin frameworks ni acceso a datos."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from munych_api.shared.kernel.catalog import SessionStatus

# (judge_id, delegate_id, session_id, criterion_id): una calificación por celda.
ScoreKey = tuple[UUID, UUID, UUID, UUID]


@dataclass(frozen=True, slots=True)
class ScoreSubmission:
    """Un ítem del lote enviado por el juez."""

    client_id: UUID
    judge_id: UUID
    delegate_id: UUID
    session_id: UUID
    criterion_id: UUID
    value: int
    comment: str | None
    client_updated_at: datetime

    @property
    def key(self) -> ScoreKey:
        return (self.judge_id, self.delegate_id, self.session_id, self.criterion_id)


@dataclass(frozen=True, slots=True)
class Score:
    """Calificación guardada."""

    id: UUID
    client_id: UUID
    judge_id: UUID
    delegate_id: UUID
    session_id: UUID
    criterion_id: UUID
    value: int
    comment: str | None
    client_updated_at: datetime
    updated_at: datetime | None = None

    @property
    def key(self) -> ScoreKey:
        return (self.judge_id, self.delegate_id, self.session_id, self.criterion_id)

    def audit_view(self) -> dict[str, object]:
        return {
            "client_id": str(self.client_id),
            "value": self.value,
            "comment": self.comment,
            "client_updated_at": self.client_updated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ScoringSession:
    id: UUID
    committee_id: UUID
    number: int
    status: SessionStatus
    opened_at: datetime | None
    closed_at: datetime | None

    @property
    def is_open(self) -> bool:
        return self.status == "open"


@dataclass(frozen=True, slots=True)
class SessionContext:
    """Todo lo necesario para validar un ítem de una sesión."""

    session: ScoringSession
    event_closed: bool
    scale_min: int
    scale_max: int
    criterion_ids: frozenset[UUID]
    delegate_ids: frozenset[UUID]
