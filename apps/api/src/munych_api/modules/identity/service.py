from uuid import UUID

import structlog

from munych_api.modules.identity.repository import IdentityRepository
from munych_api.modules.identity.schemas import (
    JudgeInvitationOut,
    JudgeInvite,
    JudgeOut,
    JudgeUpdate,
    MeOut,
)
from munych_api.shared.auth import CurrentUser
from munych_api.shared.kernel import DomainError, ErrorCode, NotFoundError
from munych_api.shared.pagination import Page, PageParams
from munych_api.shared.supabase import AuthAdmin

logger = structlog.get_logger(__name__)


class IdentityService:
    def __init__(
        self, repository: IdentityRepository, auth_admin: AuthAdmin, invite_redirect_url: str
    ) -> None:
        self._repo = repository
        self._auth_admin = auth_admin
        self._invite_redirect_url = invite_redirect_url

    async def me(self, user: CurrentUser) -> MeOut:
        judge = await self._repo.get_judge(user.user_id)
        return MeOut(
            user_id=user.user_id,
            email=user.email,
            role=user.role,
            full_name=judge["full_name"] if judge else None,
        )

    async def list_judges(
        self, organization_id: UUID, page: PageParams, event_id: UUID | None = None
    ) -> Page[JudgeOut]:
        rows, total = await self._repo.list_judges(
            organization_id, page.limit, page.offset, event_id
        )
        return Page[JudgeOut](items=[JudgeOut(**r) for r in rows], total=total)

    async def get_judge(self, organization_id: UUID, judge_id: UUID) -> JudgeOut:
        judge = await self._repo.get_judge(judge_id, organization_id)
        if judge is None:
            raise NotFoundError("Juez no encontrado")
        return JudgeOut(**judge)

    async def invite_judge(self, organization_id: UUID, data: JudgeInvite) -> JudgeOut:
        """Invita por correo; si el usuario ya existe en Auth, lo reutiliza.

        Si ese usuario aún no aceptó una invitación anterior, se le reenvía el correo.
        Con `event_id`, además lo vincula a ese evento (así se suma a un evento nuevo
        un juez que ya existía en la organización).
        """
        if data.event_id is not None and not await self._repo.event_exists(
            data.event_id, organization_id
        ):
            raise NotFoundError("Evento no encontrado")
        email = data.email.lower()
        user_id = await self._repo.find_user_id_by_email(email)
        if user_id is None:
            user_id = await self._send_invitation(email)
            logger.info("judge_invited", user_id=str(user_id))
        else:
            current_role = await self._repo.get_role(user_id, organization_id)
            if current_role == "admin":
                raise DomainError(
                    ErrorCode.CONFLICT, "Ese correo pertenece a un administrador de la organización"
                )
            if not await self._repo.is_email_confirmed(user_id):
                await self._send_invitation(email)
                logger.info("judge_invitation_resent", user_id=str(user_id))
            else:
                logger.info("judge_reused_existing_user", user_id=str(user_id))

        await self._repo.upsert_judge(user_id, organization_id, data.full_name.strip())
        await self._repo.set_role(user_id, organization_id, "judge")
        if data.event_id is not None:
            await self._repo.add_judge_to_event(user_id, data.event_id)
        return await self.get_judge(organization_id, user_id)

    async def list_pending_invitations(
        self, organization_id: UUID, page: PageParams, event_id: UUID | None = None
    ) -> Page[JudgeInvitationOut]:
        rows, total = await self._repo.list_pending_invitations(
            organization_id, page.limit, page.offset, event_id
        )
        return Page[JudgeInvitationOut](items=[JudgeInvitationOut(**r) for r in rows], total=total)

    async def resend_invitation(self, organization_id: UUID, judge_id: UUID) -> JudgeInvitationOut:
        invitation = await self._repo.get_invitation(judge_id, organization_id)
        if invitation is None:
            raise NotFoundError("Juez no encontrado")
        if invitation["email_confirmed_at"] is not None:
            raise DomainError(ErrorCode.CONFLICT, "El juez ya aceptó la invitación")
        if not invitation["email"]:  # pragma: no cover — los invitados siempre tienen correo
            raise DomainError(ErrorCode.CONFLICT, "El juez no tiene correo registrado")
        await self._send_invitation(invitation["email"])
        logger.info("judge_invitation_resent", user_id=str(judge_id))
        refreshed = await self._repo.get_invitation(judge_id, organization_id)
        return JudgeInvitationOut(**(refreshed or invitation))

    async def _send_invitation(self, email: str) -> UUID:
        return await self._auth_admin.invite_user_by_email(
            email, redirect_to=self._invite_redirect_url
        )

    async def update_judge(
        self, organization_id: UUID, judge_id: UUID, data: JudgeUpdate
    ) -> JudgeOut:
        await self.get_judge(organization_id, judge_id)
        values = data.model_dump(exclude_unset=True, exclude_none=True)
        if "full_name" in values:
            values["full_name"] = values["full_name"].strip()
        await self._repo.update_judge(judge_id, values)
        return await self.get_judge(organization_id, judge_id)
