"""Tipos de entrada y salida del motor. Los identificadores son cadenas opacas."""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

PRESENTATION = Decimal("0.01")
# Precisión con la que se comparan notas para detectar empates: evita que dos
# notas iguales por construcción difieran en el dígito 28 de una división.
COMPARISON = Decimal("0.0000000001")


def present(value: Decimal | None) -> Decimal | None:
    """Redondeo de presentación (2 decimales, mitad hacia arriba)."""
    return None if value is None else value.quantize(PRESENTATION, rounding=ROUND_HALF_UP)


def comparable(value: Decimal) -> Decimal:
    return value.quantize(COMPARISON, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class Criterion:
    id: str
    weight: Decimal
    position: int


@dataclass(frozen=True, slots=True)
class Rubric:
    scale_min: int
    scale_max: int
    criteria: tuple[Criterion, ...]

    def __post_init__(self) -> None:
        if self.scale_min >= self.scale_max:
            raise ValueError("scale_min debe ser menor que scale_max")
        if self.scale_max <= 0:
            raise ValueError("scale_max debe ser positivo")
        if not self.criteria:
            raise ValueError("La rúbrica necesita al menos un criterio")

    @property
    def criterion_ids(self) -> frozenset[str]:
        return frozenset(c.id for c in self.criteria)

    def tiebreak_criterion(self) -> Criterion:
        """Criterio de mayor peso; entre iguales, el de menor `position`."""
        return min(self.criteria, key=lambda c: (-c.weight, c.position, c.id))


@dataclass(frozen=True, slots=True)
class ScoreEntry:
    judge_id: str
    delegate_id: str
    session_id: str
    criterion_id: str
    value: int


@dataclass(frozen=True, slots=True)
class Delegation:
    id: str
    delegate_ids: tuple[str, ...]


class FlagKind(StrEnum):
    INCOMPLETE = "incomplete"
    """El juez no calificó todos los criterios del delegado en esa sesión."""
    SESSION_WITHOUT_SCORES = "session_without_scores"
    """El delegado no tiene ninguna nota completa en esa sesión (no cuenta)."""
    DELEGATE_WITHOUT_SCORES = "delegate_without_scores"
    """El delegado no tiene nota final (no cuenta para la media de la delegación)."""


@dataclass(frozen=True, slots=True)
class Flag:
    kind: FlagKind
    delegate_id: str
    session_id: str | None = None
    judge_id: str | None = None


@dataclass(frozen=True, slots=True)
class DelegateResult:
    delegate_id: str
    final_score: Decimal | None
    session_scores: dict[str, Decimal | None]
    flags: tuple[Flag, ...] = ()


@dataclass(frozen=True, slots=True)
class RankingRow:
    position: int
    tied: bool
    delegation_id: str
    score: Decimal | None
    delegates: tuple[DelegateResult, ...]
    criteria_averages: dict[str, Decimal | None] = field(default_factory=dict)
    flags: tuple[Flag, ...] = ()
