"""Validación de los pesos de una rúbrica (deben sumar exactamente 100)."""

from collections.abc import Iterable
from decimal import Decimal

TOTAL_WEIGHT = Decimal(100)


class InvalidWeightsError(ValueError):
    def __init__(self, total: Decimal) -> None:
        super().__init__(f"Los pesos suman {total}; deben sumar {TOTAL_WEIGHT}")
        self.total = total


def total_weight(weights: Iterable[Decimal]) -> Decimal:
    return sum(weights, Decimal(0))


def validate_weights(weights: Iterable[Decimal]) -> None:
    """Lanza `InvalidWeightsError` si algún peso no es positivo o si no suman 100."""
    values = list(weights)
    total = total_weight(values)
    if not values or any(w <= 0 for w in values) or total != TOTAL_WEIGHT:
        raise InvalidWeightsError(total)
