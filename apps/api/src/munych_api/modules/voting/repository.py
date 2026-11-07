from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from munych_api.shared.database.tables import (
    committees,
    delegates,
    delegations,
    events,
    peer_votes,
    scoring_sessions,
    voter_tokens,
)


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
            select(peer_votes.c.voter_delegate_id, func.count().label("votes_count"))
            .group_by(peer_votes.c.voter_delegate_id)
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

    async def voter_by_token_hash(
        self, token_hash: str, *, by_code: bool = False
    ) -> dict[str, Any] | None:
        """Acceso por el hash del token o, con `by_code`, por el del código de respaldo."""
        column = voter_tokens.c.code_hash if by_code else voter_tokens.c.token_hash
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
                        events.c.id.label("event_id"),
                        events.c.name.label("event_name"),
                        events.c.slug.label("event_slug"),
                        events.c.status.label("event_status"),
                        events.c.event_type,
                    )
                    .join(delegates, delegates.c.id == voter_tokens.c.delegate_id)
                    .join(delegations, delegations.c.id == delegates.c.delegation_id)
                    .join(committees, committees.c.id == delegations.c.committee_id)
                    .join(events, events.c.id == committees.c.event_id)
                    .where(column == token_hash)
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

    async def committee_progress(self, committee_id: UUID) -> dict[str, Any]:
        """Ventana del voto entre pares y avance de sesiones del comité."""
        closed = (
            select(func.count())
            .where(
                scoring_sessions.c.committee_id == committee_id,
                scoring_sessions.c.status == "closed",
                scoring_sessions.c.closed_at.is_not(None),
            )
            .scalar_subquery()
        )
        row = (
            (
                await self._session.execute(
                    select(
                        committees.c.sessions_count,
                        committees.c.peer_vote_opens_at,
                        committees.c.peer_vote_closes_at,
                        closed.label("sessions_closed"),
                    ).where(committees.c.id == committee_id)
                )
            )
            .mappings()
            .one()
        )
        return dict(row)

    async def picks(self, voter_delegate_id: UUID) -> list[dict[str, Any]]:
        rows = await self._session.execute(
            select(
                peer_votes.c.id,
                peer_votes.c.award_type,
                peer_votes.c.delegation_id,
                peer_votes.c.created_at,
            ).where(peer_votes.c.voter_delegate_id == voter_delegate_id)
        )
        return [dict(r) for r in rows.mappings()]

    async def insert_picks(
        self, voter_delegate_id: UUID, committee_id: UUID, picks: Sequence[tuple[str, UUID]]
    ) -> bool:
        """Guarda el voto completo. False si el delegado ya había votado (otra pestaña)."""
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    insert(peer_votes),
                    [
                        {
                            "voter_delegate_id": voter_delegate_id,
                            "committee_id": committee_id,
                            "award_type": award_type,
                            "delegation_id": delegation_id,
                        }
                        for award_type, delegation_id in picks
                    ],
                )
        except IntegrityError:
            return False
        return True

    # ------------------------------------------------------------ ventana (admin)

    async def event_committees(self, event_id: UUID) -> list[dict[str, Any]]:
        """Comités del evento con su ventana de voto, delegados y votantes que ya enviaron."""
        voters = (
            select(delegations.c.committee_id, func.count(delegates.c.id).label("voters"))
            .join(delegates, delegates.c.delegation_id == delegations.c.id)
            .group_by(delegations.c.committee_id)
            .subquery()
        )
        submitted = (
            select(
                peer_votes.c.committee_id,
                func.count(func.distinct(peer_votes.c.voter_delegate_id)).label("submitted"),
            )
            .group_by(peer_votes.c.committee_id)
            .subquery()
        )
        rows = await self._session.execute(
            select(
                committees.c.id.label("committee_id"),
                committees.c.name.label("committee_name"),
                committees.c.acronym.label("committee_acronym"),
                committees.c.peer_vote_opens_at,
                committees.c.peer_vote_closes_at,
                func.coalesce(voters.c.voters, 0).label("voters"),
                func.coalesce(submitted.c.submitted, 0).label("submitted"),
            )
            .outerjoin(voters, voters.c.committee_id == committees.c.id)
            .outerjoin(submitted, submitted.c.committee_id == committees.c.id)
            .where(committees.c.event_id == event_id)
            .order_by(committees.c.name)
        )
        return [dict(r) for r in rows.mappings()]

    async def committee_event(
        self, committee_id: UUID, organization_id: UUID
    ) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    select(
                        committees.c.id.label("committee_id"),
                        committees.c.peer_vote_opens_at,
                        committees.c.peer_vote_closes_at,
                        events.c.id.label("event_id"),
                        events.c.status,
                        events.c.event_type,
                    )
                    .join(events, events.c.id == committees.c.event_id)
                    .where(
                        committees.c.id == committee_id,
                        events.c.organization_id == organization_id,
                    )
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def set_window(
        self, committee_id: UUID, opens_at: datetime | None, closes_at: datetime | None
    ) -> None:
        await self._session.execute(
            update(committees)
            .where(committees.c.id == committee_id)
            .values(
                peer_vote_opens_at=opens_at, peer_vote_closes_at=closes_at, updated_at=func.now()
            )
        )
