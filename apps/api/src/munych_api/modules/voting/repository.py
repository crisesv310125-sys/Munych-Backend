from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from munych_api.shared.database.tables import (
    committees,
    criteria,
    delegate_votes,
    delegates,
    delegations,
    events,
    rubrics,
    scoring_sessions,
    voter_tokens,
)

_rubric_id = func.coalesce(committees.c.rubric_id, events.c.default_rubric_id)


class VotingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------ accesos (admin)

    async def get_event(self, event_id: UUID, organization_id: UUID) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    select(
                        events.c.id,
                        events.c.status,
                        events.c.event_type,
                        events.c.ends_on,
                    ).where(events.c.id == event_id, events.c.organization_id == organization_id)
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def event_delegates(
        self, event_id: UUID, delegate_ids: Sequence[UUID] | None = None
    ) -> list[dict[str, Any]]:
        """Delegados del evento con su delegación, comité y acceso más reciente."""
        latest_token = (
            select(
                voter_tokens.c.delegate_id,
                voter_tokens.c.created_at,
                voter_tokens.c.revoked_at,
                voter_tokens.c.expires_at,
                voter_tokens.c.last_used_at,
            )
            .where(voter_tokens.c.event_id == event_id)
            .distinct(voter_tokens.c.delegate_id)
            .order_by(voter_tokens.c.delegate_id, voter_tokens.c.created_at.desc())
            .subquery()
        )
        votes = (
            select(delegate_votes.c.voter_delegate_id, func.count().label("votes_count"))
            .group_by(delegate_votes.c.voter_delegate_id)
            .subquery()
        )
        query = (
            select(
                delegates.c.id.label("delegate_id"),
                delegates.c.full_name,
                delegations.c.id.label("delegation_id"),
                delegations.c.country_code,
                delegations.c.character_name,
                committees.c.id.label("committee_id"),
                committees.c.name.label("committee_name"),
                committees.c.acronym.label("committee_acronym"),
                latest_token.c.created_at.label("issued_at"),
                latest_token.c.revoked_at,
                latest_token.c.expires_at,
                latest_token.c.last_used_at,
                func.coalesce(votes.c.votes_count, 0).label("votes_count"),
            )
            .join(delegations, delegations.c.id == delegates.c.delegation_id)
            .join(committees, committees.c.id == delegations.c.committee_id)
            .outerjoin(latest_token, latest_token.c.delegate_id == delegates.c.id)
            .outerjoin(votes, votes.c.voter_delegate_id == delegates.c.id)
            .where(committees.c.event_id == event_id)
            .order_by(
                committees.c.name,
                delegations.c.country_code.nulls_last(),
                delegations.c.character_name,
                delegates.c.full_name,
                delegates.c.id,
            )
        )
        if delegate_ids is not None:
            query = query.where(delegates.c.id.in_(delegate_ids))
        rows = await self._session.execute(query)
        return [dict(r) for r in rows.mappings()]

    async def revoke(self, event_id: UUID, delegate_ids: Sequence[UUID], now: datetime) -> int:
        if not delegate_ids:
            return 0
        result = await self._session.execute(
            update(voter_tokens)
            .where(
                voter_tokens.c.event_id == event_id,
                voter_tokens.c.delegate_id.in_(delegate_ids),
                voter_tokens.c.revoked_at.is_(None),
            )
            .values(revoked_at=now)
            .returning(voter_tokens.c.id)
        )
        return len(result.all())

    async def insert_tokens(self, rows: Sequence[dict[str, Any]]) -> None:
        if rows:
            await self._session.execute(insert(voter_tokens), list(rows))

    # ------------------------------------------------------------ boleta (delegado)

    async def voter_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    select(
                        voter_tokens.c.id.label("token_id"),
                        voter_tokens.c.expires_at,
                        voter_tokens.c.revoked_at,
                        voter_tokens.c.last_used_at,
                        voter_tokens.c.event_id.label("token_event_id"),
                        delegates.c.id.label("delegate_id"),
                        delegates.c.full_name,
                        delegations.c.id.label("delegation_id"),
                        delegations.c.country_code,
                        delegations.c.character_name,
                        committees.c.id.label("committee_id"),
                        committees.c.name.label("committee_name"),
                        committees.c.acronym.label("committee_acronym"),
                        _rubric_id.label("rubric_id"),
                        events.c.id.label("event_id"),
                        events.c.name.label("event_name"),
                        events.c.status.label("event_status"),
                        events.c.event_type,
                    )
                    .join(delegates, delegates.c.id == voter_tokens.c.delegate_id)
                    .join(delegations, delegations.c.id == delegates.c.delegation_id)
                    .join(committees, committees.c.id == delegations.c.committee_id)
                    .join(events, events.c.id == committees.c.event_id)
                    .where(voter_tokens.c.token_hash == token_hash)
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def touch_token(self, token_id: UUID, now: datetime) -> None:
        await self._session.execute(
            update(voter_tokens).where(voter_tokens.c.id == token_id).values(last_used_at=now)
        )

    async def rubric(self, rubric_id: UUID) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    select(rubrics.c.scale_min, rubrics.c.scale_max).where(
                        rubrics.c.id == rubric_id
                    )
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        criterion_rows = await self._session.execute(
            select(
                criteria.c.id,
                criteria.c.name,
                criteria.c.description,
                criteria.c.weight,
                criteria.c.position,
                criteria.c.level_descriptors,
            )
            .where(criteria.c.rubric_id == rubric_id)
            .order_by(criteria.c.position)
        )
        return {**dict(row), "criteria": [dict(c) for c in criterion_rows.mappings()]}

    async def committee_delegations(self, committee_id: UUID) -> list[dict[str, Any]]:
        rows = await self._session.execute(
            select(delegations.c.id, delegations.c.country_code, delegations.c.character_name)
            .where(delegations.c.committee_id == committee_id)
            .order_by(
                delegations.c.country_code.nulls_last(),
                delegations.c.character_name,
                delegations.c.id,
            )
        )
        return [dict(r) for r in rows.mappings()]

    async def open_session(self, committee_id: UUID) -> dict[str, Any] | None:
        """La sesión abierta del comité (si hubiera varias, la de número mayor)."""
        row = (
            (
                await self._session.execute(
                    select(
                        scoring_sessions.c.id,
                        scoring_sessions.c.number,
                        scoring_sessions.c.opened_at,
                    )
                    .where(
                        scoring_sessions.c.committee_id == committee_id,
                        scoring_sessions.c.status == "open",
                    )
                    .order_by(scoring_sessions.c.number.desc())
                    .limit(1)
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def votes(self, voter_delegate_id: UUID, session_id: UUID) -> list[dict[str, Any]]:
        rows = await self._session.execute(
            select(
                delegate_votes.c.delegation_id,
                delegate_votes.c.criterion_id,
                delegate_votes.c.value,
            )
            .where(
                delegate_votes.c.voter_delegate_id == voter_delegate_id,
                delegate_votes.c.session_id == session_id,
            )
            .order_by(delegate_votes.c.delegation_id, delegate_votes.c.criterion_id)
        )
        return [dict(r) for r in rows.mappings()]

    async def upsert_votes(
        self, voter_delegate_id: UUID, session_id: UUID, items: Sequence[tuple[UUID, UUID, int]]
    ) -> None:
        """Un voto por (votante, delegación, sesión, criterio): reenviar lo corrige."""
        stmt = pg_insert(delegate_votes).values(
            [
                {
                    "voter_delegate_id": voter_delegate_id,
                    "delegation_id": delegation_id,
                    "session_id": session_id,
                    "criterion_id": criterion_id,
                    "value": value,
                }
                for delegation_id, criterion_id, value in items
            ]
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    delegate_votes.c.voter_delegate_id,
                    delegate_votes.c.delegation_id,
                    delegate_votes.c.session_id,
                    delegate_votes.c.criterion_id,
                ],
                set_={"value": stmt.excluded.value},
                where=delegate_votes.c.value != stmt.excluded.value,
            )
        )
