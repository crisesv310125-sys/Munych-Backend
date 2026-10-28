from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import available_timezones

from pydantic import AfterValidator, BaseModel, Field, NonNegativeInt, model_validator

from munych_api.shared.kernel.catalog import (
    AwardType,
    Brand,
    CommitteeType,
    DelegationMode,
    EventStatus,
)

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
COUNTRY_PATTERN = r"^[A-Z]{2}$"

_TIMEZONES = available_timezones()


def _check_timezone(value: str) -> str:
    if value not in _TIMEZONES:
        raise ValueError("Zona horaria IANA desconocida")
    return value


Slug = Annotated[str, Field(pattern=SLUG_PATTERN, max_length=80)]
CountryCode = Annotated[str, Field(pattern=COUNTRY_PATTERN, description="ISO-3166 alfa-2")]
Timezone = Annotated[str, AfterValidator(_check_timezone), Field(examples=["America/Mexico_City"])]
Name = Annotated[str, Field(min_length=1, max_length=200)]
OptionalText = Annotated[str | None, Field(default=None, max_length=200)]
AwardQuotas = dict[AwardType, NonNegativeInt]


# ---------------------------------------------------------------- eventos


class EventCreate(BaseModel):
    slug: Slug
    name: Name
    brand: Brand
    venue: OptionalText = None
    country_code: CountryCode | None = None
    timezone: Timezone
    starts_on: date
    ends_on: date

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.ends_on < self.starts_on:
            raise ValueError("ends_on debe ser igual o posterior a starts_on")
        return self


class EventUpdate(BaseModel):
    slug: Slug | None = None
    name: Name | None = None
    brand: Brand | None = None
    venue: OptionalText = None
    country_code: CountryCode | None = None
    timezone: Timezone | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    default_rubric_id: UUID | None = None
    status: Literal["draft", "active"] | None = Field(
        default=None, description="Para cerrar el evento usa POST /events/{id}/close"
    )


class EventOut(BaseModel):
    id: UUID
    slug: str
    name: str
    brand: Brand
    logo_url: str | None
    venue: str | None
    country_code: str | None
    timezone: str
    starts_on: date
    ends_on: date
    status: EventStatus
    default_rubric_id: UUID | None
    created_at: datetime
    updated_at: datetime | None


# ---------------------------------------------------------------- comités


class CommitteeCreate(BaseModel):
    name: Name
    acronym: Annotated[str, Field(min_length=1, max_length=30)]
    slug: Slug
    type: CommitteeType
    delegation_mode: DelegationMode
    sessions_count: Annotated[int, Field(ge=1, le=20)]
    rubric_id: UUID | None = Field(
        default=None, description="Sobrescribe la rúbrica por defecto del evento"
    )
    award_quotas: AwardQuotas | None = Field(
        default=None, description="Por defecto, según el tipo de comité"
    )


class CommitteeUpdate(BaseModel):
    name: Name | None = None
    acronym: Annotated[str | None, Field(default=None, min_length=1, max_length=30)] = None
    slug: Slug | None = None
    type: CommitteeType | None = None
    delegation_mode: DelegationMode | None = None
    sessions_count: Annotated[int | None, Field(default=None, ge=1, le=20)] = None
    rubric_id: UUID | None = None
    award_quotas: AwardQuotas | None = None


class CommitteeOut(BaseModel):
    id: UUID
    event_id: UUID
    name: str
    acronym: str
    slug: str
    type: CommitteeType
    delegation_mode: DelegationMode
    sessions_count: int
    rubric_id: UUID | None
    award_quotas: dict[AwardType, int]
    created_at: datetime


# ---------------------------------------------------------------- delegaciones y delegados


class DelegateIn(BaseModel):
    full_name: Name
    institution: OptionalText = None


class DelegateUpdate(BaseModel):
    full_name: Name | None = None
    institution: OptionalText = None


class DelegateOut(BaseModel):
    id: UUID
    delegation_id: UUID
    full_name: str
    institution: str | None


class DelegationCreate(BaseModel):
    country_code: CountryCode | None = None
    character_name: OptionalText = None
    institution: OptionalText = None
    delegates: list[DelegateIn] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def _identity(self) -> Self:
        if (self.country_code is None) == (self.character_name is None):
            raise ValueError("Indica exactamente uno: country_code o character_name")
        return self


class DelegationUpdate(BaseModel):
    """Para cambiar de país a personaje (o al revés) envía ambos campos, uno en null."""

    country_code: CountryCode | None = None
    character_name: OptionalText = None
    institution: OptionalText = None


class DelegationOut(BaseModel):
    id: UUID
    committee_id: UUID
    country_code: str | None
    character_name: str | None
    institution: str | None
    delegates: list[DelegateOut]


class ImportRowError(BaseModel):
    row: int = Field(description="Número de línea en el archivo (la cabecera es la línea 1)")
    message: str


class ImportResult(BaseModel):
    created: int
    skipped: int
    errors: list[ImportRowError]
