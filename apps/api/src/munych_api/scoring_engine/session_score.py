"""Nota ponderada de un delegado, por un juez, en una sesión (sección 6.3, paso 1)."""

from collections.abc import Mapping
from decimal import Decimal

from munych_api.scoring_engine.models import Rubric


def weighted_score(values: Mapping[str, int], rubric: Rubric) -> Decimal | None:
    """`Σ (value_i / scale_max) × weight_i` en [0, 100].

    Devuelve `None` si falta algún criterio de la rúbrica (terna incompleta).
    """
    if not rubric.criterion_ids <= values.keys():
        return None
    total = Decimal(0)
    for criterion in rubric.criteria:
        value = values[criterion.id]
        if not rubric.scale_min <= value <= rubric.scale_max:
            raise ValueError(
                f"Valor {value} fuera de la escala {rubric.scale_min}–{rubric.scale_max}"
            )
        total += Decimal(value) * criterion.weight
    # Se divide una sola vez para no acumular errores de redondeo.
    return total / Decimal(rubric.scale_max)


def mean(values: list[Decimal]) -> Decimal | None:
    return sum(values, Decimal(0)) / len(values) if values else None
