from uuid import UUID

from fastapi import APIRouter, Request

from munych_api.modules.identity.dependencies import IdentityServiceDep
from munych_api.modules.identity.schemas import (
    JudgeInvitationOut,
    JudgeInvite,
    JudgeOut,
    JudgeUpdate,
    MeOut,
)
from munych_api.shared.auth import AdminUser, AnyUser, OrganizationId
from munych_api.shared.pagination import Page, Pagination
from munych_api.shared.rate_limit import INVITES_LIMIT, limiter

router = APIRouter(tags=["identity"])


@router.get("/me")
async def get_me(user: AnyUser, service: IdentityServiceDep) -> MeOut:
    return await service.me(user)


@router.get("/judges")
async def list_judges(
    _: AdminUser,
    organization_id: OrganizationId,
    page: Pagination,
    service: IdentityServiceDep,
    event_id: UUID | None = None,
) -> Page[JudgeOut]:
    """Jueces de la organización; con `event_id`, solo los vinculados a ese evento."""
    return await service.list_judges(organization_id, page, event_id)


@router.get("/judges/invitations")
async def list_judge_invitations(
    _: AdminUser,
    organization_id: OrganizationId,
    page: Pagination,
    service: IdentityServiceDep,
    event_id: UUID | None = None,
) -> Page[JudgeInvitationOut]:
    """Jueces invitados que aún no aceptan la invitación (no salen en `GET /judges`)."""
    return await service.list_pending_invitations(organization_id, page, event_id)


@router.post("/judges/{judge_id}/invitation")
@limiter.limit(INVITES_LIMIT)
async def resend_judge_invitation(
    request: Request,
    judge_id: UUID,
    _: AdminUser,
    organization_id: OrganizationId,
    service: IdentityServiceDep,
) -> JudgeInvitationOut:
    """Reenvía el correo de invitación; 409 si el juez ya la aceptó."""
    return await service.resend_invitation(organization_id, judge_id)


@router.post("/judges", status_code=201)
@limiter.limit(INVITES_LIMIT)
async def invite_judge(
    request: Request,
    body: JudgeInvite,
    _: AdminUser,
    organization_id: OrganizationId,
    service: IdentityServiceDep,
) -> JudgeOut:
    return await service.invite_judge(organization_id, body)


@router.patch("/judges/{judge_id}")
async def update_judge(
    judge_id: UUID,
    body: JudgeUpdate,
    _: AdminUser,
    organization_id: OrganizationId,
    service: IdentityServiceDep,
) -> JudgeOut:
    return await service.update_judge(organization_id, judge_id, body)
