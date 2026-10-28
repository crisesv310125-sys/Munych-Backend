from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from munych_api.modules.results.domain.models import NameFormat
from munych_api.shared.kernel.catalog import AwardType, CommitteeType

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


class RankingOut(BaseModel):
    items: list[RankingEntryOut]
    quota_warnings: list[str]


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
    published_at: datetime
    version: int


class PublishOut(BaseModel):
    version: int
    published_at: datetime
    revalidated: bool


class UnpublishOut(BaseModel):
    revalidated: bool
