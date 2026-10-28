"""Dominio de resultados: premios, cupos y ranking del comité."""

import uuid
from decimal import Decimal

import pytest

from munych_api.modules.results.domain.awards import quota_warnings, sort_awards, validate_awards
from munych_api.modules.results.domain.models import (
    Award,
    CommitteeData,
    CommitteeInfo,
    CriterionInfo,
    DelegateInfo,
    DelegationInfo,
    RubricInfo,
    ScoreValue,
    SessionInfo,
)
from munych_api.modules.results.domain.ranking import rank_committee
from munych_api.shared.kernel import DomainError, ErrorCode

A, B = uuid.uuid4(), uuid.uuid4()


def test_quota_warnings_only_when_exceeded() -> None:
    awards = [
        Award("honorable_mention", A),
        Award("honorable_mention", B),
        Award("best_delegate", A),
    ]
    assert quota_warnings(awards, {"honorable_mention": 2, "best_delegate": 1}) == []
    assert quota_warnings(awards, {"honorable_mention": 1, "best_delegate": 1}) == [
        "Mención honorífica: 2 asignados y el cupo es 1"
    ]


def test_validate_awards() -> None:
    validate_awards([Award("best_delegate", A)], [A, B])
    with pytest.raises(DomainError) as exc:
        validate_awards([Award("best_delegate", uuid.uuid4())], [A])
    assert exc.value.code == ErrorCode.NOT_FOUND
    with pytest.raises(DomainError) as exc:
        validate_awards([Award("best_delegate", A), Award("best_delegate", A, 2)], [A])
    assert exc.value.code == ErrorCode.VALIDATION_ERROR
    with pytest.raises(DomainError):
        validate_awards([Award("best_delegate", A, 0)], [A])


def test_sort_awards_by_type_then_position() -> None:
    awards = [
        Award("verbal_commendation", A),
        Award("outstanding_delegate", B, 2),
        Award("outstanding_delegate", A, 1),
        Award("best_delegate", B),
    ]
    assert [(a.award_type, a.position) for a in sort_awards(awards)] == [
        ("best_delegate", 1),
        ("outstanding_delegate", 1),
        ("outstanding_delegate", 2),
        ("verbal_commendation", 1),
    ]


def _committee_data(rubric: RubricInfo | None) -> CommitteeData:
    session = SessionInfo(uuid.uuid4(), 1)
    ana, john = DelegateInfo(uuid.uuid4(), "Ana"), DelegateInfo(uuid.uuid4(), "John")
    mx = DelegationInfo(uuid.uuid4(), "MX", None, "Colegio", (ana,))
    us = DelegationInfo(uuid.uuid4(), "US", None, "Instituto", (john,))
    judge = uuid.uuid4()
    criteria = rubric.criteria if rubric else ()
    scores = tuple(
        ScoreValue(judge, delegate.id, session.id, c.id, value)
        for delegate, value in ((ana, 4), (john, 2))
        for c in criteria
    )
    info = CommitteeInfo(
        uuid.uuid4(), uuid.uuid4(), "disec", "DISEC", "DISEC", "general_assembly", {}, False
    )
    return CommitteeData(info, rubric, (session,), (us, mx), scores)


def test_rank_committee_maps_engine_rows_to_entities() -> None:
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    rubric = RubricInfo(
        1,
        4,
        (CriterionInfo(c1, "Oratoria", Decimal(60), 1), CriterionInfo(c2, "X", Decimal(40), 2)),
    )
    ranking = rank_committee(_committee_data(rubric))
    assert [(e.delegation.country_code, e.position, e.score) for e in ranking] == [
        ("MX", 1, Decimal(100)),
        ("US", 2, Decimal(50)),
    ]
    assert ranking[0].delegates[0].full_name == "Ana"
    assert ranking[0].criteria_averages == {c1: Decimal(4), c2: Decimal(4)}


def test_rank_committee_without_rubric() -> None:
    ranking = rank_committee(_committee_data(None))
    assert [(e.position, e.tied, e.score) for e in ranking] == [(1, True, None), (1, True, None)]


def test_incomplete_flags_use_session_numbers() -> None:
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    rubric = RubricInfo(
        1, 4, (CriterionInfo(c1, "A", Decimal(50), 1), CriterionInfo(c2, "B", Decimal(50), 2))
    )
    data = _committee_data(rubric)
    # Deja al primer delegado con un solo criterio calificado.
    partial = tuple(s for s in data.scores if not (s.criterion_id == c2 and s.value == 4))
    data = CommitteeData(data.committee, rubric, data.sessions, data.delegations, partial)
    mx = next(e for e in rank_committee(data) if e.delegation.country_code == "MX")
    kinds = {(f.kind, f.session_number) for f in mx.incomplete_flags}
    assert ("incomplete", 1) in kinds
    assert mx.score is None
