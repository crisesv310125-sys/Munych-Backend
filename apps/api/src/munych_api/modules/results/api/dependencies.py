"""Cableado del módulo de resultados (único lugar donde se crean los adaptadores)."""

from typing import Annotated

from fastapi import Depends, Request

from munych_api.modules.audit.dependencies import AuditServiceDep
from munych_api.modules.results.application.close_event import CloseEvent
from munych_api.modules.results.application.compute_ranking import ComputeRanking
from munych_api.modules.results.application.export_event import ExportEvent
from munych_api.modules.results.application.ports import Clock, Revalidator
from munych_api.modules.results.application.publication import Publication
from munych_api.modules.results.application.set_awards import ManageAwards
from munych_api.modules.results.infrastructure.adapters import (
    AwardsAuditAdapter,
    StoragePublicUrls,
)
from munych_api.modules.results.infrastructure.excel_exporter import ExcelExporter
from munych_api.modules.results.infrastructure.sqlalchemy_results_repository import (
    SqlAlchemyResultsRepository,
)
from munych_api.shared.database import DbSession
from munych_api.shared.kernel import SystemClock
from munych_api.shared.supabase import ObjectStorage


def get_clock() -> Clock:
    return SystemClock()


def get_revalidator(request: Request) -> Revalidator:
    revalidator: Revalidator = request.app.state.revalidator
    return revalidator


def get_storage(request: Request) -> ObjectStorage:
    storage: ObjectStorage = request.app.state.supabase
    return storage


ClockDep = Annotated[Clock, Depends(get_clock)]


def get_repository(session: DbSession) -> SqlAlchemyResultsRepository:
    return SqlAlchemyResultsRepository(session)


RepositoryDep = Annotated[SqlAlchemyResultsRepository, Depends(get_repository)]


def get_compute_ranking(repository: RepositoryDep) -> ComputeRanking:
    return ComputeRanking(repository)


def get_manage_awards(
    repository: RepositoryDep, audit: AuditServiceDep, clock: ClockDep
) -> ManageAwards:
    return ManageAwards(repository, AwardsAuditAdapter(audit), clock)


def get_close_event(
    repository: RepositoryDep,
    storage: Annotated[ObjectStorage, Depends(get_storage)],
    clock: ClockDep,
) -> CloseEvent:
    return CloseEvent(repository, StoragePublicUrls(storage), clock)


def get_export_event(repository: RepositoryDep, clock: ClockDep) -> ExportEvent:
    return ExportEvent(repository, ExcelExporter(), clock)


def get_publication(
    repository: RepositoryDep,
    revalidator: Annotated[Revalidator, Depends(get_revalidator)],
    clock: ClockDep,
) -> Publication:
    return Publication(repository, revalidator, clock)


ComputeRankingDep = Annotated[ComputeRanking, Depends(get_compute_ranking)]
ManageAwardsDep = Annotated[ManageAwards, Depends(get_manage_awards)]
CloseEventDep = Annotated[CloseEvent, Depends(get_close_event)]
ExportEventDep = Annotated[ExportEvent, Depends(get_export_event)]
PublicationDep = Annotated[Publication, Depends(get_publication)]
