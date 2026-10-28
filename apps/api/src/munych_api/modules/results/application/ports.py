"""Puertos del módulo de resultados (los implementa `infrastructure/`)."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol
from uuid import UUID

from munych_api.modules.results.domain.models import (
    Award,
    CommitteeData,
    CommitteeInfo,
    EventInfo,
    PublicationSettings,
    RankingEntry,
)


@dataclass(frozen=True, slots=True)
class PublicResult:
    version: int
    published: bool
    published_at: datetime | None
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ScoreDetail:
    """Una fila de la hoja «Detalle» del Excel."""

    committee: str
    delegation: str
    delegate: str
    institution: str | None
    session_number: int
    judge: str
    criterion: str
    value: int
    comment: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CommitteeResults:
    committee: CommitteeInfo
    ranking: list[RankingEntry]
    awards: list[Award]


@dataclass(frozen=True, slots=True)
class ExportData:
    event_name: str
    venue: str | None
    starts_on: date
    ends_on: date
    timezone: str
    generated_at: datetime
    committees: list[CommitteeResults]
    details: list[ScoreDetail]


class ResultsRepository(Protocol):
    # ---------------------------------------------------------------- comités y premios
    async def committee_data(
        self, committee_id: UUID, organization_id: UUID
    ) -> CommitteeData | None: ...

    async def get_awards(self, committee_id: UUID) -> list[Award]: ...

    async def replace_awards(
        self, committee_id: UUID, awards: list[Award], assigned_by: UUID, assigned_at: datetime
    ) -> None: ...

    # ---------------------------------------------------------------- eventos
    async def get_event(self, event_id: UUID, organization_id: UUID) -> EventInfo | None: ...

    async def committee_ids(self, event_id: UUID) -> list[UUID]: ...

    async def open_sessions_count(self, event_id: UUID) -> int: ...

    async def close_event(self, event_id: UUID) -> None: ...

    async def insert_snapshot(
        self, event_id: UUID, data: dict[str, Any], created_by: UUID
    ) -> tuple[UUID, datetime]: ...

    async def latest_snapshot(self, event_id: UUID) -> dict[str, Any] | None: ...

    async def score_details(self, event_id: UUID) -> list[ScoreDetail]: ...

    # ---------------------------------------------------------------- publicación
    async def save_publication_settings(
        self, event_id: UUID, settings: PublicationSettings
    ) -> None: ...

    async def get_public_result(self, event_id: UUID) -> PublicResult | None: ...

    async def upsert_public_result(
        self,
        *,
        event_id: UUID,
        event_slug: str,
        version: int,
        data: dict[str, Any],
        published_at: datetime,
    ) -> None: ...

    async def unpublish(self, event_id: UUID) -> bool:
        """Marca el documento como no publicado. Devuelve False si no existía."""
        ...

    async def commit(self) -> None:
        """Confirma la transacción (antes de avisar al sitio público)."""
        ...


class Revalidator(Protocol):
    async def revalidate(self, event_slug: str) -> bool:
        """Avisa al sitio público. Devuelve False si falla (no lanza)."""
        ...


class Exporter(Protocol):
    """Genera el archivo de exportación. En el MVP solo Excel (PDF en fases posteriores)."""

    media_type: str
    extension: str

    def export(self, data: ExportData) -> bytes: ...


class PublicUrls(Protocol):
    def logo_url(self, logo_path: str | None) -> str | None: ...


class AwardsAudit(Protocol):
    async def record_awards_change(
        self,
        *,
        actor_id: UUID,
        committee_id: UUID,
        before: list[dict[str, Any]],
        after: list[dict[str, Any]],
    ) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
