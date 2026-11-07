"""Ranking del comité: adapta el motor puro a las entidades del dominio."""

from uuid import UUID

from munych_api.modules.results.domain.models import (
    CommitteeData,
    DelegateScore,
    IncompleteFlag,
    RankingEntry,
)
from munych_api.scoring_engine import (
    AwardVote,
    Criterion,
    Delegation,
    RoleScores,
    Rubric,
    ScoreEntry,
    peer_award_scores,
    rank_delegations_by_role,
)
from munych_api.shared.kernel.catalog import EVENT_TYPES, VoterRole


def role_inputs(data: CommitteeData) -> dict[str, RoleScores]:
    """Agrupa las calificaciones por rol que vota, con el peso del tipo de evento.

    Las cuentas cuyo rol no vota en este tipo de evento (por ejemplo, un juez en
    un MUN regular) no cuentan.
    """
    config = EVENT_TYPES[data.event_type]
    by_role: dict[VoterRole, list[ScoreEntry]] = {role: [] for role in config.voter_roles}
    for s in data.scores:
        role = config.account_voter_role(s.committee_role)
        if role is not None and role != "delegate":
            by_role[role].append(
                ScoreEntry(
                    str(s.judge_id),
                    str(s.delegate_id),
                    str(s.session_id),
                    str(s.criterion_id),
                    s.value,
                )
            )
    roles: dict[str, RoleScores] = {}
    for role, entries in by_role.items():
        if role == "delegate":
            # Los delegados votan por premios (3/2/1 puntos), no con la rúbrica.
            roles[role] = RoleScores(
                weight=config.voter_weights[role],
                scores=(),
                delegation_scores=peer_award_scores(
                    (
                        AwardVote(str(v.voter_delegate_id), str(v.delegation_id), v.award_type)
                        for v in data.peer_votes
                    ),
                    [str(d.id) for d in data.delegations],
                ),
            )
        else:
            roles[role] = RoleScores(weight=config.voter_weights[role], scores=tuple(entries))
    return roles


def rank_committee(data: CommitteeData) -> list[RankingEntry]:
    """Ranking por nota de la delegación (ponderada por rol) con el desempate de la sección 6.3."""
    delegations = {d.id: d for d in data.delegations}
    names = {p.id: p.full_name for d in data.delegations for p in d.delegates}

    if data.rubric is None or not data.rubric.criteria:
        # Sin rúbrica no hay notas: todas las delegaciones empatan sin puntaje.
        ordered = sorted(data.delegations, key=lambda d: str(d.id))
        return [
            RankingEntry(
                position=1,
                tied=len(ordered) > 1,
                delegation=d,
                delegates=tuple(DelegateScore(p.id, p.full_name, None) for p in d.delegates),
                score=None,
                criteria_averages={},
            )
            for d in ordered
        ]

    rubric = Rubric(
        scale_min=data.rubric.scale_min,
        scale_max=data.rubric.scale_max,
        criteria=tuple(Criterion(str(c.id), c.weight, c.position) for c in data.rubric.criteria),
    )
    session_numbers = {str(s.id): s.number for s in data.sessions}
    rows = rank_delegations_by_role(
        rubric,
        [Delegation(str(d.id), tuple(str(p.id) for p in d.delegates)) for d in data.delegations],
        role_inputs(data),
        [str(s.id) for s in sorted(data.sessions, key=lambda s: s.number)],
    )
    return [
        RankingEntry(
            position=row.position,
            tied=row.tied,
            delegation=delegations[UUID(row.delegation_id)],
            delegates=tuple(
                DelegateScore(UUID(r.delegate_id), names[UUID(r.delegate_id)], r.final_score)
                for r in row.delegates
            ),
            score=row.score,
            criteria_averages={UUID(k): v for k, v in row.criteria_averages.items()},
            incomplete_flags=tuple(
                IncompleteFlag(
                    kind=f.kind.value,
                    delegate_id=UUID(f.delegate_id),
                    session_number=session_numbers.get(f.session_id) if f.session_id else None,
                    judge_id=UUID(f.judge_id) if f.judge_id else None,
                )
                for f in row.flags
            ),
            role_scores=dict(row.role_scores),  # type: ignore[arg-type]
        )
        for row in rows
    ]
