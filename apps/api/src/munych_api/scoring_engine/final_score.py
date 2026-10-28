"""Notas de sesión y nota final por delegado (sección 6.3, pasos 2 y 3)."""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from decimal import Decimal

from munych_api.scoring_engine.models import (
    DelegateResult,
    Flag,
    FlagKind,
    Rubric,
    ScoreEntry,
)
from munych_api.scoring_engine.session_score import mean, weighted_score

# (delegate_id, session_id, judge_id) → {criterion_id: value}
Ternas = dict[tuple[str, str, str], dict[str, int]]


def group_ternas(scores: Iterable[ScoreEntry], rubric: Rubric) -> Ternas:
    """Agrupa las notas por terna; ignora criterios que no son de la rúbrica."""
    criterion_ids = rubric.criterion_ids
    ternas: Ternas = defaultdict(dict)
    for s in scores:
        if s.criterion_id in criterion_ids:
            ternas[(s.delegate_id, s.session_id, s.judge_id)][s.criterion_id] = s.value
    return ternas


def complete_ternas(ternas: Ternas, rubric: Rubric) -> Ternas:
    criterion_ids = rubric.criterion_ids
    return {k: v for k, v in ternas.items() if criterion_ids <= v.keys()}


def delegate_results(
    rubric: Rubric,
    scores: Iterable[ScoreEntry],
    session_ids: Sequence[str],
    delegate_ids: Sequence[str],
) -> dict[str, DelegateResult]:
    """Nota de cada sesión (media de jueces completos) y nota final (media de sesiones)."""
    # TODO(cliente): confirmar si se califica por sesión o una sola vez (MVP: por sesión).
    # TODO(cliente): confirmar ausencias (MVP: la sesión sin notas no cuenta y se marca).
    ternas = group_ternas(scores, rubric)
    by_delegate_session: dict[tuple[str, str], list[tuple[str, dict[str, int]]]] = defaultdict(list)
    for (delegate_id, session_id, judge_id), values in ternas.items():
        by_delegate_session[(delegate_id, session_id)].append((judge_id, values))

    results: dict[str, DelegateResult] = {}
    for delegate_id in delegate_ids:
        flags: list[Flag] = []
        session_scores: dict[str, Decimal | None] = {}
        for session_id in session_ids:
            judge_scores: list[Decimal] = []
            for judge_id, values in sorted(by_delegate_session[(delegate_id, session_id)]):
                score = weighted_score(values, rubric)
                if score is None:
                    flags.append(Flag(FlagKind.INCOMPLETE, delegate_id, session_id, judge_id))
                else:
                    judge_scores.append(score)
            session_scores[session_id] = mean(judge_scores)
            if session_scores[session_id] is None:
                flags.append(Flag(FlagKind.SESSION_WITHOUT_SCORES, delegate_id, session_id))

        final = mean([s for s in session_scores.values() if s is not None])
        if final is None:
            flags.append(Flag(FlagKind.DELEGATE_WITHOUT_SCORES, delegate_id))
        results[delegate_id] = DelegateResult(delegate_id, final, session_scores, tuple(flags))
    return results
