"""Motor de cálculo PURO (solo biblioteca estándar).

Regla: este paquete no importa nada del resto de la aplicación ni de frameworks.
Lo hace cumplir import-linter (`just lint`). Todos los cálculos usan `Decimal`;
el redondeo a 2 decimales (`present`) se aplica solo al presentar.
"""

from munych_api.scoring_engine.final_score import delegate_results
from munych_api.scoring_engine.models import (
    Criterion,
    DelegateResult,
    Delegation,
    Flag,
    FlagKind,
    RankingRow,
    Rubric,
    ScoreEntry,
    present,
)
from munych_api.scoring_engine.peer_awards import AWARD_POINTS, AwardVote, peer_award_scores
from munych_api.scoring_engine.ranking import criteria_averages, rank_delegations
from munych_api.scoring_engine.roles import (
    RoleScores,
    rank_delegations_by_role,
    weighted_combination,
)
from munych_api.scoring_engine.session_score import weighted_score
from munych_api.scoring_engine.weights import InvalidWeightsError, validate_weights

__all__ = [
    "AWARD_POINTS",
    "AwardVote",
    "Criterion",
    "DelegateResult",
    "Delegation",
    "Flag",
    "FlagKind",
    "InvalidWeightsError",
    "RankingRow",
    "RoleScores",
    "Rubric",
    "ScoreEntry",
    "criteria_averages",
    "delegate_results",
    "peer_award_scores",
    "present",
    "rank_delegations",
    "rank_delegations_by_role",
    "validate_weights",
    "weighted_combination",
    "weighted_score",
]
