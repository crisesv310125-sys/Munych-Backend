"""Votación de delegados: accesos y ventana (admin) y boleta entre pares (delegado).

Ver ADR-005. Desde el 2026-11-06 los delegados no usan la rúbrica: votan una sola
vez por comité Mejor delegado, Delegado distinguido y Mención de honor.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from munych_api.modules.voting.repository import VotingRepository
from munych_api.modules.voting.schemas import (
    BallotAwardOut,
    BallotDelegationOut,
    BallotOut,
    BallotPickOut,
    CommitteePeerVoteOut,
    GeneratedTokenOut,
    GenerateTokensIn,
    PeerVoteStatus,
    PeerVoteWindowIn,
    PeerVoteWindowOut,
    TokenStatus,
    VoterAccessOut,
)
from munych_api.modules.voting.tokens import (
    expires_at,
    hash_token,
    looks_like_token,
    new_token,
    qr_svg,
)
from munych_api.scoring_engine import AWARD_POINTS
from munych_api.shared.kernel import Clock, DomainError, ErrorCode, NotFoundError
from munych_api.shared.kernel.catalog import (
    EVENT_TYPES,
    PEER_AWARD_LABELS,
    PEER_AWARD_TYPES,
    EventType,
    PeerAwardType,
)

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
    event_name: str
    event_status: str
    event_type: EventType


def window_status(
    opens_at: datetime | None, closes_at: datetime | None, event_status: str, now: datetime
) -> PeerVoteStatus:
    """Estado del voto entre pares. Solo está abierto si el evento está activo."""
    if event_status == "closed":
        return "closed" if opens_at is not None else "not_scheduled"
    if opens_at is None:
        return "not_scheduled"
    if closes_at is not None and now >= closes_at:
        return "closed"
    if now < opens_at or event_status != "active":
        return "scheduled"
    return "open"


def required_awards(candidates: int) -> tuple[PeerAwardType, ...]:
    """Premios a votar: los tres, o menos si el comité tiene pocas delegaciones."""
    return PEER_AWARD_TYPES[: min(len(PEER_AWARD_TYPES), candidates)]


def receipt(committee_acronym: str, vote_id: UUID) -> str:
    """Comprobante legible, p. ej. `AG-7K2Q-91` (siglas del comité + parte del id del voto)."""
    prefix = "".join(ch for ch in committee_acronym.upper() if ch.isalnum())[:6] or "MUN"
    code = vote_id.hex.upper()
    return f"{prefix}-{code[:4]}-{code[4:6]}"


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
            event_name=row["event_name"],
            event_status=row["event_status"],
            event_type=row["event_type"],
        )

    async def ballot(self, voter: Voter) -> BallotOut:
        progress = await self._repo.committee_progress(voter.committee_id)
        candidates = [
            d
            for d in await self._repo.committee_delegations(voter.committee_id)
            if d["id"] != voter.delegation_id
        ]
        picks = await self._repo.picks(voter.delegate_id)
        order = {award: i for i, award in enumerate(PEER_AWARD_TYPES)}
        picks.sort(key=lambda p: order.get(p["award_type"], len(order)))
        weight = EVENT_TYPES[voter.event_type].voter_weights.get("delegate", Decimal(0))
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
            sessions_total=progress["sessions_count"],
            sessions_closed=progress["sessions_closed"],
            peer_vote=PeerVoteWindowOut(
                status=window_status(
                    progress["peer_vote_opens_at"],
                    progress["peer_vote_closes_at"],
                    voter.event_status,
                    self._clock.now(),
                ),
                opens_at=progress["peer_vote_opens_at"],
                closes_at=progress["peer_vote_closes_at"],
            ),
            weight=float(weight),
            awards=[
                BallotAwardOut(
                    award_type=award, label=PEER_AWARD_LABELS[award], points=AWARD_POINTS[award]
                )
                for award in required_awards(len(candidates))
            ],
            delegations=[
                BallotDelegationOut(
                    delegation_id=d["id"],
                    country_code=d["country_code"],
                    character_name=d["character_name"],
                )
                for d in candidates
            ],
            picks=[
                BallotPickOut(award_type=p["award_type"], delegation_id=p["delegation_id"])
                for p in picks
            ],
            submitted_at=picks[0]["created_at"] if picks else None,
            receipt=receipt(voter.committee_acronym, picks[0]["id"]) if picks else None,
        )

    async def vote(self, voter: Voter, picks: list[BallotPickOut]) -> BallotOut:
        """Guarda el voto entre pares completo. Se valida todo antes de guardar; no se cambia."""
        if voter.event_status == "closed":
            raise DomainError(ErrorCode.EVENT_CLOSED, "El evento está cerrado")
        progress = await self._repo.committee_progress(voter.committee_id)
        status = window_status(
            progress["peer_vote_opens_at"],
            progress["peer_vote_closes_at"],
            voter.event_status,
            self._clock.now(),
        )
        if status != "open":
            detail = "La votación ya cerró" if status == "closed" else "La votación aún no abre"
            raise DomainError(ErrorCode.SESSION_CLOSED, detail)
        if await self._repo.picks(voter.delegate_id):
            raise DomainError(ErrorCode.CONFLICT, "Ya enviaste tu voto; no se puede cambiar")

        candidates = {
            d["id"]
            for d in await self._repo.committee_delegations(voter.committee_id)
            if d["id"] != voter.delegation_id
        }
        required = required_awards(len(candidates))
        if not required:
            raise DomainError(ErrorCode.CONFLICT, "Tu comité no tiene otras delegaciones")
        if sorted(p.award_type for p in picks) != sorted(required):
            labels = ", ".join(PEER_AWARD_LABELS[a] for a in required)
            raise DomainError(ErrorCode.VALIDATION_ERROR, f"Elige una delegación para: {labels}")
        chosen = [p.delegation_id for p in picks]
        if len(set(chosen)) != len(chosen):
            raise DomainError(
                ErrorCode.VALIDATION_ERROR, "Cada premio debe ir a una delegación distinta"
            )
        for delegation_id in chosen:
            if delegation_id == voter.delegation_id:
                raise DomainError(ErrorCode.FORBIDDEN, "No puedes votar por tu propia delegación")
            if delegation_id not in candidates:
                raise DomainError(ErrorCode.NOT_FOUND, "La delegación no pertenece a tu comité")

        saved = await self._repo.insert_picks(
            voter.delegate_id,
            voter.committee_id,
            [(p.award_type, p.delegation_id) for p in picks],
        )
        if not saved:
            raise DomainError(ErrorCode.CONFLICT, "Ya enviaste tu voto; no se puede cambiar")
        return await self.ballot(voter)

    # ------------------------------------------------------------ ventana (admin)

    async def list_windows(
        self, organization_id: UUID, event_id: UUID
    ) -> list[CommitteePeerVoteOut]:
        event = await self._require_event(organization_id, event_id)
        now = self._clock.now()
        return [
            CommitteePeerVoteOut(
                committee_id=r["committee_id"],
                committee_name=r["committee_name"],
                committee_acronym=r["committee_acronym"],
                status=window_status(
                    r["peer_vote_opens_at"], r["peer_vote_closes_at"], event["status"], now
                ),
                opens_at=r["peer_vote_opens_at"],
                closes_at=r["peer_vote_closes_at"],
                voters=r["voters"],
                submitted=r["submitted"],
            )
            for r in await self._repo.event_committees(event_id)
        ]

    async def _require_committee(self, organization_id: UUID, committee_id: UUID) -> dict[str, Any]:
        row = await self._repo.committee_event(committee_id, organization_id)
        if row is None:
            raise NotFoundError("Comité no encontrado")
        _ensure_voting_event(row)
        return row

    async def open_window(
        self, organization_id: UUID, committee_id: UUID, body: PeerVoteWindowIn
    ) -> PeerVoteWindowOut:
        """Abre (o programa) el voto entre pares. Reabrir quita el cierre anterior."""
        row = await self._require_committee(organization_id, committee_id)
        now = self._clock.now()
        opens_at = body.opens_at or now
        if body.closes_at is not None and body.closes_at <= max(opens_at, now):
            raise DomainError(
                ErrorCode.VALIDATION_ERROR, "El cierre debe ser posterior a la apertura y a ahora"
            )
        await self._repo.set_window(committee_id, opens_at, body.closes_at)
        return PeerVoteWindowOut(
            status=window_status(opens_at, body.closes_at, row["status"], now),
            opens_at=opens_at,
            closes_at=body.closes_at,
        )

    async def close_window(self, organization_id: UUID, committee_id: UUID) -> PeerVoteWindowOut:
        """Cierra el voto entre pares ya (si no estaba abierto, no hace nada)."""
        row = await self._require_committee(organization_id, committee_id)
        now = self._clock.now()
        opens_at, closes_at = row["peer_vote_opens_at"], row["peer_vote_closes_at"]
        if window_status(opens_at, closes_at, row["status"], now) == "open":
            closes_at = now
            await self._repo.set_window(committee_id, opens_at, closes_at)
        return PeerVoteWindowOut(
            status=window_status(opens_at, closes_at, row["status"], now),
            opens_at=opens_at,
            closes_at=closes_at,
        )
