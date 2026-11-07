"""Hoja imprimible de accesos de votación en PDF (2026-11-07)."""

import re
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from reportlab import rl_config

from munych_api.modules.voting.access_sheet import (
    AccessCard,
    delegation_label,
    entry_address,
    render_access_sheet,
    sort_key,
)
from munych_api.modules.voting.repository import VotingRepository
from munych_api.modules.voting.schemas import AccessSheetItemIn
from munych_api.modules.voting.service import VotingService
from munych_api.modules.voting.tokens import (
    hash_code,
    hash_token,
    new_code,
    new_token,
    normalize_code,
)
from munych_api.shared.kernel import DomainError, ErrorCode

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
ORG, EVENT = uuid.uuid4(), uuid.uuid4()
BASE = "https://grandinternational.mx/#/votar/"


@pytest.fixture(autouse=True)
def uncompressed() -> Iterator[None]:
    previous = rl_config.pageCompression
    rl_config.pageCompression = 0
    yield
    rl_config.pageCompression = previous


def pages(content: bytes) -> int:
    return len(re.findall(rb"/Type /Page\b", content))


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeRepository:
    def __init__(self, delegates: list[dict[str, Any]]) -> None:
        self.delegates = {d["delegate_id"]: d for d in delegates}
        self.tokens: dict[UUID, dict[str, Any]] = {}

    def issue(self, delegate_id: UUID) -> AccessSheetItemIn:
        token, code = new_token(), new_code()
        self.tokens[delegate_id] = {
            "delegate_id": delegate_id,
            "token_hash": hash_token(token),
            "code_hash": hash_code(normalize_code(code) or ""),
            "expires_at": NOW + timedelta(days=3),
        }
        return AccessSheetItemIn(delegate_id=delegate_id, token=token, code=code, url=BASE + token)

    async def get_event(self, event_id: UUID, organization_id: UUID) -> dict[str, Any] | None:
        if (event_id, organization_id) != (EVENT, ORG):
            return None
        return {"id": EVENT, "name": "SD-MUN 2026", "brand": "munych", "status": "active"}

    async def event_delegates(
        self, event_id: UUID, delegate_ids: Sequence[UUID] | None = None
    ) -> list[dict[str, Any]]:
        return [self.delegates[i] for i in delegate_ids or [] if i in self.delegates]

    async def active_tokens(
        self, event_id: UUID, delegate_ids: Sequence[UUID]
    ) -> dict[UUID, dict[str, Any]]:
        return {i: self.tokens[i] for i in delegate_ids if i in self.tokens}


def delegate(
    name: str, code: str | None, committee: str = "Asamblea General", character: str | None = None
) -> dict[str, Any]:
    return {
        "delegate_id": uuid.uuid4(),
        "full_name": name,
        "country_code": code,
        "character_name": character,
        "committee_name": committee,
        "committee_acronym": "AG" if committee == "Asamblea General" else "GC",
    }


def service(repo: FakeRepository) -> VotingService:
    return VotingService(cast(VotingRepository, repo), FixedClock())


async def test_sheet_prints_valid_accesses_grouped_and_sorted() -> None:
    people = [
        delegate("Santiago Cruz", "SA"),
        delegate("Maximiliano Rivera", "DE"),
        delegate("Ana Flores", None, "Gabinete de Crisis", character="Director de Inteligencia"),
    ]
    repo = FakeRepository(people)
    items = [repo.issue(p["delegate_id"]) for p in people]
    content = await service(repo).access_sheet(ORG, EVENT, items)
    assert content.startswith(b"%PDF-")
    assert pages(content) == 2  # una hoja por comité
    for text in (b"Maximiliano Rivera", b"Alemania", b"Arabia Saud", b"Director de Inteligencia"):
        assert text in content, text
    assert items[0].code.encode() in content
    assert b"grandinternational.mx/#/votar" in content
    assert items[0].token.encode() not in content.replace(items[0].url.encode(), b"")
    # Alemania (DE) antes que Arabia Saudí (SA): orden alfabético por delegación.
    assert content.index(b"Alemania") < content.index(b"Arabia Saud")


async def test_a_regenerated_access_is_rejected() -> None:
    person = delegate("Diego Cruz", "AR")
    repo = FakeRepository([person])
    old = repo.issue(person["delegate_id"])
    repo.issue(person["delegate_id"])  # se regeneró: el anterior ya no vale
    with pytest.raises(DomainError) as exc:
        await service(repo).access_sheet(ORG, EVENT, [old])
    assert exc.value.code == ErrorCode.VALIDATION_ERROR
    assert "Diego Cruz" in exc.value.detail


async def test_a_wrong_code_or_foreign_url_is_rejected() -> None:
    person = delegate("Diego Cruz", "AR")
    repo = FakeRepository([person])
    item = repo.issue(person["delegate_id"])
    for bad in (
        item.model_copy(update={"code": new_code()}),
        item.model_copy(update={"url": "http://evil.example/#/votar/" + item.token}),
        item.model_copy(update={"url": BASE + "otro"}),
    ):
        with pytest.raises(DomainError):
            await service(repo).access_sheet(ORG, EVENT, [bad])


async def test_unknown_delegate_or_event() -> None:
    repo = FakeRepository([])
    item = AccessSheetItemIn(
        delegate_id=uuid.uuid4(), token=new_token(), code=new_code(), url=BASE + "x" * 32
    )
    with pytest.raises(DomainError) as exc:
        await service(repo).access_sheet(ORG, EVENT, [item])
    assert exc.value.code == ErrorCode.NOT_FOUND
    with pytest.raises(DomainError) as exc:
        await service(repo).access_sheet(ORG, uuid.uuid4(), [item])
    assert exc.value.code == ErrorCode.NOT_FOUND


def test_nine_cards_per_sheet() -> None:
    cards = [
        AccessCard(
            f"Delegado {i}", "México", "Asamblea General", "AG", BASE + "t" * 32, "K7M2Q-9XH4T"
        )
        for i in range(10)
    ]
    content = render_access_sheet(
        event_name="SD-MUN 2026", brand="munych", cards=cards, tokens=["t" * 32] * 10
    )
    assert pages(content) == 2
    assert b"HOJA 1 DE 2" in content
    assert b"1 0 / 1 0" in content  # «AG · 10/10», con letras espaciadas


def test_helpers() -> None:
    assert delegation_label("AE", None) == "Emiratos Árabes Unidos"
    assert delegation_label(None, "Canciller") == "Canciller"
    assert entry_address(BASE + "abc", "abc") == "grandinternational.mx/#/votar"
    assert sorted(["Brasil", "Árabe", "alemania"], key=sort_key) == ["alemania", "Árabe", "Brasil"]
