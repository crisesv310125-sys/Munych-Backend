from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from munych_api.shared.auth import Role


class MeOut(BaseModel):
    user_id: UUID
    email: str | None
    role: Role | None
    full_name: str | None


class JudgeOut(BaseModel):
    judge_id: UUID
    email: str | None
    full_name: str
    active: bool


class JudgeInvitationOut(BaseModel):
    """Juez invitado que aún no abre el enlace de Supabase."""

    judge_id: UUID
    email: str | None
    full_name: str
    invited_at: datetime | None


class JudgeInvite(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    # Si se indica, el juez queda vinculado a ese evento (sale en `GET /judges?event_id=`).
    event_id: UUID | None = None


class JudgeUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    active: bool | None = None
