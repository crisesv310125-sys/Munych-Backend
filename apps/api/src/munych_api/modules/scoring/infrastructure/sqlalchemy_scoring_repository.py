from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from munych_api.modules.scoring.application.ports import (
    CommitteeInfo,
    ConcurrentWriteError,
    JudgeProgress,
    ProgressData,
)
from munych_api.modules.scoring.domain.models import (
    Score,
    ScoreKey,
    ScoreSubmission,
    ScoringSession,
    SessionContext,
)
from munych_api.shared.database.tables import (
    committee_judges,
    committees,
    criteria,
    delegates,
    delegations,
    events,
    judges,
    rubrics,
    scores,
    scoring_sessions,
)

_rubric_id = func.coalesce(committees.c.rubric_id, events.c.default_rubric_id)


def _score(row: Any) -> Score:
    return Score(
        id=row.id,
        client_id=row.client_id,
        judge_id=row.judge_id,
        delegate_id=row.delegate_id,
        session_id=row.session_id,
        criterion_id=row.criterion_id,
        value=row.value,
        comment=row.comment,
        client_updated_at=row.client_updated_at,
        updated_at=row.updated_at,
    )


def _session(row: Any) -> ScoringSession:
    return ScoringSession(
        id=row.id,
        committee_id=row.committee_id,
        number=row.number,
        status=row.status,
        opened_at=row.opened_at,
        closed_at=row.closed_at,
    )


class SqlAlchemyScoringRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------ lote

    async def _committee_ids(self, committee_id: UUID) -> tuple[UUID | None, frozenset[UUID]]:
        rubric_id = await self._session.scalar(
            select(_rubric_id)
            .select_from(committees.join(events, events.c.id == committees.c.event_id))
            .where(committees.c.id == committee_id)
        )
        delegate_rows = await self._session.execute(
            select(delegates.c.id)
            .join(delegations, delegations.c.id == delegates.c.delegation_id)
            .where(delegations.c.committee_id == committee_id)
        )
        return rubric_id, frozenset(r[0] for r in delegate_rows)

    async def session_context(self, session_id: UUID) -> SessionContext | None:
        row = (
            await self._session.execute(
                select(scoring_sessions, events.c.status.label("event_status"))
                .join(committees, committees.c.id == scoring_sessions.c.committee_id)
                .join(events, events.c.id == committees.c.event_id)
                .where(scoring_sessions.c.id == session_id)
            )
        ).first()
        if row is None:
            return None
        session = _session(row)
        rubric_id, delegate_ids = await self._committee_ids(session.committee_id)
        scale = (
            await self._session.execute(
                select(rubrics.c.scale_min, rubrics.c.scale_max).where(rubrics.c.id == rubric_id)
            )
        ).first()
        criterion_rows = await self._session.execute(
            select(criteria.c.id).where(criteria.c.rubric_id == rubric_id)
        )
        return SessionContext(
            session=session,
            event_closed=row.event_status == "closed",
            # Sin rúbrica no hay criterios válidos: todo ítem se rechaza por criterio.
            scale_min=scale.scale_min if scale else 0,
            scale_max=scale.scale_max if scale else 0,
            criterion_ids=frozenset(r[0] for r in criterion_rows),
            delegate_ids=delegate_ids,
        )

    async def is_assigned(self, judge_id: UUID, committee_id: UUID) -> bool:
        return bool(
            await self._session.scalar(
                select(
                    exists().where(
                        committee_judges.c.committee_id == committee_id,
                        committee_judges.c.judge_id == judge_id,
                        judges.c.user_id == committee_judges.c.judge_id,
                        judges.c.active.is_(True),
                    )
                )
            )
        )

    async def get_by_client_id(self, client_id: UUID) -> Score | None:
        row = (
            await self._session.execute(select(scores).where(scores.c.client_id == client_id))
        ).first()
        return _score(row) if row else None

    async def get_by_key(self, key: ScoreKey) -> Score | None:
        judge_id, delegate_id, session_id, criterion_id = key
        row = (
            await self._session.execute(
                select(scores).where(
                    scores.c.judge_id == judge_id,
                    scores.c.delegate_id == delegate_id,
                    scores.c.session_id == session_id,
                    scores.c.criterion_id == criterion_id,
                )
            )
        ).first()
        return _score(row) if row else None

    @staticmethod
    def _values(item: ScoreSubmission) -> dict[str, Any]:
        return {
            "client_id": item.client_id,
            "value": item.value,
            "comment": item.comment,
            "client_updated_at": item.client_updated_at,
        }

    async def insert(self, item: ScoreSubmission) -> Score:
        try:
            async with self._session.begin_nested():
                row = (
                    await self._session.execute(
                        insert(scores)
                        .values(
                            judge_id=item.judge_id,
                            delegate_id=item.delegate_id,
                            session_id=item.session_id,
                            criterion_id=item.criterion_id,
                            **self._values(item),
                        )
                        .returning(scores)
                    )
                ).one()
        except IntegrityError as exc:
            raise ConcurrentWriteError from exc
        return _score(row)

    async def update(self, score_id: UUID, item: ScoreSubmission) -> Score:
        try:
            async with self._session.begin_nested():
                row = (
                    await self._session.execute(
                        update(scores)
                        .where(scores.c.id == score_id)
                        .values(**self._values(item))
                        .returning(scores)
                    )
                ).one()
        except IntegrityError as exc:
            raise ConcurrentWriteError from exc
        return _score(row)

    # ------------------------------------------------------------ lecturas

    async def judge_scores(self, judge_id: UUID, session_id: UUID) -> list[Score]:
        rows = await self._session.execute(
            select(scores)
            .where(scores.c.judge_id == judge_id, scores.c.session_id == session_id)
            .order_by(scores.c.delegate_id, scores.c.criterion_id)
        )
        return [_score(r) for r in rows]

    async def get_session(self, session_id: UUID) -> ScoringSession | None:
        row = (
            await self._session.execute(
                select(scoring_sessions).where(scoring_sessions.c.id == session_id)
            )
        ).first()
        return _session(row) if row else None

    # ------------------------------------------------------------ sesiones (admin)

    async def get_committee(
        self, committee_id: UUID, organization_id: UUID
    ) -> CommitteeInfo | None:
        row = (
            await self._session.execute(
                select(committees.c.id, events.c.status)
                .join(events, events.c.id == committees.c.event_id)
                .where(committees.c.id == committee_id, events.c.organization_id == organization_id)
            )
        ).first()
        return CommitteeInfo(id=row.id, event_closed=row.status == "closed") if row else None

    async def list_sessions(self, committee_id: UUID) -> list[ScoringSession]:
        rows = await self._session.execute(
            select(scoring_sessions)
            .where(scoring_sessions.c.committee_id == committee_id)
            .order_by(scoring_sessions.c.number)
        )
        return [_session(r) for r in rows]

    async def get_session_by_number(self, committee_id: UUID, number: int) -> ScoringSession | None:
        row = (
            await self._session.execute(
                select(scoring_sessions).where(
                    scoring_sessions.c.committee_id == committee_id,
                    scoring_sessions.c.number == number,
                )
            )
        ).first()
        return _session(row) if row else None

    async def save_session(self, session: ScoringSession) -> None:
        await self._session.execute(
            update(scoring_sessions)
            .where(scoring_sessions.c.id == session.id)
            .values(status=session.status, opened_at=session.opened_at, closed_at=session.closed_at)
        )

    async def progress(self, committee_id: UUID) -> ProgressData:
        rubric_id, delegate_ids = await self._committee_ids(committee_id)
        criteria_count = int(
            await self._session.scalar(
                select(func.count()).select_from(criteria).where(criteria.c.rubric_id == rubric_id)
            )
            or 0
        )
        sessions = await self.list_sessions(committee_id)

        judge_rows = await self._session.execute(
            select(judges.c.user_id, judges.c.full_name)
            .join(committee_judges, committee_judges.c.judge_id == judges.c.user_id)
            .where(committee_judges.c.committee_id == committee_id)
            .order_by(judges.c.full_name, judges.c.user_id)
        )
        counts: dict[UUID, dict[UUID, int]] = defaultdict(dict)
        if delegate_ids:
            count_rows = await self._session.execute(
                select(scores.c.judge_id, scores.c.session_id, func.count())
                .join(scoring_sessions, scoring_sessions.c.id == scores.c.session_id)
                .join(criteria, criteria.c.id == scores.c.criterion_id)
                .where(
                    scoring_sessions.c.committee_id == committee_id,
                    criteria.c.rubric_id == rubric_id,
                    scores.c.delegate_id.in_(delegate_ids),
                )
                .group_by(scores.c.judge_id, scores.c.session_id)
            )
            for judge_id, session_id, count in count_rows:
                counts[judge_id][session_id] = int(count)

        return ProgressData(
            sessions=sessions,
            delegates_count=len(delegate_ids),
            criteria_count=criteria_count,
            judges=[
                JudgeProgress(
                    judge_id=r.user_id, full_name=r.full_name, scored_by_session=counts[r.user_id]
                )
                for r in judge_rows
            ],
        )
