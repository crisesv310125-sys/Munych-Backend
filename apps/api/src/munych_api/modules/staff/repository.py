from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from munych_api.shared.database.tables import (
    auth_users,
    committee_judges,
    committees,
    delegates,
    delegations,
    events,
    judges,
    organizations,
    staff_award_assignments,
    staff_award_confirmations,
    staff_awards,
    staff_evaluations,
    staff_members,
    staff_people,
    staff_types,
)

DELEGATE_KINDS = ("delegates", "press")
"""Tipos que evalúan personas (delegados); el resto evalúa delegaciones."""


def _rows(result: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in result.mappings()]


def _one(result: Any) -> dict[str, Any] | None:
    row = result.mappings().first()
    return dict(row) if row else None


class StaffRepository:
    """El staff es de la organización; candidatos, asignaciones y confirmaciones, del evento."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------ organización y eventos

    async def organization_name(self, organization_id: UUID) -> str:
        name = await self._session.scalar(
            select(organizations.c.name).where(organizations.c.id == organization_id)
        )
        return str(name or "")

    async def events(self, organization_id: UUID) -> list[dict[str, Any]]:
        """Eventos de la organización, del más reciente al más antiguo."""
        return _rows(
            await self._session.execute(
                select(
                    events.c.id,
                    events.c.name,
                    events.c.status,
                    events.c.event_type,
                    events.c.starts_on,
                    events.c.ends_on,
                )
                .where(events.c.organization_id == organization_id)
                .order_by(events.c.starts_on.desc(), events.c.name)
            )
        )

    async def event_committees(self, event_id: UUID) -> list[dict[str, Any]]:
        return _rows(
            await self._session.execute(
                select(committees.c.id, committees.c.name, committees.c.acronym)
                .where(committees.c.event_id == event_id)
                .order_by(committees.c.name, committees.c.id)
            )
        )

    async def organization_committee_ids(self, organization_id: UUID) -> set[UUID]:
        rows = await self._session.execute(
            select(committees.c.id)
            .join(events, events.c.id == committees.c.event_id)
            .where(events.c.organization_id == organization_id)
        )
        return {r[0] for r in rows}

    async def candidates(
        self, event_id: UUID, evaluates: str, committee_ids: Sequence[UUID] | None
    ) -> list[dict[str, Any]]:
        """Candidatos del tipo en ese evento (`committee_ids=None`: todos sus comités)."""
        label = func.coalesce(delegations.c.character_name, delegations.c.country_code, "")
        where = [committees.c.event_id == event_id]
        if committee_ids is not None:
            where.append(committees.c.id.in_(list(committee_ids)))
        if evaluates in DELEGATE_KINDS:
            query = (
                select(
                    delegates.c.id.label("candidate_id"),
                    delegates.c.full_name.label("label"),
                    label.label("sublabel"),
                    committees.c.id.label("committee_id"),
                    committees.c.acronym.label("committee_acronym"),
                    delegations.c.id.label("delegation_id"),
                )
                .select_from(delegates)
                .join(delegations, delegations.c.id == delegates.c.delegation_id)
                .join(committees, committees.c.id == delegations.c.committee_id)
                .where(*where)
                .order_by(committees.c.name, label, delegates.c.full_name, delegates.c.id)
            )
        else:
            query = (
                select(
                    delegations.c.id.label("candidate_id"),
                    label.label("label"),
                    delegations.c.institution.label("sublabel"),
                    committees.c.id.label("committee_id"),
                    committees.c.acronym.label("committee_acronym"),
                    delegations.c.id.label("delegation_id"),
                )
                .select_from(delegations)
                .join(committees, committees.c.id == delegations.c.committee_id)
                .where(*where)
                .order_by(committees.c.name, label, delegations.c.id)
            )
        return _rows(await self._session.execute(query))

    # ------------------------------------------------------------ tipos

    async def list_types(self, organization_id: UUID) -> list[dict[str, Any]]:
        return _rows(
            await self._session.execute(
                select(staff_types)
                .where(
                    staff_types.c.organization_id == organization_id,
                    staff_types.c.archived_at.is_(None),
                )
                .order_by(staff_types.c.position, staff_types.c.created_at, staff_types.c.id)
            )
        )

    async def get_type(self, type_id: UUID, organization_id: UUID) -> dict[str, Any] | None:
        return _one(
            await self._session.execute(
                select(staff_types).where(
                    staff_types.c.id == type_id,
                    staff_types.c.organization_id == organization_id,
                    staff_types.c.archived_at.is_(None),
                )
            )
        )

    async def name_taken(
        self, organization_id: UUID, name: str, exclude: UUID | None = None
    ) -> bool:
        query = select(func.count()).where(
            staff_types.c.organization_id == organization_id,
            func.lower(staff_types.c.name) == name.lower(),
            staff_types.c.archived_at.is_(None),
        )
        if exclude is not None:
            query = query.where(staff_types.c.id != exclude)
        return bool(await self._session.scalar(query))

    async def insert_type(self, values: dict[str, Any]) -> UUID:
        position = await self._session.scalar(
            select(func.coalesce(func.max(staff_types.c.position), -1) + 1).where(
                staff_types.c.organization_id == values["organization_id"]
            )
        )
        return UUID(
            str(
                await self._session.scalar(
                    insert(staff_types)
                    .values(**values, position=int(position or 0))
                    .returning(staff_types.c.id)
                )
            )
        )

    async def update_type(self, type_id: UUID, values: dict[str, Any]) -> None:
        if values:
            await self._session.execute(
                update(staff_types).where(staff_types.c.id == type_id).values(**values)
            )

    # ------------------------------------------------------------ premios

    async def awards(self, type_ids: Sequence[UUID]) -> list[dict[str, Any]]:
        if not type_ids:
            return []
        return _rows(
            await self._session.execute(
                select(staff_awards)
                .where(
                    staff_awards.c.staff_type_id.in_(list(type_ids)),
                    staff_awards.c.archived_at.is_(None),
                )
                .order_by(staff_awards.c.position, staff_awards.c.created_at, staff_awards.c.id)
            )
        )

    async def get_award(self, award_id: UUID, organization_id: UUID) -> dict[str, Any] | None:
        return _one(
            await self._session.execute(
                select(staff_awards)
                .join(staff_types, staff_types.c.id == staff_awards.c.staff_type_id)
                .where(
                    staff_awards.c.id == award_id,
                    staff_types.c.organization_id == organization_id,
                    staff_awards.c.archived_at.is_(None),
                    staff_types.c.archived_at.is_(None),
                )
            )
        )

    async def insert_awards(self, type_id: UUID, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        start = await self._session.scalar(
            select(func.coalesce(func.max(staff_awards.c.position), -1) + 1).where(
                staff_awards.c.staff_type_id == type_id
            )
        )
        await self._session.execute(
            insert(staff_awards),
            [
                {**item, "staff_type_id": type_id, "position": int(start or 0) + i}
                for i, item in enumerate(items)
            ],
        )

    async def update_award(self, award_id: UUID, values: dict[str, Any]) -> None:
        if values:
            await self._session.execute(
                update(staff_awards).where(staff_awards.c.id == award_id).values(**values)
            )

    async def assignments(self, award_ids: Sequence[UUID], event_id: UUID) -> list[dict[str, Any]]:
        if not award_ids:
            return []
        return _rows(
            await self._session.execute(
                select(staff_award_assignments).where(
                    staff_award_assignments.c.award_id.in_(list(award_ids)),
                    staff_award_assignments.c.event_id == event_id,
                )
            )
        )

    async def upsert_assignment(self, values: dict[str, Any]) -> None:
        """Una fila por lugar (premio, evento, comité, posición): se actualiza, nunca se borra."""
        committee = staff_award_assignments.c.committee_id
        existing = await self._session.scalar(
            select(staff_award_assignments.c.id).where(
                staff_award_assignments.c.award_id == values["award_id"],
                staff_award_assignments.c.event_id == values["event_id"],
                staff_award_assignments.c.position == values["position"],
                committee.is_(None)
                if values["committee_id"] is None
                else committee == values["committee_id"],
            )
        )
        if existing is None:
            await self._session.execute(insert(staff_award_assignments).values(**values))
        else:
            await self._session.execute(
                update(staff_award_assignments)
                .where(staff_award_assignments.c.id == existing)
                .values(**values)
            )

    async def confirmations(
        self, type_ids: Sequence[UUID], event_id: UUID
    ) -> dict[UUID, datetime | None]:
        if not type_ids:
            return {}
        rows = await self._session.execute(
            select(
                staff_award_confirmations.c.staff_type_id,
                staff_award_confirmations.c.confirmed_at,
            ).where(
                staff_award_confirmations.c.staff_type_id.in_(list(type_ids)),
                staff_award_confirmations.c.event_id == event_id,
            )
        )
        return {r.staff_type_id: r.confirmed_at for r in rows}

    async def set_confirmation(
        self, type_id: UUID, event_id: UUID, confirmed_at: datetime | None, by: UUID | None
    ) -> None:
        stmt = pg_insert(staff_award_confirmations).values(
            staff_type_id=type_id, event_id=event_id, confirmed_at=confirmed_at, confirmed_by=by
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    staff_award_confirmations.c.staff_type_id,
                    staff_award_confirmations.c.event_id,
                ],
                set_={
                    "confirmed_at": stmt.excluded.confirmed_at,
                    "confirmed_by": stmt.excluded.confirmed_by,
                },
            )
        )

    # ------------------------------------------------------------ personas y miembros

    async def members(self, type_ids: Sequence[UUID]) -> list[dict[str, Any]]:
        if not type_ids:
            return []
        return _rows(
            await self._session.execute(
                select(
                    staff_members,
                    staff_people.c.full_name,
                    staff_people.c.email,
                    staff_people.c.title,
                    staff_people.c.token_hash,
                    staff_people.c.token_issued_at,
                    staff_people.c.token_expires_at,
                    staff_people.c.last_used_at,
                )
                .join(staff_people, staff_people.c.id == staff_members.c.person_id)
                .where(staff_members.c.staff_type_id.in_(list(type_ids)))
                .order_by(
                    staff_members.c.removed_at.is_not(None),
                    staff_members.c.role,
                    staff_people.c.full_name,
                    staff_members.c.id,
                )
            )
        )

    async def get_member(self, member_id: UUID, organization_id: UUID) -> dict[str, Any] | None:
        return _one(
            await self._session.execute(
                select(staff_members)
                .join(staff_types, staff_types.c.id == staff_members.c.staff_type_id)
                .where(
                    staff_members.c.id == member_id,
                    staff_types.c.organization_id == organization_id,
                )
            )
        )

    async def people(self, organization_id: UUID) -> list[dict[str, Any]]:
        """Personas del staff con los tipos (activos) a los que pertenecen."""
        type_names = (
            select(func.array_agg(staff_types.c.name))
            .select_from(staff_members)
            .join(staff_types, staff_types.c.id == staff_members.c.staff_type_id)
            .where(
                staff_members.c.person_id == staff_people.c.id,
                staff_members.c.removed_at.is_(None),
                staff_types.c.archived_at.is_(None),
            )
            .scalar_subquery()
        )
        return _rows(
            await self._session.execute(
                select(staff_people, type_names.label("types"))
                .where(staff_people.c.organization_id == organization_id)
                .order_by(staff_people.c.full_name, staff_people.c.id)
            )
        )

    async def get_person(self, person_id: UUID, organization_id: UUID) -> dict[str, Any] | None:
        return _one(
            await self._session.execute(
                select(staff_people).where(
                    staff_people.c.id == person_id,
                    staff_people.c.organization_id == organization_id,
                )
            )
        )

    async def person_by_email(self, organization_id: UUID, email: str) -> dict[str, Any] | None:
        return _one(
            await self._session.execute(
                select(staff_people).where(
                    staff_people.c.organization_id == organization_id,
                    func.lower(staff_people.c.email) == email.lower(),
                )
            )
        )

    async def insert_person(self, values: dict[str, Any]) -> UUID:
        return UUID(
            str(
                await self._session.scalar(
                    insert(staff_people).values(**values).returning(staff_people.c.id)
                )
            )
        )

    async def update_person(self, person_id: UUID, values: dict[str, Any]) -> None:
        if values:
            await self._session.execute(
                update(staff_people).where(staff_people.c.id == person_id).values(**values)
            )

    async def upsert_member(
        self,
        type_id: UUID,
        person_id: UUID,
        role: str,
        committee_ids: list[UUID],
        *,
        event_id: UUID | None,
        judge_id: UUID | None = None,
    ) -> UUID:
        """Añade a la persona al tipo en ese evento; si era exmiembro, la vuelve a activar.

        Sin borrar: si ya existe la fila (tipo, persona, evento), se actualiza.
        """
        event_match = (
            staff_members.c.event_id.is_(None)
            if event_id is None
            else staff_members.c.event_id == event_id
        )
        existing = await self._session.scalar(
            select(staff_members.c.id).where(
                staff_members.c.staff_type_id == type_id,
                staff_members.c.person_id == person_id,
                event_match,
            )
        )
        values: dict[str, Any] = {
            "role": role,
            "committee_ids": committee_ids,
            "removed_at": None,
            "evaluations_count": True,
        }
        if judge_id is not None:
            values["judge_id"] = judge_id
        if existing is not None:
            await self._session.execute(
                update(staff_members).where(staff_members.c.id == existing).values(**values)
            )
            return UUID(str(existing))
        return UUID(
            str(
                await self._session.scalar(
                    insert(staff_members)
                    .values(staff_type_id=type_id, person_id=person_id, event_id=event_id, **values)
                    .returning(staff_members.c.id)
                )
            )
        )

    async def event_members(self, event_id: UUID, organization_id: UUID) -> list[dict[str, Any]]:
        """Personas del staff asignadas a ese evento (o a todos), con su tipo de staff."""
        return _rows(
            await self._session.execute(
                select(
                    staff_members,
                    staff_people.c.full_name,
                    staff_people.c.email,
                    staff_people.c.title,
                    staff_people.c.token_issued_at,
                    staff_people.c.token_expires_at,
                    staff_people.c.last_used_at,
                    staff_types.c.name.label("type_name"),
                    staff_types.c.code.label("type_code"),
                    staff_types.c.color.label("type_color"),
                    staff_types.c.access.label("type_access"),
                )
                .join(staff_people, staff_people.c.id == staff_members.c.person_id)
                .join(staff_types, staff_types.c.id == staff_members.c.staff_type_id)
                .where(
                    staff_types.c.organization_id == organization_id,
                    staff_types.c.archived_at.is_(None),
                    staff_members.c.removed_at.is_(None),
                    (staff_members.c.event_id == event_id) | staff_members.c.event_id.is_(None),
                )
                .order_by(staff_types.c.position, staff_people.c.full_name, staff_members.c.id)
            )
        )

    async def user_id_by_email(self, email: str) -> UUID | None:
        user_id = await self._session.scalar(
            select(auth_users.c.id).where(func.lower(auth_users.c.email) == email.lower())
        )
        return UUID(str(user_id)) if user_id is not None else None

    async def assign_committee_role(
        self, judge_id: UUID, committee_ids: Sequence[UUID], role: str
    ) -> None:
        """Asigna la cuenta a esos comités con ese rol (si ya estaba, cambia el rol)."""
        for committee_id in committee_ids:
            stmt = pg_insert(committee_judges).values(
                committee_id=committee_id, judge_id=judge_id, role=role
            )
            await self._session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[committee_judges.c.committee_id, committee_judges.c.judge_id],
                    set_={"role": stmt.excluded.role},
                )
            )

    async def update_member(self, member_id: UUID, values: dict[str, Any]) -> None:
        if values:
            await self._session.execute(
                update(staff_members).where(staff_members.c.id == member_id).values(**values)
            )

    async def organization_judges(self, organization_id: UUID) -> list[dict[str, Any]]:
        return _rows(
            await self._session.execute(
                select(judges.c.full_name, auth_users.c.email)
                .join(auth_users, auth_users.c.id == judges.c.user_id)
                .where(judges.c.organization_id == organization_id, judges.c.active.is_(True))
                .order_by(judges.c.full_name)
            )
        )

    # ------------------------------------------------------------ enlace personal

    async def person_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        return _one(
            await self._session.execute(
                select(staff_people, organizations.c.name.label("organization_name"))
                .join(organizations, organizations.c.id == staff_people.c.organization_id)
                .where(staff_people.c.token_hash == token_hash)
            )
        )

    async def person_types(self, person_id: UUID) -> list[dict[str, Any]]:
        """Asignaciones vigentes de la persona: miembro + tipo de staff."""
        return _rows(
            await self._session.execute(
                select(
                    staff_members.c.id.label("member_id"),
                    staff_members.c.role,
                    staff_members.c.committee_ids.label("member_committee_ids"),
                    staff_members.c.event_id.label("member_event_id"),
                    staff_types,
                )
                .join(staff_types, staff_types.c.id == staff_members.c.staff_type_id)
                .where(
                    staff_members.c.person_id == person_id,
                    staff_members.c.removed_at.is_(None),
                    staff_types.c.archived_at.is_(None),
                )
                .order_by(staff_types.c.position, staff_types.c.name)
            )
        )

    # ------------------------------------------------------------ evaluaciones

    async def evaluations(self, member_ids: Sequence[UUID]) -> list[dict[str, Any]]:
        if not member_ids:
            return []
        return _rows(
            await self._session.execute(
                select(staff_evaluations).where(staff_evaluations.c.member_id.in_(list(member_ids)))
            )
        )

    async def any_evaluation(self, type_id: UUID) -> bool:
        return bool(
            await self._session.scalar(
                select(literal(True))
                .select_from(staff_evaluations)
                .join(staff_members, staff_members.c.id == staff_evaluations.c.member_id)
                .where(staff_members.c.staff_type_id == type_id)
                .limit(1)
            )
        )

    async def upsert_evaluation(
        self,
        member_id: UUID,
        candidate_id: UUID,
        values: dict[str, Any],
        comment: str | None,
        client_updated_at: datetime | None,
    ) -> dict[str, Any]:
        stmt = pg_insert(staff_evaluations).values(
            member_id=member_id,
            candidate_id=candidate_id,
            values=values,
            comment=comment,
            client_updated_at=client_updated_at,
        )
        row = (
            (
                await self._session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[
                            staff_evaluations.c.member_id,
                            staff_evaluations.c.candidate_id,
                        ],
                        set_={
                            "values": stmt.excluded["values"],
                            "comment": stmt.excluded.comment,
                            "client_updated_at": stmt.excluded.client_updated_at,
                        },
                    ).returning(staff_evaluations)
                )
            )
            .mappings()
            .one()
        )
        return dict(row)
