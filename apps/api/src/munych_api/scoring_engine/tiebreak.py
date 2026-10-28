"""Clave de orden y desempate del ranking (sección 6.3, paso 5)."""

from decimal import Decimal

from munych_api.scoring_engine.models import comparable

# Una delegación sin nota (o sin media en el criterio) va detrás de cualquier otra.
_MISSING = (1, Decimal(0))


def _descending(value: Decimal | None) -> tuple[int, Decimal]:
    return _MISSING if value is None else (0, -comparable(value))


def rank_key(
    score: Decimal | None, tiebreak_average: Decimal | None
) -> tuple[tuple[int, Decimal], tuple[int, Decimal]]:
    """Orden: nota descendente y, a igual nota, mayor media en el criterio de desempate.

    Dos delegaciones con la misma clave empatan (misma posición y `tied`).
    """
    return (_descending(score), _descending(tiebreak_average))
