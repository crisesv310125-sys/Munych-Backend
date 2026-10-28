from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, exists, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from munych_api.shared.database.tables import (
    committees,
    delegates,
    delegations,
    events,
    rubrics,
    scores,
    scoring_sessions,
)


class EventsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------ eventos

    async def list_events(
        self, organization_id: UUID, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        where = events.c.organization_id == organization_id
        total = await self._session.scalar(select(func.count()).select_from(events).where(where))
        rows = await self._session.execute(
            select(events)
            .where(where)
            .order_by(events.c.starts_on.desc(), events.c.name)
            .limit(limit)
            .offset(offset)
        )
        return [dict(r) for r in rows.mappings()], int(total or 0)

    async def get_event(self, event_id: UUID, organization_id: UUID) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    select(events).where(
                        events.c.id == event_id, events.c.organization_id == organization_id
                    )
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def slug_exists(self, slug: str, exclude_event_id: UUID | None = None) -> bool:
        query = select(exists().where(events.c.slug == slug))
        if exclude_event_id is not None:
            query = select(exists().where(events.c.slug == slug, events.c.id != exclude_event_id))
        return bool(await self._session.scalar(query))

    async def create_event(self, values: dict[str, Any]) -> UUID:
        event_id = await self._session.scalar(
            insert(events).values(**values).returning(events.c.id)
        )
        return UUID(str(event_id))

    async def update_event(self, event_id: UUID, values: dict[str, Any]) -> None:
        if values:
            await self._session.execute(
                update(events).where(events.c.id == event_id).values(**values)
            )

    async def delete_event(self, event_id: UUID) -> None:
        await self._session.execute(delete(events).where(events.c.id == event_id))

    async def rubric_belongs_to_event(self, rubric_id: UUID, event_id: UUID) -> bool:
        return bool(
            await self._session.scalar(
                select(exists().where(rubrics.c.id == rubric_id, rubrics.c.event_id == event_id))
            )
        )

    # ------------------------------------------------------------ comités

    _committee_with_event = select(
        committees, events.c.status.label("event_status"), events.c.organization_id
    ).join(events, events.c.id == committees.c.event_id)

    async def list_committees(
        self, event_id: UUID, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        where = committees.c.event_id == event_id
        total = await self._session.scalar(
            select(func.count()).select_from(committees).where(where)
        )
        rows = await self._session.execute(
            select(committees)
            .where(where)
            .order_by(committees.c.name, committees.c.id)
            .limit(limit)
            .offset(offset)
        )
        return [dict(r) for r in rows.mappings()], int(total or 0)

    async def get_committee(
        self, committee_id: UUID, organization_id: UUID
    ) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    self._committee_with_event.where(
                        committees.c.id == committee_id, events.c.organization_id == organization_id
                    )
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def committee_slug_exists(
        self, event_id: UUID, slug: str, exclude_committee_id: UUID | None = None
    ) -> bool:
        conditions = [committees.c.event_id == event_id, committees.c.slug == slug]
        if exclude_committee_id is not None:
            conditions.append(committees.c.id != exclude_committee_id)
        return bool(await self._session.scalar(select(exists().where(*conditions))))

    async def create_committee(self, values: dict[str, Any]) -> UUID:
        committee_id = await self._session.scalar(
            insert(committees).values(**values).returning(committees.c.id)
        )
        return UUID(str(committee_id))

    async def update_committee(self, committee_id: UUID, values: dict[str, Any]) -> None:
        if values:
            await self._session.execute(
                update(committees).where(committees.c.id == committee_id).values(**values)
            )

    async def delete_committee(self, committee_id: UUID) -> None:
        await self._session.execute(delete(committees).where(committees.c.id == committee_id))

    async def max_delegates_in_committee(self, committee_id: UUID) -> int:
        counts = (
            select(func.count(delegates.c.id).label("n"))
            .select_from(delegations.join(delegates))
            .where(delegations.c.committee_id == committee_id)
            .group_by(delegations.c.id)
            .subquery()
        )
        return int(await self._session.scalar(select(func.coalesce(func.max(counts.c.n), 0))) or 0)

    # ------------------------------------------------------------ sesiones

    async def session_numbers(self, committee_id: UUID) -> list[int]:
        rows = await self._session.execute(
            select(scoring_sessions.c.number).where(scoring_sessions.c.committee_id == committee_id)
        )
        return sorted(int(r[0]) for r in rows)

    async def create_sessions(self, committee_id: UUID, numbers: Sequence[int]) -> None:
        if numbers:
            await self._session.execute(
                insert(scoring_sessions),
                [{"committee_id": committee_id, "number": n} for n in numbers],
            )

    async def sessions_with_scores_above(self, committee_id: UUID, number: int) -> bool:
        return bool(
            await self._session.scalar(
                select(
                    exists().where(
                        scores.c.session_id == scoring_sessions.c.id,
                        scoring_sessions.c.committee_id == committee_id,
                        scoring_sessions.c.number > number,
                    )
                )
            )
        )

    async def delete_sessions_above(self, committee_id: UUID, number: int) -> None:
        await self._session.execute(
            delete(scoring_sessions).where(
                scoring_sessions.c.committee_id == committee_id,
                scoring_sessions.c.number > number,
            )
        )

    # ------------------------------------------------------------ delegaciones

    async def list_delegations(
        self, committee_id: UUID, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        where = delegations.c.committee_id == committee_id
        total = await self._session.scalar(
            select(func.count()).select_from(delegations).where(where)
        )
        rows = await self._session.execute(
            select(delegations)
            .where(where)
            .order_by(
                delegations.c.country_code.nulls_last(),
                delegations.c.character_name,
                delegations.c.id,
            )
            .limit(limit)
            .offset(offset)
        )
        return [dict(r) for r in rows.mappings()], int(total or 0)

    async def list_delegates(self, delegation_ids: Sequence[UUID]) -> list[dict[str, Any]]:
        if not delegation_ids:
            return []
        rows = await self._session.execute(
            select(delegates)
            .where(delegates.c.delegation_id.in_(delegation_ids))
            .order_by(delegates.c.created_at, delegates.c.id)
        )
        return [dict(r) for r in rows.mappings()]

    async def get_delegation(
        self, delegation_id: UUID, organization_id: UUID
    ) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    select(
                        delegations,
                        committees.c.delegation_mode,
                        events.c.status.label("event_status"),
                    )
                    .join(committees, committees.c.id == delegations.c.committee_id)
                    .join(events, events.c.id == committees.c.event_id)
                    .where(
                        delegations.c.id == delegation_id,
                        events.c.organization_id == organization_id,
                    )
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def country_codes_in_committee(self, committee_id: UUID) -> set[str]:
        rows = await self._session.execute(
            select(delegations.c.country_code).where(
                delegations.c.committee_id == committee_id,
                delegations.c.country_code.is_not(None),
            )
        )
        return {str(r[0]) for r in rows}

    async def country_taken(
        self, committee_id: UUID, country_code: str, exclude_delegation_id: UUID | None = None
    ) -> bool:
        conditions = [
            delegations.c.committee_id == committee_id,
            delegations.c.country_code == country_code,
        ]
        if exclude_delegation_id is not None:
            conditions.append(delegations.c.id != exclude_delegation_id)
        return bool(await self._session.scalar(select(exists().where(*conditions))))

    async def create_delegation(self, values: dict[str, Any]) -> UUID:
        delegation_id = await self._session.scalar(
            insert(delegations).values(**values).returning(delegations.c.id)
        )
        return UUID(str(delegation_id))

    async def update_delegation(self, delegation_id: UUID, values: dict[str, Any]) -> None:
        if values:
            await self._session.execute(
                update(delegations).where(delegations.c.id == delegation_id).values(**values)
            )

    async def delete_delegation(self, delegation_id: UUID) -> None:
        await self._session.execute(delete(delegations).where(delegations.c.id == delegation_id))

    # ------------------------------------------------------------ delegados

    async def count_delegates(self, delegation_id: UUID) -> int:
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(delegates)
                .where(delegates.c.delegation_id == delegation_id)
            )
            or 0
        )

    async def get_delegate(self, delegate_id: UUID, organization_id: UUID) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    select(delegates, events.c.status.label("event_status"))
                    .join(delegations, delegations.c.id == delegates.c.delegation_id)
                    .join(committees, committees.c.id == delegations.c.committee_id)
                    .join(events, events.c.id == committees.c.event_id)
                    .where(
                        delegates.c.id == delegate_id, events.c.organization_id == organization_id
                    )
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def create_delegate(self, values: dict[str, Any]) -> UUID:
        delegate_id = await self._session.scalar(
            insert(delegates).values(**values).returning(delegates.c.id)
        )
        return UUID(str(delegate_id))

    async def update_delegate(self, delegate_id: UUID, values: dict[str, Any]) -> None:
        if values:
            await self._session.execute(
                update(delegates).where(delegates.c.id == delegate_id).values(**values)
            )

    async def delete_delegate(self, delegate_id: UUID) -> None:
        await self._session.execute(delete(delegates).where(delegates.c.id == delegate_id))
