from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from munych_api.config import Settings
from munych_api.modules.identity.dependencies import IdentityServiceDep, get_auth_admin
from munych_api.modules.staff.repository import StaffRepository
from munych_api.modules.staff.service import INVALID_LINK, StaffPerson, StaffService
from munych_api.shared.database import DbSession
from munych_api.shared.kernel import DomainError, ErrorCode, SystemClock
from munych_api.shared.supabase import AuthAdmin


def get_staff_service(
    request: Request,
    session: DbSession,
    identity: IdentityServiceDep,
    auth_admin: Annotated[AuthAdmin, Depends(get_auth_admin)],
) -> StaffService:
    settings: Settings = request.app.state.settings
    return StaffService(
        StaffRepository(session),
        SystemClock(),
        identity=identity,
        auth_admin=auth_admin,
        panel_url=settings.panel_url,
        # Para la imagen del QR en el correo: la URL pública de esta misma API.
        api_url=f"{str(request.base_url).rstrip('/')}/api/v1",
    )


StaffServiceDep = Annotated[StaffService, Depends(get_staff_service)]

_staff_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="StaffToken",
    description="Token del enlace personal de un miembro del staff, no un JWT",
)


async def get_staff_person(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_staff_bearer)],
    service: StaffServiceDep,
) -> StaffPerson:
    if credentials is None:
        raise DomainError(ErrorCode.UNAUTHORIZED, INVALID_LINK)
    return await service.authenticate(credentials.credentials)


CurrentStaffPerson = Annotated[StaffPerson, Depends(get_staff_person)]
