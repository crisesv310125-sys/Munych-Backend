"""Notas de los tipos de staff (`scoring_engine.staff`)."""

from decimal import Decimal

from munych_api.scoring_engine.staff import (
    StaffCriterion,
    StaffEvaluation,
    StaffRubric,
    average_types,
    candidate_results,
    evaluation_score,
    group_scores,
    rubric_from_json,
    values_from_json,
)

D = Decimal

PRESS = StaffRubric(
    scale_min=D(0),
    scale_max=D(10),
    criteria=(
        StaffCriterion("calidad", D(30)),
        StaffCriterion("fuentes", D(25)),
        StaffCriterion("redaccion", D(20)),
        StaffCriterion("cobertura", D(15)),
        StaffCriterion("puntualidad", D(10)),
    ),
)


def full(value: str) -> dict[str, Decimal]:
    return {c.id: D(value) for c in PRESS.criteria}


def test_rubric_validity() -> None:
    assert PRESS.valid
    assert PRESS.weight_sum == 100
    crisis = StaffRubric(D(0), D(10), (StaffCriterion("a", D(35)), StaffCriterion("b", D(50))))
    assert not crisis.valid  # suma 85
    assert not StaffRubric(D(0), D(10), ()).valid
    too_heavy = StaffRubric(D(0), D(10), (StaffCriterion("a", D(60)), StaffCriterion("b", D(40))))
    assert not too_heavy.valid  # un criterio pesa más de 50 %


def test_evaluation_score_normalizes_to_100() -> None:
    assert evaluation_score(PRESS, full("10")) == 100
    assert evaluation_score(PRESS, full("0")) == 0
    assert evaluation_score(PRESS, full("7.5")) == D(75)
    values = full("10") | {"calidad": D(5)}  # 30 % del total vale la mitad
    assert evaluation_score(PRESS, values) == D(85)


def test_incomplete_evaluation_has_no_score() -> None:
    values = full("9")
    del values["puntualidad"]
    assert evaluation_score(PRESS, values) is None


def test_non_zero_scale_min() -> None:
    rubric = StaffRubric(D(1), D(5), (StaffCriterion("a", D(50)), StaffCriterion("b", D(50))))
    assert evaluation_score(rubric, {"a": D(5), "b": D(1)}) == 50


def test_ranking_with_minimum_and_tiebreak() -> None:
    evaluations = [
        StaffEvaluation("e1", "sofia", full("9")),
        StaffEvaluation("e2", "sofia", full("9.5")),
        StaffEvaluation("e1", "andres", full("9")),
        StaffEvaluation("e2", "andres", full("9")),
        # Paula empata con Andrés en nota, pero gana en «calidad».
        StaffEvaluation("e1", "paula", full("9") | {"calidad": D(10), "fuentes": D("7.8")}),
        StaffEvaluation("e2", "paula", full("9")),
        StaffEvaluation("e1", "renata", full("10")),  # solo 1 de 2 evaluaciones mínimas
    ]
    rows = candidate_results(
        PRESS, evaluations, ["sofia", "andres", "paula", "renata", "tomas"], 2, "calidad"
    )
    assert [r.candidate_id for r in rows] == ["sofia", "paula", "andres", "renata", "tomas"]
    assert [r.position for r in rows] == [1, 2, 3, None, None]
    assert rows[0].score == D("92.5")
    renata = rows[3]
    assert not renata.eligible
    assert renata.evaluations == 1
    assert renata.score == 100
    tomas = rows[4]
    assert tomas.score is None
    assert tomas.evaluations == 0


def test_exact_tie_shares_position() -> None:
    evaluations = [
        StaffEvaluation("e1", "a", full("8")),
        StaffEvaluation("e1", "b", full("8")),
        StaffEvaluation("e1", "c", full("6")),
    ]
    rows = candidate_results(PRESS, evaluations, ["a", "b", "c"], 1)
    assert [(r.position, r.tied) for r in rows] == [(1, True), (1, True), (3, False)]


def test_ignores_candidates_outside_the_list_and_incomplete_evaluations() -> None:
    partial = full("10")
    del partial["calidad"]
    evaluations = [
        StaffEvaluation("e1", "a", full("5")),
        StaffEvaluation("e2", "a", partial),
        StaffEvaluation("e1", "otro", full("10")),
    ]
    (row,) = candidate_results(PRESS, evaluations, ["a"], 1)
    assert row.evaluations == 1
    assert row.score == 50


def test_group_and_type_averages() -> None:
    grouped = group_scores(
        {"p1": D(80), "p2": D(60), "p3": None}, {"d1": ["p1", "p2"], "d2": ["p3"], "d3": []}
    )
    assert grouped == {"d1": D(70), "d2": None, "d3": None}
    combined = average_types([{"d1": D(70), "d2": None}, {"d1": D(90), "d2": D(50)}])
    assert combined == {"d1": D(80), "d2": D(50)}


def test_json_helpers() -> None:
    rubric = rubric_from_json(
        D(0), D(10), [{"id": "a", "weight": 50}, {"id": "b", "weight": "50.0"}]
    )
    assert rubric.valid
    assert values_from_json({"a": 7.5, "b": "x", "c": True, "d": 3}) == {
        "a": D("7.5"),
        "d": D(3),
    }
