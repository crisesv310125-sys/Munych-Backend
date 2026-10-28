from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, exists, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from munych_api.shared.database.tables import criteria, events, rubrics, scores


class RubricsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_event(self, event_id: UUID, organization_id: UUID) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    select(events.c.id, events.c.status).where(
                        events.c.id == event_id, events.c.organization_id == organization_id
                    )
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def get_rubric(self, rubric_id: UUID, organization_id: UUID) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    select(rubrics, events.c.status.label("event_status"))
                    .join(events, events.c.id == rubrics.c.event_id)
                    .where(rubrics.c.id == rubric_id, events.c.organization_id == organization_id)
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def list_rubrics(self, event_id: UUID) -> list[dict[str, Any]]:
        rows = await self._session.execute(
            select(rubrics).where(rubrics.c.event_id == event_id).order_by(rubrics.c.created_at)
        )
        return [dict(r) for r in rows.mappings()]

    async def list_criteria(self, rubric_ids: Sequence[UUID]) -> list[dict[str, Any]]:
        if not rubric_ids:
            return []
        rows = await self._session.execute(
            select(criteria)
            .where(criteria.c.rubric_id.in_(rubric_ids))
            .order_by(criteria.c.rubric_id, criteria.c.position)
        )
        return [dict(r) for r in rows.mappings()]

    async def create_rubric(
        self, event_id: UUID, name: str, scale_min: int, scale_max: int
    ) -> UUID:
        rubric_id = await self._session.scalar(
            insert(rubrics)
            .values(event_id=event_id, name=name, scale_min=scale_min, scale_max=scale_max)
            .returning(rubrics.c.id)
        )
        return UUID(str(rubric_id))

    async def update_rubric(self, rubric_id: UUID, values: dict[str, Any]) -> None:
        await self._session.execute(
            update(rubrics).where(rubrics.c.id == rubric_id).values(**values)
        )

    async def insert_criterion(self, rubric_id: UUID, values: dict[str, Any]) -> None:
        await self._session.execute(insert(criteria).values(rubric_id=rubric_id, **values))

    async def update_criterion(self, criterion_id: UUID, values: dict[str, Any]) -> None:
        await self._session.execute(
            update(criteria).where(criteria.c.id == criterion_id).values(**values)
        )

    async def delete_criteria(self, criterion_ids: Sequence[UUID]) -> None:
        if criterion_ids:
            await self._session.execute(delete(criteria).where(criteria.c.id.in_(criterion_ids)))

    async def criteria_with_scores(self, criterion_ids: Sequence[UUID]) -> set[UUID]:
        if not criterion_ids:
            return set()
        rows = await self._session.execute(
            select(scores.c.criterion_id).distinct().where(scores.c.criterion_id.in_(criterion_ids))
        )
        return {UUID(str(r[0])) for r in rows}

    async def rubric_has_scores(self, rubric_id: UUID) -> bool:
        has_scores = await self._session.scalar(
            select(
                exists().where(
                    scores.c.criterion_id == criteria.c.id, criteria.c.rubric_id == rubric_id
                )
            )
        )
        return bool(has_scores)
