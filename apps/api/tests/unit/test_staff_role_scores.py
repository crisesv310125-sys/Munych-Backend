"""Tipos de staff que cuentan en el ranking (`counts_as`): sustituyen la nota de su rol."""

import uuid
from dataclasses import replace
from decimal import Decimal

from munych_api.modules.results.domain.models import (
    CommitteeData,
    CommitteeInfo,
    CriterionInfo,
    DelegateInfo,
    DelegationInfo,
    RubricInfo,
    ScoreValue,
    SessionInfo,
)
from munych_api.modules.results.domain.ranking import rank_committee, role_inputs

D = Decimal


def _data() -> CommitteeData:
    session = SessionInfo(uuid.uuid4(), 1)
    ana, john = DelegateInfo(uuid.uuid4(), "Ana"), DelegateInfo(uuid.uuid4(), "John")
    mx = DelegationInfo(uuid.uuid4(), "MX", None, None, (ana,))
    us = DelegationInfo(uuid.uuid4(), "US", None, None, (john,))
    criterion = CriterionInfo(uuid.uuid4(), "Oratoria", D(100), 1)
    chair = uuid.uuid4()
    scores = (
        ScoreValue(chair, ana.id, session.id, criterion.id, 4, "chair"),
        ScoreValue(chair, john.id, session.id, criterion.id, 2, "chair"),
    )
    info = CommitteeInfo(
        uuid.uuid4(), uuid.uuid4(), "disec", "DISEC", "DISEC", "general_assembly", {}, False
    )
    return CommitteeData(
        info,
        RubricInfo(1, 4, (criterion,)),
        (session,),
        (mx, us),
        scores,
        event_type="mun_regular",
    )


def test_without_staff_types_roles_come_from_accounts() -> None:
    data = _data()
    roles = role_inputs(data)
    assert roles["chair"].scores
    assert roles["chair"].delegation_scores is None
    ranking = rank_committee(data)
    assert [e.delegation.country_code for e in ranking] == ["MX", "US"]


def test_staff_type_scores_replace_the_role() -> None:
    data = _data()
    mx, us = data.delegations
    # La Mesa Directiva (tipo de staff) prefiere a US; sustituye a las cuentas «chair».
    data = replace(data, staff_role_scores={"chair": {mx.id: D(40), us.id: D(90)}})
    roles = role_inputs(data)
    assert roles["chair"].delegation_scores == {str(mx.id): D(40), str(us.id): D(90)}
    ranking = rank_committee(data)
    assert [(e.delegation.country_code, e.score) for e in ranking] == [
        ("US", D(90)),
        ("MX", D(40)),
    ]
    assert ranking[0].role_scores["chair"] == D(90)


def test_staff_weight_combines_with_other_roles() -> None:
    data = _data()
    mx, us = data.delegations
    # Mesa (cuentas): MX 100, US 50 · Staff (tipos): MX 0, US 100. Pesos 30 / 20.
    data = replace(data, staff_role_scores={"staff": {mx.id: D(0), us.id: D(100)}})
    by_country = {e.delegation.country_code: e.score for e in rank_committee(data)}
    assert by_country["MX"] == D(30) * 100 / 50  # (30·100 + 20·0) / 50
    assert by_country["US"] == (D(30) * 50 + D(20) * 100) / 50


def test_role_not_in_event_type_is_ignored() -> None:
    data = replace(_data(), event_type="judges_only")
    mx, _ = data.delegations
    data = replace(data, staff_role_scores={"staff": {mx.id: D(100)}})
    assert set(role_inputs(data)) == {"judge"}
