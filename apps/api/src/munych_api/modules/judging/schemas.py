from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from munych_api.shared.kernel.catalog import CommitteeType, DelegationMode, JudgeRole, SessionStatus

# ---------------------------------------------------------------- asignaciones (admin)


class AssignmentIn(BaseModel):
    judge_id: UUID
    role: JudgeRole = "judge"


class AssignmentOut(BaseModel):
    judge_id: UUID
    role: JudgeRole
    full_name: str
    email: str | None
    active: bool


# ---------------------------------------------------------------- panel del juez


class JudgeEventOut(BaseModel):
    name: str
    logo_url: str | None
    timezone: str


class JudgeCommitteeOut(BaseModel):
    committee_id: UUID
    name: str
    acronym: str
    event: JudgeEventOut
    role: JudgeRole


class JudgeDelegateOut(BaseModel):
    delegate_id: UUID
    full_name: str


class JudgeDelegationOut(BaseModel):
    delegation_id: UUID
    country_code: str | None
    character_name: str | None
    institution: str | None
    delegates: list[JudgeDelegateOut]


class JudgeCriterionOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    weight: float
    position: int
    level_descriptors: dict[str, str]


class JudgeRubricOut(BaseModel):
    id: UUID
    name: str
    scale_min: int
    scale_max: int
    criteria: list[JudgeCriterionOut]


class JudgeSessionOut(BaseModel):
    session_id: UUID
    number: int
    status: SessionStatus
    opened_at: datetime | None
    closed_at: datetime | None


class JudgeCommitteeDetailOut(BaseModel):
    committee_id: UUID
    name: str
    acronym: str
    type: CommitteeType
    delegation_mode: DelegationMode
    role: JudgeRole
    event: JudgeEventOut
    event_closed: bool
    delegations: list[JudgeDelegationOut]
    rubric: JudgeRubricOut | None
    sessions: list[JudgeSessionOut]
