"""Votación de delegados: accesos (admin) y boleta (delegado). Ver ADR-005."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from munych_api.modules.voting.repository import VotingRepository
from munych_api.modules.voting.schemas import (
    BallotCriterionOut,
    BallotDelegationOut,
    BallotOut,
    BallotRubricOut,
    BallotSessionOut,
    BallotVoteOut,
    GeneratedTokenOut,
    GenerateTokensIn,
    TokenStatus,
    VoteIn,
    VoterAccessOut,
)
from munych_api.modules.voting.tokens import (
    expires_at,
    hash_token,
    looks_like_token,
    new_token,
    qr_svg,
)
from munych_api.shared.kernel import Clock, DomainError, ErrorCode, NotFoundError
from munych_api.shared.kernel.catalog import EVENT_TYPES

TOUCH_INTERVAL = timedelta(minutes=5)
"""`last_used_at` se actualiza como mucho cada 5 minutos (la boleta se consulta a menudo)."""

INVALID_ACCESS = "Tu acceso no es válido o ya venció. Pide uno nuevo al staff del evento"


@dataclass(frozen=True, slots=True)
class Voter:
    """Delegado autenticado con su token."""

    delegate_id: UUID
    full_name: str
    delegation_id: UUID
    country_code: str | None
    character_name: str | None
    committee_id: UUID
    committee_name: str
    committee_acronym: str
    rubric_id: UUID | None
    event_name: str
    event_status: str


def _status(row: dict[str, Any], now: datetime) -> TokenStatus:
    if row["issued_at"] is None:
        return "none"
    if row["revoked_at"] is not None:
        return "revoked"
    if row["expires_at"] <= now:
        return "expired"
    return "active"


def _ensure_voting_event(event: dict[str, Any]) -> None:
    if "delegate" not in EVENT_TYPES[event["event_type"]].voter_weights:
        raise DomainError(ErrorCode.CONFLICT, "En este tipo de evento los delegados no votan")
    if event["status"] == "closed":
        raise DomainError(ErrorCode.EVENT_CLOSED, "El evento está cerrado")


class VotingService:
    def __init__(self, repository: VotingRepository, clock: Clock) -> None:
        self._repo = repository
        self._clock = clock

    # ------------------------------------------------------------ accesos (admin)

    async def _require_event(self, organization_id: UUID, event_id: UUID) -> dict[str, Any]:
        event = await self._repo.get_event(event_id, organization_id)
        if event is None:
            raise NotFoundError("Evento no encontrado")
        return event

    async def list_access(self, organization_id: UUID, event_id: UUID) -> list[VoterAccessOut]:
        await self._require_event(organization_id, event_id)
        now = self._clock.now()
        return [
            VoterAccessOut(
                delegate_id=r["delegate_id"],
                full_name=r["full_name"],
                delegation_id=r["delegation_id"],
                country_code=r["country_code"],
                character_name=r["character_name"],
                committee_id=r["committee_id"],
                committee_name=r["committee_name"],
                committee_acronym=r["committee_acronym"],
                status=_status(r, now),
                issued_at=r["issued_at"],
                last_used_at=r["last_used_at"],
                votes_count=r["votes_count"],
            )
            for r in await self._repo.event_delegates(event_id)
        ]

    async def generate(
        self, organization_id: UUID, event_id: UUID, body: GenerateTokensIn, admin_id: UUID
    ) -> list[GeneratedTokenOut]:
        """Genera un acceso nuevo por delegado; revoca el anterior si lo había."""
        event = await self._require_event(organization_id, event_id)
        _ensure_voting_event(event)
        now = self._clock.now()

        if body.delegate_ids is None:
            targets = [
                r for r in await self._repo.event_delegates(event_id) if _status(r, now) != "active"
            ]
        else:
            wanted = list(dict.fromkeys(body.delegate_ids))
            targets = await self._repo.event_delegates(event_id, wanted)
            if len(targets) != len(wanted):
                raise NotFoundError("Algún delegado no pertenece a este evento")
        if not targets:
            return []

        await self._repo.revoke(event_id, [r["delegate_id"] for r in targets], now)
        expiry = expires_at(event["ends_on"])
        generated: list[GeneratedTokenOut] = []
        rows: list[dict[str, Any]] = []
        for r in targets:
            token = new_token()
            url = f"{body.link_base}{token}"
            rows.append(
                {
                    "delegate_id": r["delegate_id"],
                    "event_id": event_id,
                    "token_hash": hash_token(token),
                    "expires_at": expiry,
                    "created_by": admin_id,
                }
            )
            generated.append(
                GeneratedTokenOut(
                    delegate_id=r["delegate_id"],
                    full_name=r["full_name"],
                    country_code=r["country_code"],
                    character_name=r["character_name"],
                    committee_name=r["committee_name"],
                    committee_acronym=r["committee_acronym"],
                    token=token,
                    url=url,
                    qr_svg=qr_svg(url),
                    expires_at=expiry,
                )
            )
        await self._repo.insert_tokens(rows)
        return generated

    async def revoke(self, organization_id: UUID, event_id: UUID, delegate_ids: list[UUID]) -> int:
        await self._require_event(organization_id, event_id)
        return await self._repo.revoke(event_id, delegate_ids, self._clock.now())

    # ------------------------------------------------------------ boleta (delegado)

    async def authenticate(self, token: str) -> Voter:
        """Valida el token: existe, no está revocado ni vencido y su evento admite delegados."""
        if not looks_like_token(token):
            raise DomainError(ErrorCode.UNAUTHORIZED, INVALID_ACCESS)
        row = await self._repo.voter_by_token_hash(hash_token(token))
        now = self._clock.now()
        if (
            row is None
            or row["revoked_at"] is not None
            or row["expires_at"] <= now
            # Un token de un evento no sirve en otro (el delegado pertenece a un solo evento).
            or row["token_event_id"] != row["event_id"]
            or "delegate" not in EVENT_TYPES[row["event_type"]].voter_weights
        ):
            raise DomainError(ErrorCode.UNAUTHORIZED, INVALID_ACCESS)
        if row["last_used_at"] is None or now - row["last_used_at"] >= TOUCH_INTERVAL:
            await self._repo.touch_token(row["token_id"], now)
        return Voter(
            delegate_id=row["delegate_id"],
            full_name=row["full_name"],
            delegation_id=row["delegation_id"],
            country_code=row["country_code"],
            character_name=row["character_name"],
            committee_id=row["committee_id"],
            committee_name=row["committee_name"],
            committee_acronym=row["committee_acronym"],
            rubric_id=row["rubric_id"],
            event_name=row["event_name"],
            event_status=row["event_status"],
        )

    async def _rubric(self, voter: Voter) -> BallotRubricOut | None:
        rubric = await self._repo.rubric(voter.rubric_id) if voter.rubric_id else None
        if rubric is None:
            return None
        return BallotRubricOut(
            scale_min=rubric["scale_min"],
            scale_max=rubric["scale_max"],
            criteria=[
                BallotCriterionOut(
                    id=c["id"],
                    name=c["name"],
                    description=c["description"],
                    weight=float(Decimal(c["weight"])),
                    position=c["position"],
                    level_descriptors=c["level_descriptors"] or {},
                )
                for c in rubric["criteria"]
            ],
        )

    async def _open_session(self, voter: Voter) -> dict[str, Any] | None:
        # En borrador o cerrado no se vota aunque haya una sesión abierta.
        if voter.event_status != "active":
            return None
        return await self._repo.open_session(voter.committee_id)

    async def ballot(self, voter: Voter) -> BallotOut:
        session = await self._open_session(voter)
        votes = await self._repo.votes(voter.delegate_id, session["id"]) if session else []
        return BallotOut(
            voter_name=voter.full_name,
            own_delegation=BallotDelegationOut(
                delegation_id=voter.delegation_id,
                country_code=voter.country_code,
                character_name=voter.character_name,
            ),
            event_name=voter.event_name,
            event_status=voter.event_status,  # type: ignore[arg-type]
            committee_name=voter.committee_name,
            committee_acronym=voter.committee_acronym,
            open_session=(
                BallotSessionOut(
                    session_id=session["id"],
                    number=session["number"],
                    opened_at=session["opened_at"],
                )
                if session
                else None
            ),
            rubric=await self._rubric(voter),
            delegations=[
                BallotDelegationOut(
                    delegation_id=d["id"],
                    country_code=d["country_code"],
                    character_name=d["character_name"],
                )
                for d in await self._repo.committee_delegations(voter.committee_id)
                if d["id"] != voter.delegation_id
            ],
            votes=[BallotVoteOut(**v) for v in votes],
        )

    async def vote(self, voter: Voter, items: list[VoteIn]) -> BallotOut:
        """Guarda los votos en la sesión abierta. Todo el lote se valida antes de guardar."""
        if voter.event_status == "closed":
            raise DomainError(ErrorCode.EVENT_CLOSED, "El evento está cerrado")
        session = await self._open_session(voter)
        if session is None:
            raise DomainError(
                ErrorCode.SESSION_CLOSED, "No hay una sesión abierta; espera a la siguiente"
            )
        rubric = await self._rubric(voter)
        if rubric is None:
            raise DomainError(ErrorCode.CONFLICT, "El comité aún no tiene rúbrica")
        criterion_ids = {c.id for c in rubric.criteria}
        delegation_ids = {
            d["id"] for d in await self._repo.committee_delegations(voter.committee_id)
        }

        cells: dict[tuple[UUID, UUID], int] = {}
        for item in items:
            if item.delegation_id == voter.delegation_id:
                raise DomainError(ErrorCode.FORBIDDEN, "No puedes votar por tu propia delegación")
            if item.delegation_id not in delegation_ids:
                raise DomainError(ErrorCode.NOT_FOUND, "La delegación no pertenece a tu comité")
            if item.criterion_id not in criterion_ids:
                raise DomainError(
                    ErrorCode.NOT_FOUND, "El criterio no pertenece a la rúbrica del comité"
                )
            if not rubric.scale_min <= item.value <= rubric.scale_max:
                raise DomainError(
                    ErrorCode.VALUE_OUT_OF_RANGE,
                    f"El valor {item.value} está fuera de la escala "
                    f"{rubric.scale_min}–{rubric.scale_max}",
                )
            # Si una celda viene repetida en el lote, gana la última.
            cells[(item.delegation_id, item.criterion_id)] = item.value

        await self._repo.upsert_votes(
            voter.delegate_id,
            session["id"],
            [
                (delegation_id, criterion_id, v)
                for (delegation_id, criterion_id), v in cells.items()
            ],
        )
        return await self.ballot(voter)
