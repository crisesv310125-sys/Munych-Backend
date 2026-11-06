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
from munych_api.shared.kernel.catalog import EventType

CRITERION = uuid.uuid4()
RUBRIC = RubricInfo(0, 10, (CriterionInfo(CRITERION, "General", Decimal(100), 1),))
SESSION = SessionInfo(uuid.uuid4(), 1)
ANA, JOHN = DelegateInfo(uuid.uuid4(), "Ana"), DelegateInfo(uuid.uuid4(), "John")
MX = DelegationInfo(uuid.uuid4(), "MX", None, None, (ANA,))
US = DelegationInfo(uuid.uuid4(), "US", None, None, (JOHN,))
INFO = CommitteeInfo(
    uuid.uuid4(), uuid.uuid4(), "disec", "DISEC", "DISEC", "general_assembly", {}, False
)


def _score(role: str, delegate: DelegateInfo, value: int) -> ScoreValue:
    return ScoreValue(uuid.uuid4(), delegate.id, SESSION.id, CRITERION, value, role)


def _vote(voter: DelegateInfo, delegation: DelegationInfo, value: int) -> PeerVoteValue:
    return PeerVoteValue(voter.id, delegation.id, SESSION.id, CRITERION, value)


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
        peer_votes=(_vote(JOHN, MX, 6), _vote(ANA, US, 9)),
    )


def test_mun_regular_weights_chair_delegates_staff_and_ignores_judges() -> None:
    ranking = rank_committee(_data("mun_regular"))
    mx = next(e for e in ranking if e.delegation.country_code == "MX")
    assert mx.role_scores == {"chair": Decimal(80), "delegate": Decimal(60), "staff": Decimal(50)}
    # 0.3·80 + 0.5·60 + 0.2·50 = 64 (el juez no cuenta en un MUN regular).
    assert mx.score == Decimal(64)
    us = next(e for e in ranking if e.delegation.country_code == "US")
    # 0.3·60 + 0.5·90 + 0.2·60 = 75
    assert us.score == Decimal(75)
    assert [e.delegation.country_code for e in ranking] == ["US", "MX"]


def test_national_championship_includes_judges() -> None:
    mx = next(
        e
        for e in rank_committee(_data("national_championship"))
        if e.delegation.country_code == "MX"
    )
    assert mx.role_scores["judge"] == Decimal(100)
    # 0.5·100 + 0.15·80 + 0.25·60 + 0.1·50 = 82
    assert mx.score == Decimal(82)


def test_judges_only_keeps_pooling_every_account_and_ignores_peer_votes() -> None:
    mx = next(e for e in rank_committee(_data("judges_only")) if e.delegation.country_code == "MX")
    # Media de las 4 cuentas (90, 70, 50, 100) = 77.5, como antes de los tipos de evento.
    assert mx.score == Decimal("77.5")
    assert set(mx.role_scores) == {"judge"}


def test_snapshot_keeps_role_scores() -> None:
    entry = rank_committee(_data("mun_regular"))[0]
    assert ranking_entry_to_dict(entry)["role_scores"] == {
        "chair": 60.0,
        "delegate": 90.0,
        "staff": 60.0,
    }
