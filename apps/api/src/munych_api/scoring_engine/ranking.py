"""Nota de la delegación y ranking del comité (sección 6.3, pasos 4 y 5)."""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from decimal import Decimal
from itertools import groupby

from munych_api.scoring_engine.final_score import complete_ternas, delegate_results, group_ternas
from munych_api.scoring_engine.models import (
    DelegateResult,
    Delegation,
    Flag,
    RankingRow,
    Rubric,
    ScoreEntry,
)
from munych_api.scoring_engine.session_score import mean
from munych_api.scoring_engine.tiebreak import rank_key


def criteria_averages(
    rubric: Rubric, scores: Iterable[ScoreEntry], delegate_ids: Iterable[str]
) -> dict[str, Decimal | None]:
    """Media de cada criterio en las ternas completas de los delegados indicados."""
    wanted = set(delegate_ids)
    values: dict[str, list[Decimal]] = defaultdict(list)
    for (delegate_id, _, _), terna in complete_ternas(group_ternas(scores, rubric), rubric).items():
        if delegate_id in wanted:
            for criterion_id, value in terna.items():
                values[criterion_id].append(Decimal(value))
    return {c.id: mean(values[c.id]) for c in rubric.criteria}


def rank_delegations(
    rubric: Rubric,
    delegations: Sequence[Delegation],
    scores: Iterable[ScoreEntry],
    session_ids: Sequence[str],
) -> list[RankingRow]:
    """Ranking descendente por nota de la delegación (media de sus delegados).

    Desempate: mayor media en el criterio de mayor peso. Si persiste, misma
    posición y `tied=True` para que decida el administrador. El resultado no
    depende del orden de la entrada.
    """
    score_list = list(scores)
    all_delegates = [d for delegation in delegations for d in delegation.delegate_ids]
    results = delegate_results(rubric, score_list, session_ids, all_delegates)
    tiebreak_id = rubric.tiebreak_criterion().id

    rows: list[tuple[Delegation, Decimal | None, dict[str, Decimal | None]]] = []
    # TODO(cliente): confirmar delegación doble (MVP: se califica a cada delegado y la
    # delegación recibe la media de sus notas finales).
    for delegation in delegations:
        finals = [results[d].final_score for d in delegation.delegate_ids]
        score = mean([f for f in finals if f is not None])
        rows.append(
            (delegation, score, criteria_averages(rubric, score_list, delegation.delegate_ids))
        )

    def key(row: tuple[Delegation, Decimal | None, dict[str, Decimal | None]]) -> object:
        return rank_key(row[1], row[2][tiebreak_id])

    rows.sort(key=lambda r: (key(r), r[0].id))
    ranking: list[RankingRow] = []
    for _, group_iter in groupby(rows, key=key):
        group = list(group_iter)
        position = len(ranking) + 1
        for delegation, score, averages in group:
            delegates: tuple[DelegateResult, ...] = tuple(
                results[d] for d in delegation.delegate_ids
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
                )
            )
    return ranking
