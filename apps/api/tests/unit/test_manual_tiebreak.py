"""Desempate manual del admin (2026-11-07): `apply_manual_tiebreak`."""

import uuid
from decimal import Decimal

from munych_api.modules.results.domain.models import DelegationInfo, RankingEntry
from munych_api.modules.results.domain.ranking import apply_manual_tiebreak


def entry(position: int, tied: bool, score: str | None = "80") -> RankingEntry:
    return RankingEntry(
        position=position,
        tied=tied,
        delegation=DelegationInfo(
            uuid.uuid4(), None, f"D{position}-{uuid.uuid4().hex[:4]}", None, ()
        ),
        delegates=(),
        score=None if score is None else Decimal(score),
        criteria_averages={},
    )


def ids(entries: list[RankingEntry]) -> list[uuid.UUID]:
    return [e.delegation.id for e in entries]


def test_without_an_order_nothing_changes() -> None:
    ranking = [entry(1, False, "90"), entry(2, True), entry(2, True)]
    assert apply_manual_tiebreak(ranking, []) == ranking


def test_a_fully_ordered_tie_is_resolved() -> None:
    first, b, c, d, last = (
        entry(1, False, "95"),
        entry(2, True),
        entry(2, True),
        entry(2, True),
        entry(5, False, "70"),
    )
    result = apply_manual_tiebreak(
        [first, b, c, d, last], [d.delegation.id, b.delegation.id, c.delegation.id]
    )
    assert ids(result) == ids([first, d, b, c, last])
    assert [(e.position, e.tied, e.manual_tiebreak) for e in result] == [
        (1, False, False),
        (2, False, True),
        (3, False, True),
        (4, False, True),
        (5, False, False),
    ]


def test_a_partially_ordered_tie_stays_tied() -> None:
    b, c, d = entry(1, True), entry(1, True), entry(1, True)
    result = apply_manual_tiebreak([b, c, d], [c.delegation.id, b.delegation.id])
    assert result == [b, c, d]


def test_stale_ids_and_ties_without_score_are_ignored() -> None:
    b, c = entry(1, True, None), entry(1, True, None)
    stale = uuid.uuid4()
    assert apply_manual_tiebreak([b, c], [stale, c.delegation.id, b.delegation.id]) == [b, c]


def test_two_tie_groups_are_resolved_independently() -> None:
    a, b, c, d = entry(1, True, "90"), entry(1, True, "90"), entry(3, True), entry(3, True)
    result = apply_manual_tiebreak(
        [a, b, c, d], [b.delegation.id, a.delegation.id, d.delegation.id, c.delegation.id]
    )
    assert ids(result) == ids([b, a, d, c])
    assert [e.position for e in result] == [1, 2, 3, 4]
