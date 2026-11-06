"""Ranking con varios grupos que votan, ponderados por rol (spec del 2026-11-05).

Por cada delegación:

1. Se calcula la nota de cada rol con el mismo método de siempre: nota ponderada
   de la rúbrica en [0, 100] por evaluador y sesión → media de evaluadores →
   media de sesiones. Las rúbricas con escalas distintas quedan así en la misma
   escala común (0-100).
2. Nota final = Σ peso_rol × nota_rol / Σ peso de los roles **con nota**.
   Un rol sin votos no cuenta como 0: su peso se reparte entre los demás.

Hay dos clases de rol:

- **por delegado** (jueces, mesa, staff): califican a cada delegado; la nota de la
  delegación es la media de sus delegados, como en `rank_delegations`.
- **por delegación** (delegados): votan por la delegación entera. En sus
  `ScoreEntry`, `delegate_id` es el id de la delegación votada y `judge_id` el
  del delegado que vota.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import groupby

from munych_api.scoring_engine.final_score import delegate_results
from munych_api.scoring_engine.models import (
    DelegateResult,
    Delegation,
    Flag,
    RankingRow,
    Rubric,
    ScoreEntry,
)
from munych_api.scoring_engine.ranking import criteria_averages
from munych_api.scoring_engine.session_score import mean
from munych_api.scoring_engine.tiebreak import rank_key


@dataclass(frozen=True, slots=True)
class RoleScores:
    """Calificaciones de un grupo que vota y su peso en el resultado."""

    weight: Decimal
    scores: tuple[ScoreEntry, ...]
    per_delegation: bool = False
    """True si el grupo vota por delegación (delegados) y no por delegado."""

    def __post_init__(self) -> None:
        if self.weight <= 0:
            raise ValueError("El peso de un rol debe ser positivo")


def weighted_combination(
    values: Mapping[str, Decimal | None], weights: Mapping[str, Decimal]
) -> Decimal | None:
    """`Σ w·v / Σ w` sobre los roles con valor. `None` si ningún rol tiene valor."""
    present = [(weights[role], value) for role, value in values.items() if value is not None]
    total_weight = sum((w for w, _ in present), Decimal(0))
    if not present or total_weight == 0:
        return None
    if len(present) == 1:
        # Evita redondeos en `w·v / w`: con un solo rol la nota es exactamente la suya.
        return present[0][1]
    # Se divide una sola vez para no acumular errores de redondeo.
    return sum((w * v for w, v in present), Decimal(0)) / total_weight


@dataclass(frozen=True, slots=True)
class _RoleOutcome:
    delegation_scores: dict[str, Decimal | None]
    delegate_results: dict[str, DelegateResult]
    criteria: dict[str, dict[str, Decimal | None]]


def _role_outcome(
    rubric: Rubric,
    delegations: Sequence[Delegation],
    role: RoleScores,
    session_ids: Sequence[str],
) -> _RoleOutcome:
    scores = list(role.scores)
    if role.per_delegation:
        ids = [d.id for d in delegations]
        results = delegate_results(rubric, scores, session_ids, ids)
        return _RoleOutcome(
            delegation_scores={d.id: results[d.id].final_score for d in delegations},
            delegate_results={},
            criteria={d.id: criteria_averages(rubric, scores, [d.id]) for d in delegations},
        )

    all_delegates = [p for d in delegations for p in d.delegate_ids]
    results = delegate_results(rubric, scores, session_ids, all_delegates)
    delegation_scores: dict[str, Decimal | None] = {}
    for delegation in delegations:
        finals = [results[p].final_score for p in delegation.delegate_ids]
        delegation_scores[delegation.id] = mean([f for f in finals if f is not None])
    return _RoleOutcome(
        delegation_scores=delegation_scores,
        delegate_results=results,
        criteria={d.id: criteria_averages(rubric, scores, d.delegate_ids) for d in delegations},
    )


def _combined_delegate(
    delegate_id: str, outcomes: Mapping[str, _RoleOutcome], weights: Mapping[str, Decimal]
) -> DelegateResult:
    """Nota de un delegado con los roles que califican por delegado."""
    per_role = {
        role: outcome.delegate_results[delegate_id]
        for role, outcome in outcomes.items()
        if delegate_id in outcome.delegate_results
    }
    if not per_role:
        return DelegateResult(delegate_id, None, {})
    if len(per_role) == 1:
        # Un solo rol: el resultado es exactamente el de siempre.
        return next(iter(per_role.values()))
    sessions: dict[str, Decimal | None] = {}
    for session_id in {s for r in per_role.values() for s in r.session_scores}:
        sessions[session_id] = weighted_combination(
            {role: r.session_scores.get(session_id) for role, r in per_role.items()}, weights
        )
    return DelegateResult(
        delegate_id=delegate_id,
        final_score=weighted_combination(
            {role: r.final_score for role, r in per_role.items()}, weights
        ),
        session_scores=sessions,
        flags=tuple(f for r in per_role.values() for f in r.flags),
    )


def rank_delegations_by_role(
    rubric: Rubric,
    delegations: Sequence[Delegation],
    roles: Mapping[str, RoleScores],
    session_ids: Sequence[str],
) -> list[RankingRow]:
    """Ranking descendente por la nota ponderada por rol.

    Desempate igual que `rank_delegations`: mayor media (también ponderada por
    rol) en el criterio de mayor peso; si persiste, misma posición y `tied=True`.
    Con un solo rol el resultado coincide con `rank_delegations`.
    """
    if not roles:
        raise ValueError("Se necesita al menos un rol que vote")
    weights = {role: r.weight for role, r in roles.items()}
    outcomes = {
        role: _role_outcome(rubric, delegations, r, session_ids) for role, r in roles.items()
    }
    tiebreak_id = rubric.tiebreak_criterion().id
    account_outcomes = {role: outcomes[role] for role, r in roles.items() if not r.per_delegation}

    rows: list[
        tuple[Delegation, Decimal | None, dict[str, Decimal | None], dict[str, Decimal | None]]
    ] = []
    for delegation in delegations:
        role_scores = {role: o.delegation_scores[delegation.id] for role, o in outcomes.items()}
        averages = {
            c.id: weighted_combination(
                {role: o.criteria[delegation.id][c.id] for role, o in outcomes.items()}, weights
            )
            for c in rubric.criteria
        }
        rows.append((delegation, weighted_combination(role_scores, weights), averages, role_scores))

    def key(row: tuple[Delegation, Decimal | None, dict[str, Decimal | None], object]) -> object:
        return rank_key(row[1], row[2][tiebreak_id])

    rows.sort(key=lambda r: (key(r), r[0].id))
    ranking: list[RankingRow] = []
    for _, group_iter in groupby(rows, key=key):
        group = list(group_iter)
        position = len(ranking) + 1
        for delegation, score, averages, role_scores in group:
            delegates: tuple[DelegateResult, ...] = tuple(
                _combined_delegate(p, account_outcomes, weights) for p in delegation.delegate_ids
            )
            flags: tuple[Flag, ...] = tuple(f for r in delegates for f in r.flags)
            ranking.append(
                RankingRow(
                    position=position,
                    tied=len(group) > 1,
                    delegation_id=delegation.id,
                    score=score,
                    delegates=delegates,
                    criteria_averages=averages,
                    flags=flags,
                    role_scores=role_scores,
                )
            )
    return ranking
