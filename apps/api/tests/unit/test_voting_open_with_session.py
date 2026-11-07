"""`VotingService.open_with_session`: abrir una sesión abre el voto entre pares."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest

from munych_api.modules.voting.repository import VotingRepository
from munych_api.modules.voting.service import VotingService

NOW = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)
ORG = uuid.uuid4()
COMMITTEE = uuid.uuid4()


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeVotingRepository:
    def __init__(self, **row: Any) -> None:
        self.row: dict[str, Any] | None = {
            "committee_id": COMMITTEE,
            "peer_vote_opens_at": None,
            "peer_vote_closes_at": None,
            "event_id": uuid.uuid4(),
            "status": "active",
            "event_type": "mun_regular",
            **row,
        }
        self.windows: list[tuple[datetime | None, datetime | None]] = []

    async def committee_event(
        self, committee_id: UUID, organization_id: UUID
    ) -> dict[str, Any] | None:
        return self.row if committee_id == COMMITTEE and organization_id == ORG else None

    async def set_window(
        self, committee_id: UUID, opens_at: datetime | None, closes_at: datetime | None
    ) -> None:
        self.windows.append((opens_at, closes_at))


def service(repo: FakeVotingRepository) -> VotingService:
    return VotingService(cast(VotingRepository, repo), FixedClock())


@pytest.mark.parametrize(
    ("opens_at", "closes_at"),
    [
        (None, None),  # sin programar
        (NOW + timedelta(hours=3), None),  # programada para después
        (NOW - timedelta(hours=3), NOW - timedelta(hours=1)),  # ya cerró: se reabre
    ],
)
async def test_opens_now_without_close(
    opens_at: datetime | None, closes_at: datetime | None
) -> None:
    repo = FakeVotingRepository(peer_vote_opens_at=opens_at, peer_vote_closes_at=closes_at)
    await service(repo).open_with_session(ORG, COMMITTEE)
    assert repo.windows == [(NOW, None)]


async def test_keeps_an_open_window_and_its_scheduled_close() -> None:
    repo = FakeVotingRepository(
        peer_vote_opens_at=NOW - timedelta(hours=1), peer_vote_closes_at=NOW + timedelta(hours=1)
    )
    await service(repo).open_with_session(ORG, COMMITTEE)
    assert repo.windows == []


@pytest.mark.parametrize(
    "row",
    [
        {"event_type": "judges_only"},  # los delegados no votan
        {"status": "closed"},  # evento cerrado
    ],
)
async def test_does_nothing_when_not_applicable(row: dict[str, Any]) -> None:
    repo = FakeVotingRepository(**row)
    await service(repo).open_with_session(ORG, COMMITTEE)
    assert repo.windows == []


async def test_unknown_committee_is_ignored() -> None:
    repo = FakeVotingRepository()
    await service(repo).open_with_session(uuid.uuid4(), COMMITTEE)
    assert repo.windows == []
