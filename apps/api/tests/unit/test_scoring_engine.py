"""Casos límite del motor que no cubren los fixtures."""

from decimal import Decimal

import pytest

from munych_api.scoring_engine import (
    Criterion,
    Delegation,
    InvalidWeightsError,
    Rubric,
    ScoreEntry,
    present,
    rank_delegations,
    validate_weights,
    weighted_score,
)

RUBRIC = Rubric(1, 4, (Criterion("a", Decimal(50), 2), Criterion("b", Decimal(50), 1)))


def test_rubric_invariants() -> None:
    with pytest.raises(ValueError, match="scale_min"):
        Rubric(4, 4, RUBRIC.criteria)
    with pytest.raises(ValueError, match="positivo"):
        Rubric(-2, 0, RUBRIC.criteria)
    with pytest.raises(ValueError, match="criterio"):
        Rubric(1, 4, ())


def test_tiebreak_criterion_prefers_lower_position_among_equal_weights() -> None:
    assert RUBRIC.tiebreak_criterion().id == "b"


def test_weighted_score_rejects_values_out_of_scale() -> None:
    with pytest.raises(ValueError, match="fuera de la escala"):
        weighted_score({"a": 5, "b": 1}, RUBRIC)


def test_weighted_score_is_none_when_incomplete() -> None:
    assert weighted_score({"a": 4}, RUBRIC) is None


def test_scores_of_unknown_criteria_are_ignored() -> None:
    scores = [
        ScoreEntry("j", "d", "s", "a", 4),
        ScoreEntry("j", "d", "s", "b", 4),
        ScoreEntry("j", "d", "s", "otro", 1),
    ]
    (row,) = rank_delegations(RUBRIC, [Delegation("X", ("d",))], scores, ["s"])
    assert row.score == Decimal(100)
    assert set(row.criteria_averages) == {"a", "b"}


def test_several_unscored_delegations_tie_at_the_end() -> None:
    ranking = rank_delegations(
        RUBRIC,
        [Delegation("Z", ("z",)), Delegation("Y", ("y",)), Delegation("X", ("x",))],
        [ScoreEntry("j", "x", "s", "a", 1), ScoreEntry("j", "x", "s", "b", 1)],
        ["s"],
    )
    assert [(r.delegation_id, r.position, r.tied) for r in ranking] == [
        ("X", 1, False),
        ("Y", 2, True),
        ("Z", 2, True),
    ]


def test_present_rounds_half_up() -> None:
    assert present(Decimal("63.125")) == Decimal("63.13")
    assert present(None) is None


@pytest.mark.parametrize("weights", [[], [Decimal(0), Decimal(100)], [Decimal(50)]])
def test_validate_weights(weights: list[Decimal]) -> None:
    with pytest.raises(InvalidWeightsError):
        validate_weights(weights)
