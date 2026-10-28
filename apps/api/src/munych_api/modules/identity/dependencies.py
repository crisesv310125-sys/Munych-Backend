from typing import Annotated

from fastapi import Depends, Request

from munych_api.config import Settings
from munych_api.modules.identity.repository import IdentityRepository
from munych_api.modules.identity.service import IdentityService
from munych_api.shared.database import DbSession
from munych_api.shared.supabase import AuthAdmin


def get_auth_admin(request: Request) -> AuthAdmin:
    auth_admin: AuthAdmin = request.app.state.supabase
    return auth_admin


def get_identity_service(
    request: Request,
    session: DbSession,
    auth_admin: Annotated[AuthAdmin, Depends(get_auth_admin)],
) -> IdentityService:
    settings: Settings = request.app.state.settings
    return IdentityService(IdentityRepository(session), auth_admin, settings.panel_url)


IdentityServiceDep = Annotated[IdentityService, Depends(get_identity_service)]
