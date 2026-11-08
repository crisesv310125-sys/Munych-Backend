"""Notas de los tipos de staff (handoff «Gestión de staff», 2026-11-08).

- Cada evaluador califica cada criterio en la escala del tipo (p. ej. 0-10, paso 0.5).
- Nota de una evaluación = Σ (valor normalizado a 0-100 × peso / 100). Solo cuenta si
  la evaluación tiene valor en **todos** los criterios actuales de la rúbrica.
- Nota del candidato = promedio de sus evaluaciones completas.
- Solo entran al ranking sugerido los candidatos con evaluaciones ≥ mínimo del tipo.
- Desempate: el criterio elegido (promedio normalizado); si persiste, empate (decide el admin).
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from munych_api.scoring_engine.session_score import mean

TOTAL_WEIGHT = Decimal(100)
MAX_CRITERION_WEIGHT = Decimal(50)


@dataclass(frozen=True, slots=True)
class StaffCriterion:
    id: str
    weight: Decimal


@dataclass(frozen=True, slots=True)
class StaffRubric:
    scale_min: Decimal
    scale_max: Decimal
    criteria: tuple[StaffCriterion, ...]

    @property
    def weight_sum(self) -> Decimal:
        return sum((c.weight for c in self.criteria), Decimal(0))

    @property
    def valid(self) -> bool:
        """Al menos un criterio, pesos de 0 a 50 % y suma exacta de 100 %."""
        return (
            bool(self.criteria)
            and self.scale_max > self.scale_min
            and all(Decimal(0) <= c.weight <= MAX_CRITERION_WEIGHT for c in self.criteria)
            and self.weight_sum == TOTAL_WEIGHT
        )

    def normalize(self, value: Decimal) -> Decimal:
        """Valor de la escala del evaluador → 0-100."""
        return (value - self.scale_min) * 100 / (self.scale_max - self.scale_min)


def rubric_from_json(
    scale_min: Decimal, scale_max: Decimal, criteria: Iterable[Mapping[str, object]]
) -> StaffRubric:
    """Rúbrica a partir de lo guardado en `staff_types` (criterios como JSON)."""
    return StaffRubric(
        scale_min=Decimal(scale_min),
        scale_max=Decimal(scale_max),
        criteria=tuple(
            StaffCriterion(str(c["id"]), Decimal(str(c.get("weight", 0)))) for c in criteria
        ),
    )


def values_from_json(raw: Mapping[str, object]) -> dict[str, Decimal]:
    """Valores de una evaluación guardada (`{criterion_id: número}`); ignora los no numéricos."""
    out: dict[str, Decimal] = {}
    for key, value in raw.items():
        if isinstance(value, int | float | str) and not isinstance(value, bool):
            try:
                out[key] = Decimal(str(value))
            except ArithmeticError:
                continue
    return out


@dataclass(frozen=True, slots=True)
class StaffEvaluation:
    evaluator_id: str
    candidate_id: str
    values: Mapping[str, Decimal]


def evaluation_score(rubric: StaffRubric, values: Mapping[str, Decimal]) -> Decimal | None:
    """Nota 0-100 de una evaluación; `None` si le falta algún criterio."""
    if not rubric.criteria or any(c.id not in values for c in rubric.criteria):
        return None
    return sum(
        (rubric.normalize(values[c.id]) * c.weight / TOTAL_WEIGHT for c in rubric.criteria),
        Decimal(0),
    )


@dataclass(frozen=True, slots=True)
class CandidateResult:
    candidate_id: str
    score: Decimal | None
    evaluations: int
    """Evaluaciones completas."""
    criteria_averages: dict[str, Decimal | None] = field(default_factory=dict)
    """Promedio normalizado (0-100) por criterio, para desempatar."""
    eligible: bool = False
    """Tiene evaluaciones ≥ mínimo: entra al ranking sugerido."""
    position: int | None = None
    tied: bool = False


def candidate_results(
    rubric: StaffRubric,
    evaluations: Iterable[StaffEvaluation],
    candidate_ids: Sequence[str],
    min_evaluators: int,
    tiebreak_criterion_id: str | None = None,
) -> list[CandidateResult]:
    """Ranking de candidatos de un tipo de staff.

    Primero los elegibles, por nota descendente (desempate por el criterio indicado) y
    con posición; después los que no llegan al mínimo, por nota, sin posición.
    """
    wanted = set(candidate_ids)
    scores: dict[str, list[Decimal]] = defaultdict(list)
    by_criterion: dict[str, dict[str, list[Decimal]]] = defaultdict(lambda: defaultdict(list))
    for ev in evaluations:
        if ev.candidate_id not in wanted:
            continue
        score = evaluation_score(rubric, ev.values)
        if score is None:
            continue
        scores[ev.candidate_id].append(score)
        for c in rubric.criteria:
            by_criterion[ev.candidate_id][c.id].append(rubric.normalize(ev.values[c.id]))

    results = [
        CandidateResult(
            candidate_id=cid,
            score=mean(scores[cid]) if scores[cid] else None,
            evaluations=len(scores[cid]),
            criteria_averages={
                c.id: mean(by_criterion[cid][c.id]) if by_criterion[cid][c.id] else None
                for c in rubric.criteria
            },
            eligible=len(scores[cid]) >= min_evaluators,
        )
        for cid in dict.fromkeys(candidate_ids)
    ]

    def key(r: CandidateResult) -> tuple[int, Decimal, Decimal]:
        tb = r.criteria_averages.get(tiebreak_criterion_id or "") if tiebreak_criterion_id else None
        return (
            0 if r.score is not None else 1,
            -(r.score if r.score is not None else Decimal(0)),
            -(tb if tb is not None else Decimal(0)),
        )

    eligible = sorted((r for r in results if r.eligible), key=lambda r: (key(r), r.candidate_id))
    rest = sorted((r for r in results if not r.eligible), key=lambda r: (key(r), r.candidate_id))

    ranked: list[CandidateResult] = []
    for i, r in enumerate(eligible):
        prev = eligible[i - 1] if i else None
        nxt = eligible[i + 1] if i + 1 < len(eligible) else None
        tied = (prev is not None and key(prev) == key(r)) or (
            nxt is not None and key(nxt) == key(r)
        )
        position = ranked[-1].position if prev is not None and key(prev) == key(r) else i + 1
        ranked.append(
            CandidateResult(
                r.candidate_id,
                r.score,
                r.evaluations,
                r.criteria_averages,
                True,
                position,
                tied,
            )
        )
    return ranked + rest


def group_scores(
    candidate_scores: Mapping[str, Decimal | None], groups: Mapping[str, Sequence[str]]
) -> dict[str, Decimal | None]:
    """Nota por grupo (p. ej. delegación) = promedio de sus candidatos con nota (delegados)."""
    out: dict[str, Decimal | None] = {}
    for group_id, members in groups.items():
        values = [v for m in members if (v := candidate_scores.get(m)) is not None]
        out[group_id] = mean(values) if values else None
    return out


def average_types(per_type: Iterable[Mapping[str, Decimal | None]]) -> dict[str, Decimal | None]:
    """Varios tipos de staff que cuentan para el mismo peso se promedian entre sí.

    Por delegación, solo entre los tipos que le dieron nota.
    """
    values: dict[str, list[Decimal]] = defaultdict(list)
    keys: dict[str, None] = {}
    for scores in per_type:
        for key, value in scores.items():
            keys[key] = None
            if value is not None:
                values[key].append(value)
    return {k: (mean(values[k]) if values[k] else None) for k in keys}
