from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from munych_api.shared.database.tables import auth_users, event_judges, events, judges, user_roles

_JUDGE_COLUMNS = (
    judges.c.user_id.label("judge_id"),
    auth_users.c.email,
    judges.c.full_name,
    judges.c.active,
)

_INVITATION_COLUMNS = (
    judges.c.user_id.label("judge_id"),
    auth_users.c.email,
    judges.c.full_name,
    auth_users.c.invited_at,
)


def _in_event(event_id: UUID | None) -> tuple[Any, ...]:
    """Filtro opcional: solo jueces vinculados a `event_id`."""
    if event_id is None:
        return ()
    return (
        judges.c.user_id.in_(
            select(event_judges.c.judge_id).where(event_judges.c.event_id == event_id)
        ),
    )


class IdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_user_id_by_email(self, email: str) -> UUID | None:
        user_id = await self._session.scalar(
            select(auth_users.c.id).where(func.lower(auth_users.c.email) == email.lower())
        )
        return UUID(str(user_id)) if user_id is not None else None

    async def get_role(self, user_id: UUID, organization_id: UUID) -> str | None:
        role = await self._session.scalar(
            select(user_roles.c.role).where(
                user_roles.c.user_id == user_id, user_roles.c.organization_id == organization_id
            )
        )
        return str(role) if role is not None else None

    async def set_role(self, user_id: UUID, organization_id: UUID, role: str) -> None:
        stmt = insert(user_roles).values(
            user_id=user_id, organization_id=organization_id, role=role
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[user_roles.c.user_id, user_roles.c.organization_id],
                set_={"role": stmt.excluded.role},
            )
        )

    async def get_judge(
        self, user_id: UUID, organization_id: UUID | None = None
    ) -> dict[str, Any] | None:
        query = (
            select(*_JUDGE_COLUMNS)
            .join(auth_users, auth_users.c.id == judges.c.user_id)
            .where(judges.c.user_id == user_id)
        )
        if organization_id is not None:
            query = query.where(judges.c.organization_id == organization_id)
        row = (await self._session.execute(query)).mappings().first()
        return dict(row) if row else None

    async def get_event(self, event_id: UUID, organization_id: UUID) -> dict[str, Any] | None:
        """Datos del evento que se muestran en el correo de invitación."""
        row = (
            await self._session.execute(
                select(events.c.name, events.c.venue, events.c.starts_on, events.c.ends_on).where(
                    events.c.id == event_id, events.c.organization_id == organization_id
                )
            )
        ).first()
        return dict(row._mapping) if row else None

    async def add_judge_to_event(self, user_id: UUID, event_id: UUID) -> None:
        await self._session.execute(
            insert(event_judges)
            .values(event_id=event_id, judge_id=user_id)
            .on_conflict_do_nothing()
        )

    async def list_judges(
        self, organization_id: UUID, limit: int, offset: int, event_id: UUID | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        # Solo jueces que ya aceptaron la invitación (abrieron el enlace de Supabase).
        where = (
            judges.c.organization_id == organization_id,
            auth_users.c.email_confirmed_at.is_not(None),
            *_in_event(event_id),
        )
        joined = judges.join(auth_users, auth_users.c.id == judges.c.user_id)
        total = await self._session.scalar(select(func.count()).select_from(joined).where(*where))
        rows = (
            await self._session.execute(
                select(*_JUDGE_COLUMNS)
                .select_from(joined)
                .where(*where)
                .order_by(judges.c.full_name, judges.c.user_id)
                .limit(limit)
                .offset(offset)
            )
        ).mappings()
        return [dict(r) for r in rows], int(total or 0)

    async def is_email_confirmed(self, user_id: UUID) -> bool:
        confirmed_at = await self._session.scalar(
            select(auth_users.c.email_confirmed_at).where(auth_users.c.id == user_id)
        )
        return confirmed_at is not None

    async def list_pending_invitations(
        self, organization_id: UUID, limit: int, offset: int, event_id: UUID | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        where = (
            judges.c.organization_id == organization_id,
            auth_users.c.email_confirmed_at.is_(None),
            *_in_event(event_id),
        )
        joined = judges.join(auth_users, auth_users.c.id == judges.c.user_id)
        total = await self._session.scalar(select(func.count()).select_from(joined).where(*where))
        rows = (
            await self._session.execute(
                select(*_INVITATION_COLUMNS)
                .select_from(joined)
                .where(*where)
                .order_by(auth_users.c.invited_at.desc().nulls_last(), judges.c.user_id)
                .limit(limit)
                .offset(offset)
            )
        ).mappings()
        return [dict(r) for r in rows], int(total or 0)

    async def get_invitation(self, user_id: UUID, organization_id: UUID) -> dict[str, Any] | None:
        """Invitación del juez (aceptada o no); `None` si no es juez de la organización."""
        row = (
            (
                await self._session.execute(
                    select(*_INVITATION_COLUMNS, auth_users.c.email_confirmed_at)
                    .join(auth_users, auth_users.c.id == judges.c.user_id)
                    .where(judges.c.user_id == user_id, judges.c.organization_id == organization_id)
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def upsert_judge(self, user_id: UUID, organization_id: UUID, full_name: str) -> None:
        stmt = insert(judges).values(
            user_id=user_id, organization_id=organization_id, full_name=full_name, active=True
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[judges.c.user_id],
                set_={"full_name": stmt.excluded.full_name, "active": True},
            )
        )

    async def update_judge(self, user_id: UUID, values: dict[str, Any]) -> None:
        if values:
            await self._session.execute(
                judges.update().where(judges.c.user_id == user_id).values(**values)
            )
