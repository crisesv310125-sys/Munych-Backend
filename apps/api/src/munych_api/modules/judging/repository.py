from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from munych_api.shared.database.tables import (
    auth_users,
    committee_judges,
    committees,
    criteria,
    delegates,
    delegations,
    event_judges,
    events,
    judges,
    rubrics,
    scoring_sessions,
)


class JudgingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------ administración

    async def get_committee(
        self, committee_id: UUID, organization_id: UUID
    ) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    select(
                        committees.c.id,
                        committees.c.event_id,
                        events.c.status.label("event_status"),
                    )
                    .join(events, events.c.id == committees.c.event_id)
                    .where(
                        committees.c.id == committee_id, events.c.organization_id == organization_id
                    )
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def list_assignments(self, committee_id: UUID) -> list[dict[str, Any]]:
        rows = await self._session.execute(
            select(
                committee_judges.c.judge_id,
                committee_judges.c.role,
                judges.c.full_name,
                judges.c.active,
                auth_users.c.email,
            )
            .join(judges, judges.c.user_id == committee_judges.c.judge_id)
            .join(auth_users, auth_users.c.id == judges.c.user_id)
            .where(committee_judges.c.committee_id == committee_id)
            .order_by(judges.c.full_name, committee_judges.c.judge_id)
        )
        return [dict(r) for r in rows.mappings()]

    async def existing_judges(self, judge_ids: Sequence[UUID], organization_id: UUID) -> set[UUID]:
        if not judge_ids:
            return set()
        rows = await self._session.execute(
            select(judges.c.user_id).where(
                judges.c.user_id.in_(judge_ids), judges.c.organization_id == organization_id
            )
        )
        return {UUID(str(r[0])) for r in rows}

    async def replace_assignments(
        self, committee_id: UUID, assignments: Sequence[tuple[UUID, str]]
    ) -> None:
        await self._session.execute(
            delete(committee_judges).where(committee_judges.c.committee_id == committee_id)
        )
        if assignments:
            await self._session.execute(
                insert(committee_judges),
                [
                    {"committee_id": committee_id, "judge_id": judge_id, "role": role}
                    for judge_id, role in assignments
                ],
            )

    async def add_judges_to_event(self, event_id: UUID, judge_ids: Sequence[UUID]) -> None:
        if judge_ids:
            await self._session.execute(
                pg_insert(event_judges)
                .values([{"event_id": event_id, "judge_id": j} for j in judge_ids])
                .on_conflict_do_nothing()
            )

    # ------------------------------------------------------------ panel del juez

    async def judge_committees(self, judge_id: UUID) -> list[dict[str, Any]]:
        """Solo eventos activos: en borrador aún no se califica y cerrados ya no."""
        rows = await self._session.execute(
            select(
                committees.c.id.label("committee_id"),
                committees.c.name,
                committees.c.acronym,
                committee_judges.c.role,
                events.c.name.label("event_name"),
                events.c.logo_path,
                events.c.timezone,
                events.c.starts_on,
            )
            .join(committees, committees.c.id == committee_judges.c.committee_id)
            .join(events, events.c.id == committees.c.event_id)
            .join(judges, judges.c.user_id == committee_judges.c.judge_id)
            .where(
                committee_judges.c.judge_id == judge_id,
                judges.c.active.is_(True),
                events.c.status == "active",
            )
            .order_by(events.c.starts_on.desc(), committees.c.name)
        )
        return [dict(r) for r in rows.mappings()]

    async def committee_detail(self, committee_id: UUID) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    select(
                        committees.c.id,
                        committees.c.name,
                        committees.c.acronym,
                        committees.c.type,
                        committees.c.delegation_mode,
                        committees.c.rubric_id,
                        events.c.default_rubric_id,
                        events.c.name.label("event_name"),
                        events.c.logo_path,
                        events.c.timezone,
                        events.c.status.label("event_status"),
                    )
                    .join(events, events.c.id == committees.c.event_id)
                    .where(committees.c.id == committee_id)
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def delegations_with_delegates(self, committee_id: UUID) -> list[dict[str, Any]]:
        rows = await self._session.execute(
            select(
                delegations.c.id,
                delegations.c.country_code,
                delegations.c.character_name,
                delegations.c.institution,
                delegates.c.id.label("delegate_id"),
                delegates.c.full_name,
            )
            .outerjoin(delegates, delegates.c.delegation_id == delegations.c.id)
            .where(delegations.c.committee_id == committee_id)
            .order_by(
                delegations.c.country_code.nulls_last(),
                delegations.c.character_name,
                delegations.c.id,
                delegates.c.created_at,
                delegates.c.id,
            )
        )
        return [dict(r) for r in rows.mappings()]

    async def rubric(self, rubric_id: UUID) -> dict[str, Any] | None:
        row = (
            (await self._session.execute(select(rubrics).where(rubrics.c.id == rubric_id)))
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def criteria(self, rubric_id: UUID) -> list[dict[str, Any]]:
        rows = await self._session.execute(
            select(criteria).where(criteria.c.rubric_id == rubric_id).order_by(criteria.c.position)
        )
        return [dict(r) for r in rows.mappings()]

    async def sessions(self, committee_id: UUID) -> list[dict[str, Any]]:
        rows = await self._session.execute(
            select(
                scoring_sessions.c.id,
                scoring_sessions.c.number,
                scoring_sessions.c.status,
                scoring_sessions.c.opened_at,
                scoring_sessions.c.closed_at,
            )
            .where(scoring_sessions.c.committee_id == committee_id)
            .order_by(scoring_sessions.c.number)
        )
        return [dict(r) for r in rows.mappings()]
