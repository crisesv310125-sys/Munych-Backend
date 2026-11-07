from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from munych_api.modules.results.domain.models import NameFormat
from munych_api.shared.kernel.catalog import AwardType, CommitteeType, EventType, VoterRole

# ---------------------------------------------------------------- ranking


class RankingDelegateOut(BaseModel):
    delegate_id: UUID
    full_name: str
    final_score: float | None


class IncompleteFlagOut(BaseModel):
    kind: str = Field(description="incomplete | session_without_scores | delegate_without_scores")
    delegate_id: UUID
    session_number: int | None
    judge_id: UUID | None


class RankingEntryOut(BaseModel):
    position: int
    tied: bool
    delegation_id: UUID
    country_code: str | None
    character_name: str | None
    institution: str | None
    delegates: list[RankingDelegateOut]
    score: float | None
    criteria_averages: dict[str, float | None]
    incomplete_flags: list[IncompleteFlagOut]
    role_scores: dict[VoterRole, float | None] = Field(
        description="Nota (0-100) de la delegación por rol que vota. null: nadie de ese rol "
        "calificó y su peso se reparte entre los demás roles"
    )
    manual_tiebreak: bool = Field(
        default=False, description="Su posición la decidió el admin al resolver un empate"
    )


class TiebreakIn(BaseModel):
    """Desempate manual: delegaciones del comité en el orden que decide el admin."""

    delegation_ids: list[UUID] = Field(
        max_length=500,
        description="Orden de las delegaciones empatadas. Un empate se resuelve solo si "
        "están todas sus delegaciones. Lista vacía = quitar los desempates manuales",
    )


class RankingOut(BaseModel):
    items: list[RankingEntryOut]
    quota_warnings: list[str]
    event_type: EventType
    role_weights: dict[VoterRole, float] = Field(
        description="Peso (%) de cada rol en la nota final según el tipo de evento"
    )


# ---------------------------------------------------------------- premios


class AwardIn(BaseModel):
    award_type: AwardType
    delegation_id: UUID
    position: int = Field(default=1, ge=1)


class AwardOut(BaseModel):
    award_type: AwardType
    delegation_id: UUID
    position: int


class AwardsOut(BaseModel):
    items: list[AwardOut]
    quota_warnings: list[str]


# ---------------------------------------------------------------- cierre


class CloseEventOut(BaseModel):
    event_id: UUID
    status: str
    snapshot_id: UUID
    closed_at: datetime


# ---------------------------------------------------------------- publicación


class PublicationSettingsBody(BaseModel):
    name_format: NameFormat = "first_name_initial"
    show_institution: bool = True
    show_ranking: bool = False
    show_scores: bool = False
    indexable: bool = False


class PublicDelegationOut(BaseModel):
    country_code: str | None
    character_name: str | None
    institution: str | None


class PublicAwardOut(BaseModel):
    award_type: AwardType
    position: int
    delegation: PublicDelegationOut
    delegates: list[str]


class PublicRankingEntryOut(BaseModel):
    position: int
    delegation: PublicDelegationOut
    delegates: list[str]
    score: float | None


class PublicCommitteeOut(BaseModel):
    slug: str
    name: str
    acronym: str
    type: CommitteeType
    awards: list[PublicAwardOut]
    ranking: list[PublicRankingEntryOut] | None


class PublicCommitteeRefOut(BaseModel):
    slug: str
    name: str
    acronym: str


class PublicGeneralRankingEntryOut(PublicRankingEntryOut):
    """Una delegación en el ranking general del evento (todas las de todos los comités)."""

    committee: PublicCommitteeRefOut


class PublicEventOut(BaseModel):
    slug: str
    name: str
    brand: str
    logo_url: str | None
    venue: str | None
    starts_on: date
    ends_on: date
    timezone: str


class PublicDocumentOut(BaseModel):
    """Documento de `public.public_results.data` (sección 7.5)."""

    event: PublicEventOut
    settings: PublicationSettingsBody
    committees: list[PublicCommitteeOut]
    general_ranking: list[PublicGeneralRankingEntryOut] | None = Field(
        default=None,
        description="Ranking general del evento (todas las delegaciones con nota). "
        "null si show_ranking = false",
    )
    published_at: datetime
    version: int


class PublishOut(BaseModel):
    version: int
    published_at: datetime
    revalidated: bool


class UnpublishOut(BaseModel):
    revalidated: bool
