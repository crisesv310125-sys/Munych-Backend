from uuid import UUID

from fastapi import APIRouter

from munych_api.modules.judging.dependencies import JudgingServiceDep
from munych_api.modules.judging.schemas import (
    AssignmentIn,
    AssignmentOut,
    JudgeCommitteeDetailOut,
    JudgeCommitteeOut,
)
from munych_api.shared.auth import AdminUser, JudgeUser, OrganizationId, ensure_committee_assignment
from munych_api.shared.database import DbSession

router = APIRouter(tags=["judging"])


@router.get("/committees/{committee_id}/judges")
async def list_committee_judges(
    committee_id: UUID, _: AdminUser, organization_id: OrganizationId, service: JudgingServiceDep
) -> list[AssignmentOut]:
    return await service.list_assignments(organization_id, committee_id)


@router.put("/committees/{committee_id}/judges")
async def replace_committee_judges(
    committee_id: UUID,
    body: list[AssignmentIn],
    _: AdminUser,
    organization_id: OrganizationId,
    service: JudgingServiceDep,
) -> list[AssignmentOut]:
    """Reemplaza todas las asignaciones del comité por la lista enviada."""
    return await service.replace_assignments(organization_id, committee_id, body)


@router.get("/judge/committees")
async def list_judge_committees(
    user: JudgeUser, service: JudgingServiceDep
) -> list[JudgeCommitteeOut]:
    """Comités asignados al juez autenticado, solo de eventos activos."""
    return await service.judge_committees(user.user_id)


@router.get("/judge/committees/{committee_id}")
async def get_judge_committee(
    committee_id: UUID, user: JudgeUser, session: DbSession, service: JudgingServiceDep
) -> JudgeCommitteeDetailOut:
    """Delegaciones, delegados, rúbrica (con descriptores) y sesiones del comité."""
    role = await ensure_committee_assignment(session, user.user_id, committee_id)
    return await service.judge_committee_detail(committee_id, role)
