from uuid import UUID

from fastapi import APIRouter

from munych_api.modules.rubrics.dependencies import RubricsServiceDep
from munych_api.modules.rubrics.schemas import RubricIn, RubricOut
from munych_api.shared.auth import AdminUser, OrganizationId

router = APIRouter(tags=["rubrics"])


@router.get("/events/{event_id}/rubrics")
async def list_event_rubrics(
    event_id: UUID, _: AdminUser, organization_id: OrganizationId, service: RubricsServiceDep
) -> list[RubricOut]:
    return await service.list_rubrics(organization_id, event_id)


@router.post("/events/{event_id}/rubrics", status_code=201)
async def create_rubric(
    event_id: UUID,
    body: RubricIn,
    _: AdminUser,
    organization_id: OrganizationId,
    service: RubricsServiceDep,
) -> RubricOut:
    """Crea una rúbrica adicional (para sobrescribir la del evento en un comité)."""
    return await service.create_rubric(organization_id, event_id, body)


@router.get("/rubrics/{rubric_id}")
async def get_rubric(
    rubric_id: UUID, _: AdminUser, organization_id: OrganizationId, service: RubricsServiceDep
) -> RubricOut:
    return await service.get_rubric(organization_id, rubric_id)


@router.put("/rubrics/{rubric_id}")
async def replace_rubric(
    rubric_id: UUID,
    body: RubricIn,
    _: AdminUser,
    organization_id: OrganizationId,
    service: RubricsServiceDep,
) -> RubricOut:
    return await service.replace_rubric(organization_id, rubric_id, body)
