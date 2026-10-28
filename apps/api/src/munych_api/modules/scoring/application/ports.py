"""Puertos del módulo de calificación (los implementa `infrastructure/`)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from munych_api.modules.scoring.domain.models import (
    Score,
    ScoreKey,
    ScoreSubmission,
    ScoringSession,
    SessionContext,
)


class ConcurrentWriteError(Exception):
    """Otra petición escribió la misma calificación a la vez."""


@dataclass(frozen=True, slots=True)
class CommitteeInfo:
    id: UUID
    event_closed: bool


@dataclass(frozen=True, slots=True)
class JudgeProgress:
    judge_id: UUID
    full_name: str
    scored_by_session: dict[UUID, int]


@dataclass(frozen=True, slots=True)
class ProgressData:
    sessions: list[ScoringSession]
    delegates_count: int
    criteria_count: int
    judges: list[JudgeProgress]


class ScoringRepository(Protocol):
    # ---------------------------------------------------------------- lote
    async def session_context(self, session_id: UUID) -> SessionContext | None: ...

    async def is_assigned(self, judge_id: UUID, committee_id: UUID) -> bool: ...

    async def get_by_client_id(self, client_id: UUID) -> Score | None: ...

    async def get_by_key(self, key: ScoreKey) -> Score | None: ...

    async def insert(self, item: ScoreSubmission) -> Score:
        """Lanza `ConcurrentWriteError` si la celda o el client_id ya existen."""
        ...

    async def update(self, score_id: UUID, item: ScoreSubmission) -> Score: ...

    # ---------------------------------------------------------------- lecturas
    async def judge_scores(self, judge_id: UUID, session_id: UUID) -> list[Score]: ...

    async def get_session(self, session_id: UUID) -> ScoringSession | None: ...

    # ---------------------------------------------------------------- sesiones (admin)
    async def get_committee(
        self, committee_id: UUID, organization_id: UUID
    ) -> CommitteeInfo | None: ...

    async def list_sessions(self, committee_id: UUID) -> list[ScoringSession]: ...

    async def get_session_by_number(
        self, committee_id: UUID, number: int
    ) -> ScoringSession | None: ...

    async def save_session(self, session: ScoringSession) -> None: ...

    async def progress(self, committee_id: UUID) -> ProgressData: ...


class AuditLog(Protocol):
    async def record_score_change(
        self,
        *,
        actor_id: UUID,
        score_id: UUID,
        action: str,
        before: dict[str, Any] | None,
        after: dict[str, Any],
    ) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
