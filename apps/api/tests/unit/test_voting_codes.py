"""Código corto de respaldo de los accesos de delegados (2026-11-07)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest

from munych_api.modules.voting.repository import VotingRepository
from munych_api.modules.voting.service import VotingService
from munych_api.modules.voting.tokens import (
    CODE_ALPHABET,
    CODE_LENGTH,
    hash_code,
    hash_token,
    new_code,
    new_token,
    normalize_code,
)
from munych_api.shared.kernel import DomainError, ErrorCode

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def test_new_code_is_readable_and_random() -> None:
    codes = {new_code() for _ in range(200)}
    assert len(codes) == 200
    for code in codes:
        first, second = code.split("-")
        assert len(first) + len(second) == CODE_LENGTH
        assert all(c in CODE_ALPHABET for c in first + second)
    assert not set("01OIL") & set(CODE_ALPHABET)


@pytest.mark.parametrize("typed", ["K7M2Q-9XH4T", "k7m2q9xh4t", " k7m2q 9xh4t ", "K7M2Q—9XH4T"])
def test_normalize_accepts_how_people_type_it(typed: str) -> None:
    assert normalize_code(typed) == "K7M2Q9XH4T"


@pytest.mark.parametrize("value", ["", "K7M2Q", "K7M2Q-9XH4T-2", "K7M2Q-9XH40", new_token()])
def test_normalize_rejects_other_shapes(value: str) -> None:
    assert normalize_code(value) is None


def test_code_and_token_hashes_never_collide() -> None:
    assert hash_code("K7M2Q9XH4T") != hash_token("K7M2Q9XH4T")


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeRepository:
    def __init__(self) -> None:
        self.token = new_token()
        self.code = new_code()
        event_id = uuid.uuid4()
        self.row: dict[str, Any] = {
            "token_id": uuid.uuid4(),
            "expires_at": NOW + timedelta(days=3),
            "revoked_at": None,
            "last_used_at": NOW,
            "token_event_id": event_id,
            "delegate_id": uuid.uuid4(),
            "full_name": "Ana Pérez",
            "delegation_id": uuid.uuid4(),
            "country_code": "MX",
            "character_name": None,
            "committee_id": uuid.uuid4(),
            "committee_name": "Asamblea General",
            "committee_acronym": "AG",
            "event_id": event_id,
            "event_name": "SD-MUN 2026",
            "event_slug": "sd-mun-2026",
            "event_status": "active",
            "event_type": "mun_regular",
        }
        self.lookups: list[tuple[str, bool]] = []

    async def voter_by_token_hash(
        self, token_hash: str, *, by_code: bool = False
    ) -> dict[str, Any] | None:
        self.lookups.append((token_hash, by_code))
        expected = hash_code(normalize_code(self.code) or "") if by_code else hash_token(self.token)
        return self.row if token_hash == expected else None

    async def touch_token(self, token_id: UUID, now: datetime) -> None:
        pass


def service(repo: FakeRepository) -> VotingService:
    return VotingService(cast(VotingRepository, repo), FixedClock())


async def test_the_code_works_like_the_token() -> None:
    repo = FakeRepository()
    by_token = await service(repo).authenticate(repo.token)
    by_code = await service(repo).authenticate(repo.code.lower().replace("-", " "))
    assert by_token == by_code
    assert by_code.event_slug == "sd-mun-2026"
    assert [by_code for _, by_code in repo.lookups] == [False, True]


async def test_a_wrong_code_is_rejected() -> None:
    repo = FakeRepository()
    with pytest.raises(DomainError) as exc:
        await service(repo).authenticate(new_code())
    assert exc.value.code == ErrorCode.UNAUTHORIZED


async def test_garbage_is_rejected_without_a_lookup() -> None:
    repo = FakeRepository()
    with pytest.raises(DomainError):
        await service(repo).authenticate("hola")
    assert repo.lookups == []
