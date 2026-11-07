from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from munych_api.shared.kernel.catalog import EventStatus, PeerAwardType

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
    votes_count: int = Field(description="Premios que ha votado (0 si aún no envía su boleta)")


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
    code: str = Field(
        description="Código corto de respaldo (p. ej. K7M2Q-9XH4T) para escribirlo a mano "
        "si la cámara no lee el QR. Sirve igual que el token; solo llega aquí, una vez."
    )
    url: str
    qr_svg: str = Field(description="QR del enlace como SVG en línea")
    expires_at: datetime


class RevokeTokensIn(BaseModel):
    delegate_ids: list[UUID] = Field(min_length=1, max_length=5000)


class RevokeTokensOut(BaseModel):
    revoked: int


# ---------------------------------------------------------------- ventana del voto entre pares

PeerVoteStatus = Literal["not_scheduled", "scheduled", "open", "closed"]
"""Estado del voto entre pares de un comité, derivado de sus fechas y del evento."""


class PeerVoteWindowOut(BaseModel):
    status: PeerVoteStatus
    opens_at: datetime | None
    closes_at: datetime | None = Field(description="null: abierto hasta que el admin lo cierre")


class PeerVoteWindowIn(BaseModel):
    """Abre o programa el voto entre pares de un comité."""

    opens_at: datetime | None = Field(
        default=None, description="Apertura. null: ahora mismo (hora del servidor)"
    )
    closes_at: datetime | None = Field(
        default=None, description="Cierre programado. null: hasta que el admin lo cierre"
    )


class CommitteePeerVoteOut(PeerVoteWindowOut):
    """Estado del voto entre pares de un comité, para el admin."""

    committee_id: UUID
    committee_name: str
    committee_acronym: str
    voters: int = Field(description="Delegados del comité")
    submitted: int = Field(description="Delegados que ya enviaron su voto")


# ---------------------------------------------------------------- boleta (delegado)


class BallotDelegationOut(BaseModel):
    delegation_id: UUID
    country_code: str | None
    character_name: str | None


class BallotAwardOut(BaseModel):
    """Un premio de la boleta, en el orden en que se vota."""

    award_type: PeerAwardType
    label: str
    points: int


class BallotPickOut(BaseModel):
    award_type: PeerAwardType
    delegation_id: UUID


class BallotOut(BaseModel):
    """Boleta entre pares: el delegado elige una delegación por premio, una sola vez."""

    voter_name: str
    own_delegation: BallotDelegationOut
    event_name: str
    event_slug: str = Field(description="Para enlazar a los resultados públicos del evento")
    event_status: EventStatus
    committee_name: str
    committee_acronym: str
    sessions_total: int = Field(description="Sesiones previstas del comité")
    sessions_closed: int = Field(description="Sesiones del comité ya cerradas")
    peer_vote: PeerVoteWindowOut
    weight: float = Field(description="Peso (%) del voto de los delegados en el puntaje final")
    awards: list[BallotAwardOut] = Field(
        description="Premios a votar, en orden. Menos de 3 si el comité tiene pocas delegaciones"
    )
    delegations: list[BallotDelegationOut] = Field(
        description="Delegaciones por las que puede votar (todas las del comité menos la suya)"
    )
    picks: list[BallotPickOut] = Field(description="Su voto enviado. Vacío si aún no vota")
    submitted_at: datetime | None
    receipt: str | None = Field(description="Comprobante del voto enviado, p. ej. AG-7K2Q-91")


class PeerVotesIn(BaseModel):
    """El voto completo: una delegación por premio, todas distintas. No se puede cambiar."""

    picks: list[BallotPickOut] = Field(min_length=1, max_length=3)
