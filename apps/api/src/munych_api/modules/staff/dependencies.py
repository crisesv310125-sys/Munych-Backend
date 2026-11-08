from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from munych_api.modules.staff.repository import StaffRepository
from munych_api.modules.staff.service import INVALID_LINK, StaffPerson, StaffService
from munych_api.shared.database import DbSession
from munych_api.shared.kernel import DomainError, ErrorCode, SystemClock


def get_staff_service(session: DbSession) -> StaffService:
    return StaffService(StaffRepository(session), SystemClock())


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
