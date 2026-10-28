from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from munych_api.modules.results.application.ports import PublicResult, ScoreDetail
from munych_api.modules.results.domain.models import (
    Award,
    CommitteeData,
    CommitteeInfo,
    CriterionInfo,
    DelegateInfo,
    DelegationInfo,
    EventInfo,
    PublicationSettings,
    RubricInfo,
    ScoreValue,
    SessionInfo,
)
from munych_api.shared.database.tables import (
    awards,
    committees,
    criteria,
    delegates,
    delegations,
    events,
    judges,
    public_results,
    result_snapshots,
    rubrics,
    scores,
    scoring_sessions,
)


class SqlAlchemyResultsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------ comités y premios

    async def committee_data(
        self, committee_id: UUID, organization_id: UUID
    ) -> CommitteeData | None:
        row = (
            await self._session.execute(
                select(
                    committees,
                    events.c.status.label("event_status"),
                    func.coalesce(committees.c.rubric_id, events.c.default_rubric_id).label(
                        "effective_rubric_id"
                    ),
                )
                .join(events, events.c.id == committees.c.event_id)
                .where(committees.c.id == committee_id, events.c.organization_id == organization_id)
            )
        ).first()
        if row is None:
            return None

        rubric = None
        rubric_row = (
            await self._session.execute(
                select(rubrics.c.scale_min, rubrics.c.scale_max).where(
                    rubrics.c.id == row.effective_rubric_id
                )
            )
        ).first()
        if rubric_row is not None:
            criterion_rows = await self._session.execute(
                select(criteria.c.id, criteria.c.name, criteria.c.weight, criteria.c.position)
                .where(criteria.c.rubric_id == row.effective_rubric_id)
                .order_by(criteria.c.position)
            )
            rubric = RubricInfo(
                scale_min=rubric_row.scale_min,
                scale_max=rubric_row.scale_max,
                criteria=tuple(
                    CriterionInfo(c.id, c.name, Decimal(c.weight), c.position)
                    for c in criterion_rows
                ),
            )

        session_rows = await self._session.execute(
            select(scoring_sessions.c.id, scoring_sessions.c.number)
            .where(scoring_sessions.c.committee_id == committee_id)
            .order_by(scoring_sessions.c.number)
        )
        delegation_rows = (
            await self._session.execute(
                select(delegations)
                .where(delegations.c.committee_id == committee_id)
                .order_by(delegations.c.country_code.nulls_last(), delegations.c.character_name)
            )
        ).all()
        delegate_rows = await self._session.execute(
            select(delegates.c.id, delegates.c.delegation_id, delegates.c.full_name)
            .join(delegations, delegations.c.id == delegates.c.delegation_id)
            .where(delegations.c.committee_id == committee_id)
            .order_by(delegates.c.created_at, delegates.c.id)
        )
        by_delegation: dict[UUID, list[DelegateInfo]] = defaultdict(list)
        for d in delegate_rows:
            by_delegation[d.delegation_id].append(DelegateInfo(d.id, d.full_name))

        score_rows = await self._session.execute(
            select(
                scores.c.judge_id,
                scores.c.delegate_id,
                scores.c.session_id,
                scores.c.criterion_id,
                scores.c.value,
            )
            .join(scoring_sessions, scoring_sessions.c.id == scores.c.session_id)
            .where(scoring_sessions.c.committee_id == committee_id)
        )

        return CommitteeData(
            committee=CommitteeInfo(
                id=row.id,
                event_id=row.event_id,
                slug=row.slug,
                name=row.name,
                acronym=row.acronym,
                type=row.type,
                award_quotas=dict(row.award_quotas or {}),
                event_closed=row.event_status == "closed",
            ),
            rubric=rubric,
            sessions=tuple(SessionInfo(s.id, s.number) for s in session_rows),
            delegations=tuple(
                DelegationInfo(
                    id=d.id,
                    country_code=d.country_code,
                    character_name=d.character_name,
                    institution=d.institution,
                    delegates=tuple(by_delegation[d.id]),
                )
                for d in delegation_rows
            ),
            scores=tuple(
                ScoreValue(s.judge_id, s.delegate_id, s.session_id, s.criterion_id, s.value)
                for s in score_rows
            ),
        )

    async def get_awards(self, committee_id: UUID) -> list[Award]:
        rows = await self._session.execute(
            select(awards.c.award_type, awards.c.delegation_id, awards.c.position).where(
                awards.c.committee_id == committee_id
            )
        )
        return [Award(r.award_type, r.delegation_id, r.position) for r in rows]

    async def replace_awards(
        self, committee_id: UUID, items: list[Award], assigned_by: UUID, assigned_at: datetime
    ) -> None:
        await self._session.execute(delete(awards).where(awards.c.committee_id == committee_id))
        if items:
            await self._session.execute(
                insert(awards),
                [
                    {
                        "committee_id": committee_id,
                        "award_type": a.award_type,
                        "delegation_id": a.delegation_id,
                        "position": a.position,
                        "assigned_by": assigned_by,
                        "assigned_at": assigned_at,
                    }
                    for a in items
                ],
            )

    # ------------------------------------------------------------ eventos

    async def get_event(self, event_id: UUID, organization_id: UUID) -> EventInfo | None:
        row = (
            await self._session.execute(
                select(events).where(
                    events.c.id == event_id, events.c.organization_id == organization_id
                )
            )
        ).first()
        if row is None:
            return None
        return EventInfo(
            id=row.id,
            slug=row.slug,
            name=row.name,
            brand=row.brand,
            logo_path=row.logo_path,
            venue=row.venue,
            timezone=row.timezone,
            starts_on=row.starts_on,
            ends_on=row.ends_on,
            status=row.status,
            publication_settings=PublicationSettings.from_dict(row.publication_settings),
        )

    async def committee_ids(self, event_id: UUID) -> list[UUID]:
        rows = await self._session.execute(
            select(committees.c.id)
            .where(committees.c.event_id == event_id)
            .order_by(committees.c.name, committees.c.id)
        )
        return [r[0] for r in rows]

    async def open_sessions_count(self, event_id: UUID) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(scoring_sessions)
            .join(committees, committees.c.id == scoring_sessions.c.committee_id)
            .where(committees.c.event_id == event_id, scoring_sessions.c.status == "open")
        )
        return int(count or 0)

    async def close_event(self, event_id: UUID) -> None:
        await self._session.execute(
            update(events).where(events.c.id == event_id).values(status="closed")
        )

    async def insert_snapshot(
        self, event_id: UUID, data: dict[str, Any], created_by: UUID
    ) -> tuple[UUID, datetime]:
        row = (
            await self._session.execute(
                insert(result_snapshots)
                .values(event_id=event_id, data=data, created_by=created_by)
                .returning(result_snapshots.c.id, result_snapshots.c.created_at)
            )
        ).one()
        return row.id, row.created_at

    async def latest_snapshot(self, event_id: UUID) -> dict[str, Any] | None:
        data = await self._session.scalar(
            select(result_snapshots.c.data)
            .where(result_snapshots.c.event_id == event_id)
            .order_by(result_snapshots.c.created_at.desc())
            .limit(1)
        )
        return dict(data) if data is not None else None

    async def score_details(self, event_id: UUID) -> list[ScoreDetail]:
        rows = await self._session.execute(
            select(
                committees.c.name.label("committee"),
                func.coalesce(delegations.c.country_code, delegations.c.character_name).label(
                    "delegation"
                ),
                delegates.c.full_name.label("delegate"),
                func.coalesce(delegates.c.institution, delegations.c.institution).label(
                    "institution"
                ),
                scoring_sessions.c.number.label("session_number"),
                judges.c.full_name.label("judge"),
                criteria.c.name.label("criterion"),
                criteria.c.position.label("criterion_position"),
                scores.c.value,
                scores.c.comment,
                func.coalesce(scores.c.updated_at, scores.c.created_at).label("updated_at"),
            )
            .select_from(scores)
            .join(delegates, delegates.c.id == scores.c.delegate_id)
            .join(delegations, delegations.c.id == delegates.c.delegation_id)
            .join(committees, committees.c.id == delegations.c.committee_id)
            .join(scoring_sessions, scoring_sessions.c.id == scores.c.session_id)
            .join(judges, judges.c.user_id == scores.c.judge_id)
            .join(criteria, criteria.c.id == scores.c.criterion_id)
            .where(committees.c.event_id == event_id)
            .order_by(
                committees.c.name,
                delegations.c.country_code.nulls_last(),
                delegations.c.character_name,
                delegates.c.full_name,
                scoring_sessions.c.number,
                judges.c.full_name,
                criteria.c.position,
            )
        )
        return [
            ScoreDetail(
                committee=r.committee,
                delegation=r.delegation or "",
                delegate=r.delegate,
                institution=r.institution,
                session_number=r.session_number,
                judge=r.judge,
                criterion=r.criterion,
                value=r.value,
                comment=r.comment,
                updated_at=r.updated_at,
            )
            for r in rows
        ]

    # ------------------------------------------------------------ publicación

    async def save_publication_settings(
        self, event_id: UUID, settings: PublicationSettings
    ) -> None:
        await self._session.execute(
            update(events)
            .where(events.c.id == event_id)
            .values(publication_settings=settings.to_dict())
        )

    async def get_public_result(self, event_id: UUID) -> PublicResult | None:
        row = (
            await self._session.execute(
                select(public_results).where(public_results.c.event_id == event_id)
            )
        ).first()
        if row is None:
            return None
        return PublicResult(
            version=row.version,
            published=row.published,
            published_at=row.published_at,
            data=dict(row.data),
        )

    async def upsert_public_result(
        self,
        *,
        event_id: UUID,
        event_slug: str,
        version: int,
        data: dict[str, Any],
        published_at: datetime,
    ) -> None:
        stmt = pg_insert(public_results).values(
            event_slug=event_slug,
            event_id=event_id,
            published=True,
            version=version,
            data=data,
            published_at=published_at,
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[public_results.c.event_id],
                set_={
                    "event_slug": stmt.excluded.event_slug,
                    "published": True,
                    "version": stmt.excluded.version,
                    "data": stmt.excluded.data,
                    "published_at": stmt.excluded.published_at,
                },
            )
        )

    async def unpublish(self, event_id: UUID) -> bool:
        result = await self._session.execute(
            update(public_results)
            .where(public_results.c.event_id == event_id)
            .values(published=False)
            .returning(public_results.c.event_id)
        )
        return result.first() is not None

    async def commit(self) -> None:
        await self._session.commit()
