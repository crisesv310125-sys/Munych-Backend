from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from munych_api.shared.kernel.catalog import SessionStatus

MAX_BATCH_ITEMS = 500

# ---------------------------------------------------------------- lote


class ScoreItemIn(BaseModel):
    client_id: UUID = Field(description="Id generado por el cliente; hace idempotente el reintento")
    delegate_id: UUID
    session_id: UUID
    criterion_id: UUID
    # Rango de smallint: la escala de la rúbrica se valida por ítem (VALUE_OUT_OF_RANGE).
    value: int = Field(ge=-32768, le=32767)
    comment: str | None = Field(default=None, max_length=2000)
    client_updated_at: AwareDatetime


class ScoresBatchIn(BaseModel):
    items: list[ScoreItemIn] = Field(min_length=1, max_length=MAX_BATCH_ITEMS)


class RejectedScoreOut(BaseModel):
    client_id: UUID
    code: str
    detail: str


class ScoresBatchOut(BaseModel):
    accepted: list[UUID]
    rejected: list[RejectedScoreOut]


class ScoreOut(BaseModel):
    client_id: UUID
    delegate_id: UUID
    session_id: UUID
    criterion_id: UUID
    value: int
    comment: str | None
    client_updated_at: datetime
    updated_at: datetime | None


# ---------------------------------------------------------------- sesiones y avance


class SessionOut(BaseModel):
    id: UUID
    committee_id: UUID
    number: int
    status: SessionStatus
    opened_at: datetime | None
    closed_at: datetime | None


class JudgeProgressOut(BaseModel):
    judge_id: UUID
    full_name: str
    scored: int
    expected: int


class SessionProgressOut(BaseModel):
    number: int
    status: SessionStatus
    judges: list[JudgeProgressOut]


class ProgressOut(BaseModel):
    sessions: list[SessionProgressOut]
