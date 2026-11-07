"""Casos de uso: listar, abrir y cerrar sesiones de calificación de un comité."""

from dataclasses import replace
from uuid import UUID

from munych_api.modules.scoring.application.ports import (
    Clock,
    CommitteeInfo,
    PeerVote,
    ScoringRepository,
)
from munych_api.modules.scoring.domain.models import ScoringSession
from munych_api.shared.kernel import DomainError, ErrorCode, NotFoundError


class ManageSessions:
    def __init__(
        self, repository: ScoringRepository, clock: Clock, peer_vote: PeerVote | None = None
    ) -> None:
        self._repo = repository
        self._clock = clock
        self._peer_vote = peer_vote

    async def _committee(self, organization_id: UUID, committee_id: UUID) -> CommitteeInfo:
        committee = await self._repo.get_committee(committee_id, organization_id)
        if committee is None:
            raise NotFoundError("Comité no encontrado")
        return committee

    async def _session(
        self, organization_id: UUID, committee_id: UUID, number: int
    ) -> ScoringSession:
        committee = await self._committee(organization_id, committee_id)
        if committee.event_closed:
            raise DomainError(ErrorCode.EVENT_CLOSED, "El evento está cerrado")
        session = await self._repo.get_session_by_number(committee_id, number)
        if session is None:
            raise NotFoundError(f"La sesión {number} no existe en este comité")
        return session

    async def list(self, organization_id: UUID, committee_id: UUID) -> list[ScoringSession]:
        await self._committee(organization_id, committee_id)
        return await self._repo.list_sessions(committee_id)

    async def open(self, organization_id: UUID, committee_id: UUID, number: int) -> ScoringSession:
        """Abrir una sesión ya abierta no cambia nada (idempotente).

        Al abrirla también se abre el voto entre pares del comité (2026-11-06), en la
        misma transacción, para que los delegados puedan votar desde ese momento.
        """
        session = await self._session(organization_id, committee_id, number)
        if session.is_open:
            return session
        opened = replace(session, status="open", opened_at=self._clock.now(), closed_at=None)
        await self._repo.save_session(opened)
        if self._peer_vote is not None:
            await self._peer_vote.open_with_session(organization_id, committee_id)
        return opened

    async def close(self, organization_id: UUID, committee_id: UUID, number: int) -> ScoringSession:
        """Cerrar una sesión ya cerrada no cambia nada (idempotente)."""
        session = await self._session(organization_id, committee_id, number)
        if not session.is_open:
            return session
        closed = replace(session, status="closed", closed_at=self._clock.now())
        await self._repo.save_session(closed)
        return closed
