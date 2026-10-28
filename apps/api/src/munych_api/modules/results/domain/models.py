"""Entidades de resultados. Dominio puro: sin frameworks ni acceso a datos."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from munych_api.shared.kernel.catalog import AwardType, CommitteeType

NameFormat = Literal["full", "first_name_initial", "hidden"]


@dataclass(frozen=True, slots=True)
class DelegateInfo:
    id: UUID
    full_name: str


@dataclass(frozen=True, slots=True)
class DelegationInfo:
    id: UUID
    country_code: str | None
    character_name: str | None
    institution: str | None
    delegates: tuple[DelegateInfo, ...]

    @property
    def label(self) -> str:
        return self.country_code or self.character_name or ""


@dataclass(frozen=True, slots=True)
class CriterionInfo:
    id: UUID
    name: str
    weight: Decimal
    position: int


@dataclass(frozen=True, slots=True)
class RubricInfo:
    scale_min: int
    scale_max: int
    criteria: tuple[CriterionInfo, ...]


@dataclass(frozen=True, slots=True)
class SessionInfo:
    id: UUID
    number: int


@dataclass(frozen=True, slots=True)
class ScoreValue:
    judge_id: UUID
    delegate_id: UUID
    session_id: UUID
    criterion_id: UUID
    value: int


@dataclass(frozen=True, slots=True)
class CommitteeInfo:
    id: UUID
    event_id: UUID
    slug: str
    name: str
    acronym: str
    type: CommitteeType
    award_quotas: dict[AwardType, int]
    event_closed: bool


@dataclass(frozen=True, slots=True)
class CommitteeData:
    """Todo lo necesario para calcular el ranking de un comité."""

    committee: CommitteeInfo
    rubric: RubricInfo | None
    sessions: tuple[SessionInfo, ...]
    delegations: tuple[DelegationInfo, ...]
    scores: tuple[ScoreValue, ...]


# ---------------------------------------------------------------- ranking


@dataclass(frozen=True, slots=True)
class DelegateScore:
    delegate_id: UUID
    full_name: str
    final_score: Decimal | None


@dataclass(frozen=True, slots=True)
class IncompleteFlag:
    kind: str
    delegate_id: UUID
    session_number: int | None = None
    judge_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class RankingEntry:
    position: int
    tied: bool
    delegation: DelegationInfo
    delegates: tuple[DelegateScore, ...]
    score: Decimal | None
    criteria_averages: dict[UUID, Decimal | None]
    incomplete_flags: tuple[IncompleteFlag, ...] = ()


# ---------------------------------------------------------------- premios


@dataclass(frozen=True, slots=True)
class Award:
    award_type: AwardType
    delegation_id: UUID
    position: int = 1


# ---------------------------------------------------------------- evento y publicación


@dataclass(frozen=True, slots=True)
class PublicationSettings:
    """Valores por defecto conservadores: participan menores (sección 6.5)."""

    # TODO(cliente): confirmar qué se publica (MVP: premios, delegación, "Nombre I." e
    # institución; sin ranking ni puntajes; noindex).
    name_format: NameFormat = "first_name_initial"
    show_institution: bool = True
    show_ranking: bool = False
    show_scores: bool = False
    indexable: bool = False

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "PublicationSettings":
        """Lee la configuración guardada; las claves ausentes o inválidas usan el defecto."""
        raw = raw or {}
        defaults = cls()
        name_format = raw.get("name_format", defaults.name_format)
        if name_format not in ("full", "first_name_initial", "hidden"):
            name_format = defaults.name_format

        def flag(key: str) -> bool:
            value = raw.get(key)
            return value if isinstance(value, bool) else bool(getattr(defaults, key))

        return cls(
            name_format=name_format,
            show_institution=flag("show_institution"),
            show_ranking=flag("show_ranking"),
            show_scores=flag("show_scores"),
            indexable=flag("indexable"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name_format": self.name_format,
            "show_institution": self.show_institution,
            "show_ranking": self.show_ranking,
            "show_scores": self.show_scores,
            "indexable": self.indexable,
        }


@dataclass(frozen=True, slots=True)
class EventInfo:
    id: UUID
    slug: str
    name: str
    brand: str
    logo_path: str | None
    venue: str | None
    timezone: str
    starts_on: date
    ends_on: date
    status: str
    publication_settings: PublicationSettings = field(default_factory=PublicationSettings)

    @property
    def closed(self) -> bool:
        return self.status == "closed"
