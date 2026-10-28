"""Casos de uso de `results` con adaptadores en memoria (sin base de datos)."""

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from munych_api.modules.results.application.close_event import CloseEvent
from munych_api.modules.results.application.compute_ranking import ComputeRanking
from munych_api.modules.results.application.export_event import ExportEvent
from munych_api.modules.results.application.ports import (
    ExportData,
    PublicResult,
    ScoreDetail,
)
from munych_api.modules.results.application.publication import Publication
from munych_api.modules.results.application.set_awards import ManageAwards
from munych_api.modules.results.domain.models import (
    Award,
    CommitteeData,
    CommitteeInfo,
    CriterionInfo,
    DelegateInfo,
    DelegationInfo,
    EventInfo,
    PublicationSettings,
    RubricInfo,
    ScoreValue,
    SessionInfo,
)
from munych_api.shared.kernel import DomainError, ErrorCode

NOW = datetime(2026, 10, 11, 23, 0, tzinfo=UTC)
ORG, ADMIN, JUDGE = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
EVENT_ID, COMMITTEE_ID, SESSION_ID, CRITERION_ID = (uuid.uuid4() for _ in range(4))
ANA = DelegateInfo(uuid.uuid4(), "Ana Pérez López")
MX = DelegationInfo(uuid.uuid4(), "MX", None, "Colegio Ejemplo", (ANA,))


class FixedClock:
    def now(self) -> datetime:
        return NOW


class InMemoryResultsRepository:
    def __init__(self) -> None:
        self.event = EventInfo(
            EVENT_ID,
            "sd-mun-2026",
            "SD-MUN 2026",
            "grand_international",
            "logo.png",
            "Santo Domingo",
            "America/Santo_Domingo",
            date(2026, 10, 9),
            date(2026, 10, 11),
            "active",
        )
        self.awards: list[Award] = []
        self.open_sessions = 0
        self.snapshots: list[dict[str, Any]] = []
        self.public: PublicResult | None = None
        self.log: list[str] = []

    def _data(self) -> CommitteeData:
        return CommitteeData(
            committee=CommitteeInfo(
                COMMITTEE_ID,
                EVENT_ID,
                "disec",
                "Primera Comisión",
                "DISEC",
                "general_assembly",
                {"best_delegate": 1},
                self.event.closed,
            ),
            rubric=RubricInfo(1, 4, (CriterionInfo(CRITERION_ID, "Oratoria", Decimal(100), 1),)),
            sessions=(SessionInfo(SESSION_ID, 1),),
            delegations=(MX,),
            scores=(ScoreValue(JUDGE, ANA.id, SESSION_ID, CRITERION_ID, 3),),
        )

    async def committee_data(
        self, committee_id: UUID, organization_id: UUID
    ) -> CommitteeData | None:
        return self._data() if (committee_id, organization_id) == (COMMITTEE_ID, ORG) else None

    async def get_awards(self, committee_id: UUID) -> list[Award]:
        return list(self.awards)

    async def replace_awards(
        self, committee_id: UUID, awards: list[Award], assigned_by: UUID, assigned_at: datetime
    ) -> None:
        self.awards = list(awards)

    async def get_event(self, event_id: UUID, organization_id: UUID) -> EventInfo | None:
        return self.event if (event_id, organization_id) == (EVENT_ID, ORG) else None

    async def committee_ids(self, event_id: UUID) -> list[UUID]:
        return [COMMITTEE_ID]

    async def open_sessions_count(self, event_id: UUID) -> int:
        return self.open_sessions

    async def close_event(self, event_id: UUID) -> None:
        self.event = replace(self.event, status="closed")

    async def insert_snapshot(
        self, event_id: UUID, data: dict[str, Any], created_by: UUID
    ) -> tuple[UUID, datetime]:
        self.snapshots.append(data)
        return uuid.uuid4(), NOW

    async def latest_snapshot(self, event_id: UUID) -> dict[str, Any] | None:
        return self.snapshots[-1] if self.snapshots else None

    async def score_details(self, event_id: UUID) -> list[ScoreDetail]:
        return []

    async def save_publication_settings(
        self, event_id: UUID, settings: PublicationSettings
    ) -> None:
        self.event = replace(self.event, publication_settings=settings)

    async def get_public_result(self, event_id: UUID) -> PublicResult | None:
        return self.public

    async def upsert_public_result(self, **values: Any) -> None:
        self.log.append("upsert")
        self.public = PublicResult(values["version"], True, values["published_at"], values["data"])

    async def unpublish(self, event_id: UUID) -> bool:
        if self.public is None:
            return False
        self.public = PublicResult(
            self.public.version, False, self.public.published_at, self.public.data
        )
        return True

    async def commit(self) -> None:
        self.log.append("commit")


class FakeRevalidator:
    def __init__(self, repo: InMemoryResultsRepository, ok: bool = True) -> None:
        self.repo = repo
        self.ok = ok
        self.calls: list[str] = []

    async def revalidate(self, event_slug: str) -> bool:
        self.repo.log.append("revalidate")
        self.calls.append(event_slug)
        return self.ok


class RecordingAudit:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def record_awards_change(self, **entry: Any) -> None:
        self.entries.append(entry)


class Urls:
    def logo_url(self, logo_path: str | None) -> str | None:
        return f"https://cdn/{logo_path}" if logo_path else None


class RecordingExporter:
    media_type = "application/test"
    extension = "bin"

    def __init__(self) -> None:
        self.data: ExportData | None = None

    def export(self, data: ExportData) -> bytes:
        self.data = data
        return b"contenido"


@pytest.fixture
def repo() -> InMemoryResultsRepository:
    return InMemoryResultsRepository()


# ---------------------------------------------------------------- ranking y premios


async def test_ranking_with_quota_warnings(repo: InMemoryResultsRepository) -> None:
    repo.awards = [Award("best_delegate", MX.id), Award("best_delegate", uuid.uuid4())]
    ranking = await ComputeRanking(repo).execute(ORG, COMMITTEE_ID)
    assert ranking.items[0].score == Decimal(75)
    assert ranking.quota_warnings == ["Mejor delegado: 2 asignados y el cupo es 1"]
    with pytest.raises(DomainError):
        await ComputeRanking(repo).execute(uuid.uuid4(), COMMITTEE_ID)


async def test_replace_awards_is_audited(repo: InMemoryResultsRepository) -> None:
    audit = RecordingAudit()
    manage = ManageAwards(repo, audit, FixedClock())
    result = await manage.replace(ORG, COMMITTEE_ID, [Award("honorable_mention", MX.id)], ADMIN)
    assert result.items == [Award("honorable_mention", MX.id)]
    assert result.quota_warnings == ["Mención honorífica: 1 asignados y el cupo es 0"]
    assert audit.entries[0]["before"] == []
    assert audit.entries[0]["after"][0]["award_type"] == "honorable_mention"
    assert (await manage.get(ORG, COMMITTEE_ID)).items == result.items


async def test_awards_cannot_change_after_close(repo: InMemoryResultsRepository) -> None:
    repo.event = replace(repo.event, status="closed")
    manage = ManageAwards(repo, RecordingAudit(), FixedClock())
    with pytest.raises(DomainError) as exc:
        await manage.replace(ORG, COMMITTEE_ID, [], ADMIN)
    assert exc.value.code == ErrorCode.EVENT_CLOSED


# ---------------------------------------------------------------- cierre


async def test_close_requires_all_sessions_closed(repo: InMemoryResultsRepository) -> None:
    repo.open_sessions = 2
    with pytest.raises(DomainError) as exc:
        await CloseEvent(repo, Urls(), FixedClock()).execute(ORG, EVENT_ID, ADMIN)
    assert exc.value.code == ErrorCode.SESSIONS_STILL_OPEN
    assert "2 sesiones" in exc.value.detail


async def test_close_creates_snapshot_and_blocks_second_close(
    repo: InMemoryResultsRepository,
) -> None:
    repo.awards = [Award("best_delegate", MX.id)]
    close = CloseEvent(repo, Urls(), FixedClock())
    closed = await close.execute(ORG, EVENT_ID, ADMIN)
    assert closed.closed_at == NOW
    assert repo.event.closed
    (snapshot,) = repo.snapshots
    assert snapshot["event"]["logo_url"] == "https://cdn/logo.png"
    committee = snapshot["committees"][0]
    assert committee["ranking"][0]["score"] == 75.0
    assert committee["awards"] == [
        {"award_type": "best_delegate", "position": 1, "delegation_id": str(MX.id)}
    ]
    with pytest.raises(DomainError) as exc:
        await close.execute(ORG, EVENT_ID, ADMIN)
    assert exc.value.code == ErrorCode.EVENT_CLOSED


# ---------------------------------------------------------------- publicación


async def test_publish_requires_closed_event(repo: InMemoryResultsRepository) -> None:
    publication = Publication(repo, FakeRevalidator(repo), FixedClock())
    with pytest.raises(DomainError) as exc:
        await publication.publish(ORG, EVENT_ID)
    assert exc.value.code == ErrorCode.EVENT_NOT_CLOSED
    with pytest.raises(DomainError) as exc:
        await publication.preview(ORG, EVENT_ID)
    assert exc.value.code == ErrorCode.EVENT_NOT_CLOSED


async def test_publish_commits_before_revalidating_and_bumps_version(
    repo: InMemoryResultsRepository,
) -> None:
    repo.awards = [Award("best_delegate", MX.id)]
    await CloseEvent(repo, Urls(), FixedClock()).execute(ORG, EVENT_ID, ADMIN)
    revalidator = FakeRevalidator(repo)
    publication = Publication(repo, revalidator, FixedClock())

    preview = await publication.preview(ORG, EVENT_ID)
    first = await publication.publish(ORG, EVENT_ID)
    assert (first.version, first.revalidated) == (1, True)
    assert repo.log == ["upsert", "commit", "revalidate"]
    assert repo.public is not None
    assert repo.public.data == preview
    assert preview["committees"][0]["awards"][0]["delegates"] == ["Ana P."]

    second = await publication.publish(ORG, EVENT_ID)
    assert second.version == 2
    assert revalidator.calls == ["sd-mun-2026", "sd-mun-2026"]


async def test_failed_webhook_keeps_publication(repo: InMemoryResultsRepository) -> None:
    await CloseEvent(repo, Urls(), FixedClock()).execute(ORG, EVENT_ID, ADMIN)
    result = await Publication(repo, FakeRevalidator(repo, ok=False), FixedClock()).publish(
        ORG, EVENT_ID
    )
    assert result.revalidated is False
    assert repo.public is not None
    assert repo.public.published is True


async def test_settings_and_unpublish(repo: InMemoryResultsRepository) -> None:
    publication = Publication(repo, FakeRevalidator(repo), FixedClock())
    assert await publication.get_settings(ORG, EVENT_ID) == PublicationSettings()
    updated = await publication.update_settings(
        ORG, EVENT_ID, PublicationSettings(name_format="hidden", show_ranking=True)
    )
    assert (await publication.get_settings(ORG, EVENT_ID)) == updated

    await CloseEvent(repo, Urls(), FixedClock()).execute(ORG, EVENT_ID, ADMIN)
    preview = await publication.preview(ORG, EVENT_ID)
    assert preview["committees"][0]["ranking"][0]["delegates"] == []

    await publication.publish(ORG, EVENT_ID)
    assert await publication.unpublish(ORG, EVENT_ID) is True
    assert repo.public is not None
    assert repo.public.published is False


async def test_export_uses_exporter(repo: InMemoryResultsRepository) -> None:
    exporter = RecordingExporter()
    export = await ExportEvent(repo, exporter, FixedClock()).execute(ORG, EVENT_ID)
    assert export.filename == "sd-mun-2026-resultados.bin"
    assert export.content == b"contenido"
    assert exporter.data is not None
    assert exporter.data.committees[0].ranking[0].score == Decimal(75)
    with pytest.raises(DomainError) as exc:
        await ExportEvent(repo, exporter, FixedClock()).execute(ORG, uuid.uuid4())
    assert exc.value.code == ErrorCode.NOT_FOUND
