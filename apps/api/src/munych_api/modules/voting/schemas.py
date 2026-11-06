from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from munych_api.shared.kernel.catalog import EventStatus

TokenStatus = Literal["none", "active", "revoked", "expired"]

# ---------------------------------------------------------------- accesos (admin)


class VoterAccessOut(BaseModel):
    """Estado del acceso de un delegado. Nunca incluye el token."""

    delegate_id: UUID
    full_name: str
    delegation_id: UUID
    country_code: str | None
    character_name: str | None
    committee_id: UUID
    committee_name: str
    committee_acronym: str
    status: TokenStatus
    issued_at: datetime | None
    last_used_at: datetime | None
    votes_count: int = Field(description="Votos (celdas criterio × delegación) que ha emitido")


class GenerateTokensIn(BaseModel):
    link_base: Annotated[str, Field(min_length=10, max_length=300)] = Field(
        description="Prefijo del enlace de votación; el token se añade al final. "
        "Ej.: https://panel.grandinternational.mx/#/votar/",
        examples=["https://panel.grandinternational.mx/#/votar/"],
    )
    delegate_ids: list[UUID] | None = Field(
        default=None,
        description="Delegados a los que se genera (o regenera) el acceso. "
        "Si se omite: todos los delegados del evento que no tienen un acceso vigente",
        max_length=5000,
    )

    @field_validator("link_base")
    @classmethod
    def _https(cls, value: str) -> str:
        local = value.startswith(("http://localhost", "http://127.0.0.1"))
        if not (value.startswith("https://") or local):
            raise ValueError("link_base debe empezar con https://")
        return value


class GeneratedTokenOut(BaseModel):
    """Acceso recién generado. El token **solo** se devuelve aquí, una vez."""

    delegate_id: UUID
    full_name: str
    country_code: str | None
    character_name: str | None
    committee_name: str
    committee_acronym: str
    token: str
    url: str
    qr_svg: str = Field(description="QR del enlace como SVG en línea")
    expires_at: datetime


class RevokeTokensIn(BaseModel):
    delegate_ids: list[UUID] = Field(min_length=1, max_length=5000)


class RevokeTokensOut(BaseModel):
    revoked: int


# ---------------------------------------------------------------- boleta (delegado)


class BallotCriterionOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    weight: float
    position: int
    level_descriptors: dict[str, str]


class BallotRubricOut(BaseModel):
    scale_min: int
    scale_max: int
    criteria: list[BallotCriterionOut]


class BallotDelegationOut(BaseModel):
    delegation_id: UUID
    country_code: str | None
    character_name: str | None


class BallotVoteOut(BaseModel):
    delegation_id: UUID
    criterion_id: UUID
    value: int


class BallotSessionOut(BaseModel):
    session_id: UUID
    number: int
    opened_at: datetime | None


class BallotOut(BaseModel):
    """Lo que ve el delegado: por quién puede votar y sus votos de la sesión abierta."""

    voter_name: str
    own_delegation: BallotDelegationOut
    event_name: str
    event_status: EventStatus
    committee_name: str
    committee_acronym: str
    open_session: BallotSessionOut | None = Field(
        description="La sesión en la que caen los votos. null: no hay sesión abierta"
    )
    rubric: BallotRubricOut | None
    delegations: list[BallotDelegationOut] = Field(
        description="Delegaciones por las que puede votar (todas las del comité menos la suya)"
    )
    votes: list[BallotVoteOut] = Field(description="Sus votos en la sesión abierta")


class VoteIn(BaseModel):
    delegation_id: UUID
    criterion_id: UUID
    value: int


class VotesIn(BaseModel):
    """Votos de la sesión abierta. El servidor decide la sesión; el celular no la manda."""

    items: list[VoteIn] = Field(min_length=1, max_length=2000)
