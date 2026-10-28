from uuid import UUID

from fastapi import APIRouter, File, Response, UploadFile

from munych_api.modules.events.csv_import import MAX_FILE_BYTES
from munych_api.modules.events.dependencies import EventsServiceDep
from munych_api.modules.events.schemas import (
    CommitteeCreate,
    CommitteeOut,
    CommitteeUpdate,
    DelegateIn,
    DelegateOut,
    DelegateUpdate,
    DelegationCreate,
    DelegationOut,
    DelegationUpdate,
    EventCreate,
    EventOut,
    EventUpdate,
    ImportResult,
)
from munych_api.shared.auth import AdminUser, OrganizationId
from munych_api.shared.kernel.catalog import LOGO_MAX_BYTES
from munych_api.shared.pagination import Page, Pagination

router = APIRouter(tags=["events"])

# ---------------------------------------------------------------- eventos


@router.get("/events")
async def list_events(
    _: AdminUser, organization_id: OrganizationId, page: Pagination, service: EventsServiceDep
) -> Page[EventOut]:
    return await service.list_events(organization_id, page)


@router.post("/events", status_code=201)
async def create_event(
    body: EventCreate, _: AdminUser, organization_id: OrganizationId, service: EventsServiceDep
) -> EventOut:
    """Crea el evento y su rúbrica por defecto."""
    return await service.create_event(organization_id, body)


@router.get("/events/{event_id}")
async def get_event(
    event_id: UUID, _: AdminUser, organization_id: OrganizationId, service: EventsServiceDep
) -> EventOut:
    return await service.get_event(organization_id, event_id)


@router.patch("/events/{event_id}")
async def update_event(
    event_id: UUID,
    body: EventUpdate,
    _: AdminUser,
    organization_id: OrganizationId,
    service: EventsServiceDep,
) -> EventOut:
    return await service.update_event(organization_id, event_id, body)


@router.delete("/events/{event_id}", status_code=204)
async def delete_event(
    event_id: UUID, _: AdminUser, organization_id: OrganizationId, service: EventsServiceDep
) -> Response:
    """Solo se pueden borrar eventos en borrador."""
    await service.delete_event(organization_id, event_id)
    return Response(status_code=204)


@router.post("/events/{event_id}/logo")
async def upload_event_logo(
    event_id: UUID,
    _: AdminUser,
    organization_id: OrganizationId,
    service: EventsServiceDep,
    file: UploadFile = File(description="PNG, SVG o WebP; máximo 2 MB"),
) -> EventOut:
    content = await file.read(LOGO_MAX_BYTES + 1)
    return await service.upload_logo(organization_id, event_id, content, file.content_type)


# ---------------------------------------------------------------- comités


@router.get("/events/{event_id}/committees")
async def list_committees(
    event_id: UUID,
    _: AdminUser,
    organization_id: OrganizationId,
    page: Pagination,
    service: EventsServiceDep,
) -> Page[CommitteeOut]:
    return await service.list_committees(organization_id, event_id, page)


@router.post("/events/{event_id}/committees", status_code=201)
async def create_committee(
    event_id: UUID,
    body: CommitteeCreate,
    _: AdminUser,
    organization_id: OrganizationId,
    service: EventsServiceDep,
) -> CommitteeOut:
    """Crea el comité y sus sesiones de calificación (1..sessions_count)."""
    return await service.create_committee(organization_id, event_id, body)


@router.get("/committees/{committee_id}")
async def get_committee(
    committee_id: UUID, _: AdminUser, organization_id: OrganizationId, service: EventsServiceDep
) -> CommitteeOut:
    return await service.get_committee(organization_id, committee_id)


@router.patch("/committees/{committee_id}")
async def update_committee(
    committee_id: UUID,
    body: CommitteeUpdate,
    _: AdminUser,
    organization_id: OrganizationId,
    service: EventsServiceDep,
) -> CommitteeOut:
    return await service.update_committee(organization_id, committee_id, body)


@router.delete("/committees/{committee_id}", status_code=204)
async def delete_committee(
    committee_id: UUID, _: AdminUser, organization_id: OrganizationId, service: EventsServiceDep
) -> Response:
    await service.delete_committee(organization_id, committee_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- delegaciones


@router.get("/committees/{committee_id}/delegations")
async def list_delegations(
    committee_id: UUID,
    _: AdminUser,
    organization_id: OrganizationId,
    page: Pagination,
    service: EventsServiceDep,
) -> Page[DelegationOut]:
    return await service.list_delegations(organization_id, committee_id, page)


@router.post("/committees/{committee_id}/delegations", status_code=201)
async def create_delegation(
    committee_id: UUID,
    body: DelegationCreate,
    _: AdminUser,
    organization_id: OrganizationId,
    service: EventsServiceDep,
) -> DelegationOut:
    return await service.create_delegation(organization_id, committee_id, body)


@router.post("/committees/{committee_id}/delegations/import")
async def import_delegations(
    committee_id: UUID,
    _: AdminUser,
    organization_id: OrganizationId,
    service: EventsServiceDep,
    file: UploadFile = File(description="CSV UTF-8 separado por comas (sección 7.4)"),
) -> ImportResult:
    content = await file.read(MAX_FILE_BYTES + 1)
    return await service.import_delegations(organization_id, committee_id, content)


@router.patch("/delegations/{delegation_id}")
async def update_delegation(
    delegation_id: UUID,
    body: DelegationUpdate,
    _: AdminUser,
    organization_id: OrganizationId,
    service: EventsServiceDep,
) -> DelegationOut:
    return await service.update_delegation(organization_id, delegation_id, body)


@router.delete("/delegations/{delegation_id}", status_code=204)
async def delete_delegation(
    delegation_id: UUID, _: AdminUser, organization_id: OrganizationId, service: EventsServiceDep
) -> Response:
    await service.delete_delegation(organization_id, delegation_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- delegados


@router.post("/delegations/{delegation_id}/delegates", status_code=201)
async def add_delegate(
    delegation_id: UUID,
    body: DelegateIn,
    _: AdminUser,
    organization_id: OrganizationId,
    service: EventsServiceDep,
) -> DelegateOut:
    return await service.add_delegate(organization_id, delegation_id, body)


@router.patch("/delegates/{delegate_id}")
async def update_delegate(
    delegate_id: UUID,
    body: DelegateUpdate,
    _: AdminUser,
    organization_id: OrganizationId,
    service: EventsServiceDep,
) -> DelegateOut:
    return await service.update_delegate(organization_id, delegate_id, body)


@router.delete("/delegates/{delegate_id}", status_code=204)
async def delete_delegate(
    delegate_id: UUID, _: AdminUser, organization_id: OrganizationId, service: EventsServiceDep
) -> Response:
    await service.delete_delegate(organization_id, delegate_id)
    return Response(status_code=204)
