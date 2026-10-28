"""Autenticación y autorización: `verify_jwt`, `require_role` y asignación a comités."""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Path, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from munych_api.shared.auth.tokens import (
    CurrentUser,
    InvalidTokenError,
    JwtVerifier,
    Role,
    SupabaseKeyResolver,
    TokenVerifier,
)
from munych_api.shared.database import DbSession
from munych_api.shared.database.tables import committee_judges, judges, user_roles
from munych_api.shared.kernel import DomainError, ErrorCode

__all__ = [
    "AdminUser",
    "AnyUser",
    "CurrentUser",
    "InvalidTokenError",
    "JudgeUser",
    "JwtVerifier",
    "OrganizationId",
    "Role",
    "SupabaseKeyResolver",
    "TokenVerifier",
    "ensure_committee_assignment",
    "get_current_user",
    "get_organization_id",
    "get_token_verifier",
    "require_committee_assignment",
    "require_role",
    "verify_jwt",
]

_bearer = HTTPBearer(auto_error=False, description="access_token de Supabase Auth")


def get_token_verifier(request: Request) -> TokenVerifier:
    verifier: TokenVerifier = request.app.state.token_verifier
    return verifier


async def verify_jwt(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Se requiere autenticación",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return await verifier.verify(credentials.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


get_current_user = verify_jwt
AnyUser = Annotated[CurrentUser, Depends(verify_jwt)]


def require_role(*roles: Role) -> Callable[[CurrentUser], Awaitable[CurrentUser]]:
    async def dependency(user: AnyUser) -> CurrentUser:
        if user.role not in roles:
            raise DomainError(ErrorCode.FORBIDDEN, "Tu rol no permite realizar esta acción")
        return user

    return dependency


AdminUser = Annotated[CurrentUser, Depends(require_role("admin"))]
JudgeUser = Annotated[CurrentUser, Depends(require_role("judge"))]


async def ensure_committee_assignment(
    session: AsyncSession, judge_id: UUID, committee_id: UUID
) -> str:
    """Devuelve el rol del juez en el comité o lanza `JUDGE_NOT_ASSIGNED`."""
    role = await session.scalar(
        select(committee_judges.c.role)
        .join(judges, judges.c.user_id == committee_judges.c.judge_id)
        .where(
            committee_judges.c.committee_id == committee_id,
            committee_judges.c.judge_id == judge_id,
            judges.c.active.is_(True),
        )
    )
    if role is None:
        raise DomainError(ErrorCode.JUDGE_NOT_ASSIGNED, "No estás asignado a este comité")
    return str(role)


async def require_committee_assignment(
    committee_id: Annotated[UUID, Path()], user: JudgeUser, session: DbSession
) -> CurrentUser:
    await ensure_committee_assignment(session, user.user_id, committee_id)
    return user


async def get_organization_id(user: AnyUser, session: DbSession) -> UUID:
    """Organización del usuario (MVP: una sola organización por usuario)."""
    organization_id = await session.scalar(
        select(user_roles.c.organization_id)
        .where(user_roles.c.user_id == user.user_id)
        .order_by(user_roles.c.created_at)
        .limit(1)
    )
    if organization_id is None:
        raise DomainError(ErrorCode.FORBIDDEN, "Tu usuario no pertenece a ninguna organización")
    return UUID(str(organization_id))


OrganizationId = Annotated[UUID, Depends(get_organization_id)]
