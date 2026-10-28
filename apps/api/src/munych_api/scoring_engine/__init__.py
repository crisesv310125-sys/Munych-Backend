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
from munych_api.scoring_engine.ranking import criteria_averages, rank_delegations
from munych_api.scoring_engine.session_score import weighted_score
from munych_api.scoring_engine.weights import InvalidWeightsError, validate_weights

__all__ = [
    "Criterion",
    "DelegateResult",
    "Delegation",
    "Flag",
    "FlagKind",
    "InvalidWeightsError",
    "RankingRow",
    "Rubric",
    "ScoreEntry",
    "criteria_averages",
    "delegate_results",
    "present",
    "rank_delegations",
    "validate_weights",
    "weighted_score",
]
