"""Validaciones de rúbrica sin acceso a datos."""

from munych_api.modules.rubrics.schemas import RubricIn
from munych_api.scoring_engine.weights import InvalidWeightsError, validate_weights
from munych_api.shared.kernel import DomainError, ErrorCode


def validate_rubric(rubric: RubricIn) -> None:
    if rubric.scale_min >= rubric.scale_max:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR, "El mínimo de la escala debe ser menor que el máximo"
        )

    try:
        validate_weights(c.weight for c in rubric.criteria)
    except InvalidWeightsError as exc:
        raise DomainError(
            ErrorCode.WEIGHTS_MUST_SUM_100,
            f"Los pesos de los criterios suman {exc.total.normalize():f}; deben sumar 100",
        ) from exc

    ids = [c.id for c in rubric.criteria if c.id is not None]
    if len(ids) != len(set(ids)):
        raise DomainError(ErrorCode.VALIDATION_ERROR, "Hay criterios repetidos en la rúbrica")

    levels = range(rubric.scale_min, rubric.scale_max + 1)
    for criterion in rubric.criteria:
        for level in criterion.level_descriptors:
            if not level.lstrip("-").isdigit() or int(level) not in levels:
                raise DomainError(
                    ErrorCode.VALIDATION_ERROR,
                    f"El descriptor «{level}» del criterio «{criterion.name}» está fuera de la "
                    f"escala {rubric.scale_min}–{rubric.scale_max}",
                )
