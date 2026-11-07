"""Dominio de resultados con tipos de evento: roles por cuenta y votos de delegados."""

import uuid
from decimal import Decimal

from munych_api.modules.results.domain.models import (
    CommitteeData,
    CommitteeInfo,
    CriterionInfo,
    DelegateInfo,
    DelegationInfo,
    PeerVoteValue,
    RubricInfo,
    ScoreValue,
    SessionInfo,
)
from munych_api.modules.results.domain.ranking import rank_committee
from munych_api.modules.results.domain.snapshot import ranking_entry_to_dict
from munych_api.shared.kernel.catalog import EventType, PeerAwardType

CRITERION = uuid.uuid4()
RUBRIC = RubricInfo(0, 10, (CriterionInfo(CRITERION, "General", Decimal(100), 1),))
SESSION = SessionInfo(uuid.uuid4(), 1)
ANA, JOHN = DelegateInfo(uuid.uuid4(), "Ana"), DelegateInfo(uuid.uuid4(), "John")
MX = DelegationInfo(uuid.uuid4(), "MX", None, None, (ANA,))
US = DelegationInfo(uuid.uuid4(), "US", None, None, (JOHN,))
OTHER = DelegationInfo(uuid.uuid4(), "BR", None, None, ())
INFO = CommitteeInfo(
    uuid.uuid4(), uuid.uuid4(), "disec", "DISEC", "DISEC", "general_assembly", {}, False
)


def _score(role: str, delegate: DelegateInfo, value: int) -> ScoreValue:
    return ScoreValue(uuid.uuid4(), delegate.id, SESSION.id, CRITERION, value, role)


def _vote(voter: DelegateInfo, delegation: DelegationInfo, award: PeerAwardType) -> PeerVoteValue:
    return PeerVoteValue(voter.id, delegation.id, award)


def _data(event_type: EventType) -> CommitteeData:
    return CommitteeData(
        committee=INFO,
        rubric=RUBRIC,
        sessions=(SESSION,),
        delegations=(MX, US),
        scores=(
            _score("chair", ANA, 9),
            _score("moderator", ANA, 7),  # la mesa promedia: 80
            _score("staff", ANA, 5),
            _score("judge", ANA, 10),
            _score("chair", JOHN, 6),
            _score("staff", JOHN, 6),
        ),
        event_type=event_type,
        # Dos votantes (máx. 6 puntos): MX y US reciben 3 cada una → 50.
        # El premio a una delegación de fuera del comité no suma a nadie.
        peer_votes=(
            _vote(JOHN, MX, "best_delegate"),
            _vote(ANA, US, "best_delegate"),
            _vote(ANA, OTHER, "outstanding_delegate"),
        ),
    )


def test_mun_regular_weights_chair_delegates_staff_and_ignores_judges() -> None:
    ranking = rank_committee(_data("mun_regular"))
    mx = next(e for e in ranking if e.delegation.country_code == "MX")
    # Pares: 3 puntos de 6 posibles (2 votantes × 3) = 50.
    assert mx.role_scores == {"chair": Decimal(80), "delegate": Decimal(50), "staff": Decimal(50)}
    # 0.3·80 + 0.5·50 + 0.2·50 = 59 (el juez no cuenta en un MUN regular).
    assert mx.score == Decimal(59)
    us = next(e for e in ranking if e.delegation.country_code == "US")
    # 0.3·60 + 0.5·50 + 0.2·60 = 55
    assert us.score == Decimal(55)
    assert [e.delegation.country_code for e in ranking] == ["MX", "US"]
    # Los votos entre pares no aportan a las medias por criterio (no usan la rúbrica).
    # Escala de la rúbrica (0-10): mesa 8, staff 5 → (30·8 + 20·5) / 50 = 6.8.
    assert mx.criteria_averages[CRITERION] == Decimal("6.8")


def test_national_championship_includes_judges() -> None:
    mx = next(
        e
        for e in rank_committee(_data("national_championship"))
        if e.delegation.country_code == "MX"
    )
    assert mx.role_scores["judge"] == Decimal(100)
    # 0.5·100 + 0.15·80 + 0.25·50 + 0.1·50 = 79.5
    assert mx.score == Decimal("79.5")


def test_judges_only_keeps_pooling_every_account_and_ignores_peer_votes() -> None:
    mx = next(e for e in rank_committee(_data("judges_only")) if e.delegation.country_code == "MX")
    # Media de las 4 cuentas (90, 70, 50, 100) = 77.5, como antes de los tipos de evento.
    assert mx.score == Decimal("77.5")
    assert set(mx.role_scores) == {"judge"}


def test_snapshot_keeps_role_scores() -> None:
    entry = rank_committee(_data("mun_regular"))[0]
    assert ranking_entry_to_dict(entry)["role_scores"] == {
        "chair": 80.0,
        "delegate": 50.0,
        "staff": 50.0,
    }
