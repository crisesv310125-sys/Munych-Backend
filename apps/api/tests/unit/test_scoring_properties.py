"""Propiedades del motor con Hypothesis (sección 10)."""

from decimal import Decimal
from itertools import pairwise

from hypothesis import given
from hypothesis import strategies as st

from munych_api.scoring_engine import (
    Criterion,
    Delegation,
    Rubric,
    ScoreEntry,
    delegate_results,
    rank_delegations,
    weighted_score,
)


@st.composite
def rubrics(draw: st.DrawFn) -> Rubric:
    """Rúbricas válidas: pesos enteros positivos que suman 100 y escala arbitraria."""
    count = draw(st.integers(min_value=1, max_value=6))
    cuts = sorted(draw(st.sets(st.integers(1, 99), min_size=count - 1, max_size=count - 1)))
    bounds = [0, *cuts, 100]
    weights = [Decimal(b - a) for a, b in pairwise(bounds)]
    scale_min = draw(st.integers(min_value=0, max_value=5))
    scale_max = draw(st.integers(min_value=scale_min + 1, max_value=scale_min + 10))
    positions = draw(st.permutations(list(range(1, count + 1))))
    return Rubric(
        scale_min=scale_min,
        scale_max=scale_max,
        criteria=tuple(
            Criterion(f"c{i}", w, p)
            for i, (w, p) in enumerate(zip(weights, positions, strict=True))
        ),
    )


@st.composite
def rubric_and_values(draw: st.DrawFn) -> tuple[Rubric, dict[str, int]]:
    rubric = draw(rubrics())
    values = {c.id: draw(st.integers(rubric.scale_min, rubric.scale_max)) for c in rubric.criteria}
    return rubric, values


@st.composite
def committees(draw: st.DrawFn) -> tuple[Rubric, list[Delegation], list[ScoreEntry], list[str]]:
    rubric = draw(rubrics())
    sessions = [f"s{i}" for i in range(draw(st.integers(1, 3)))]
    judges = [f"j{i}" for i in range(draw(st.integers(1, 3)))]
    delegations = [
        Delegation(f"d{i}", tuple(f"d{i}-{k}" for k in range(draw(st.integers(1, 2)))))
        for i in range(draw(st.integers(1, 6)))
    ]
    scores = [
        ScoreEntry(judge, delegate, session, criterion.id, value)
        for delegation in delegations
        for delegate in delegation.delegate_ids
        for session in sessions
        for judge in judges
        for criterion in rubric.criteria
        # Algunas notas faltan: genera ternas incompletas y sesiones vacías.
        if (value := draw(st.one_of(st.none(), st.integers(rubric.scale_min, rubric.scale_max))))
        is not None
    ]
    return rubric, delegations, scores, sessions


@given(rubric_and_values())
def test_weighted_score_is_between_0_and_100(case: tuple[Rubric, dict[str, int]]) -> None:
    rubric, values = case
    score = weighted_score(values, rubric)
    assert score is not None
    assert Decimal(0) <= score <= Decimal(100)


@given(rubric_and_values(), st.data())
def test_raising_a_value_never_lowers_the_score(
    case: tuple[Rubric, dict[str, int]], data: st.DataObject
) -> None:
    rubric, values = case
    criterion = data.draw(st.sampled_from(rubric.criteria))
    raised = {**values, criterion.id: min(values[criterion.id] + 1, rubric.scale_max)}
    before, after = weighted_score(values, rubric), weighted_score(raised, rubric)
    assert before is not None
    assert after is not None
    assert after >= before


@given(committees(), st.data())
def test_raising_a_value_never_lowers_the_final_score(
    case: tuple[Rubric, list[Delegation], list[ScoreEntry], list[str]], data: st.DataObject
) -> None:
    rubric, delegations, scores, sessions = case
    if not scores:
        return
    index = data.draw(st.integers(0, len(scores) - 1))
    target = scores[index]
    raised = list(scores)
    raised[index] = ScoreEntry(
        target.judge_id,
        target.delegate_id,
        target.session_id,
        target.criterion_id,
        min(target.value + 1, rubric.scale_max),
    )
    delegate_ids = [d for delegation in delegations for d in delegation.delegate_ids]
    before = delegate_results(rubric, scores, sessions, delegate_ids)[target.delegate_id]
    after = delegate_results(rubric, raised, sessions, delegate_ids)[target.delegate_id]
    if before.final_score is not None:
        assert after.final_score is not None
        assert after.final_score >= before.final_score


@given(committees())
def test_final_scores_are_between_0_and_100(
    case: tuple[Rubric, list[Delegation], list[ScoreEntry], list[str]],
) -> None:
    rubric, delegations, scores, sessions = case
    for row in rank_delegations(rubric, delegations, scores, sessions):
        if row.score is not None:
            assert Decimal(0) <= row.score <= Decimal(100)


@given(committees(), st.randoms(use_true_random=False))
def test_ranking_does_not_depend_on_input_order(
    case: tuple[Rubric, list[Delegation], list[ScoreEntry], list[str]], rng: object
) -> None:
    import random

    assert isinstance(rng, random.Random)
    rubric, delegations, scores, sessions = case
    shuffled_delegations = list(delegations)
    shuffled_scores = list(scores)
    rng.shuffle(shuffled_delegations)
    rng.shuffle(shuffled_scores)

    expected = rank_delegations(rubric, delegations, scores, sessions)
    actual = rank_delegations(rubric, shuffled_delegations, shuffled_scores, sessions)
    assert actual == expected
    assert sorted(r.delegation_id for r in actual) == sorted(d.id for d in delegations)


@given(committees())
def test_positions_are_consistent(
    case: tuple[Rubric, list[Delegation], list[ScoreEntry], list[str]],
) -> None:
    rubric, delegations, scores, sessions = case
    ranking = rank_delegations(rubric, delegations, scores, sessions)
    positions = [r.position for r in ranking]
    assert positions == sorted(positions)
    assert positions[0] == 1
    for index, row in enumerate(ranking):
        # Posición de competición: 1, 2, 2, 4…
        assert row.position == 1 + sum(1 for r in ranking if r.position < row.position)
        assert row.tied == (positions.count(row.position) > 1), index
