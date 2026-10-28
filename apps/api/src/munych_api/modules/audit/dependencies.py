from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from munych_api.modules.audit.repository import AuditRepository
from munych_api.modules.audit.service import AuditService
from munych_api.shared.database import DbSession


def build_audit_service(session: AsyncSession) -> AuditService:
    return AuditService(AuditRepository(session))


def get_audit_service(session: DbSession) -> AuditService:
    return build_audit_service(session)


AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
