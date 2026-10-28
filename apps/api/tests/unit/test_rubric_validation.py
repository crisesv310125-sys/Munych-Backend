"""Validación de rúbricas: pesos = 100, escala y descriptores."""

from decimal import Decimal

import pytest

from munych_api.modules.rubrics.schemas import CriterionIn, RubricIn
from munych_api.modules.rubrics.service import default_rubric
from munych_api.modules.rubrics.validation import validate_rubric
from munych_api.shared.kernel import DomainError, ErrorCode


def _rubric(*weights: str, scale: tuple[int, int] = (1, 4)) -> RubricIn:
    return RubricIn(
        name="Prueba",
        scale_min=scale[0],
        scale_max=scale[1],
        criteria=[CriterionIn(name=f"C{i}", weight=Decimal(w)) for i, w in enumerate(weights)],
    )


def test_default_rubric_matches_spec() -> None:
    rubric = default_rubric()
    validate_rubric(rubric)
    assert (rubric.scale_min, rubric.scale_max) == (1, 4)
    assert [c.weight for c in rubric.criteria] == [20, 20, 20, 15, 15, 10]
    assert rubric.criteria[0].level_descriptors["4"] == "Excepcional"


@pytest.mark.parametrize("weights", [("50", "49.99"), ("60", "50"), ("100.01",)])
def test_weights_must_sum_100(weights: tuple[str, ...]) -> None:
    with pytest.raises(DomainError) as exc:
        validate_rubric(_rubric(*weights))
    assert exc.value.code == ErrorCode.WEIGHTS_MUST_SUM_100


def test_decimal_weights_summing_100_are_valid() -> None:
    validate_rubric(_rubric("33.33", "33.33", "33.34"))


def test_scale_min_must_be_lower_than_max() -> None:
    with pytest.raises(DomainError) as exc:
        validate_rubric(_rubric("100", scale=(4, 4)))
    assert exc.value.code == ErrorCode.VALIDATION_ERROR


def test_descriptor_outside_scale_is_rejected() -> None:
    rubric = _rubric("100")
    rubric.criteria[0].level_descriptors = {"5": "Fuera"}
    with pytest.raises(DomainError, match="fuera de la escala"):
        validate_rubric(rubric)
