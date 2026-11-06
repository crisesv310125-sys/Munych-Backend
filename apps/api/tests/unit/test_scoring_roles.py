"""Motor: ranking ponderado por rol (spec «Tipos de evento y votación», 2026-11-05)."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from munych_api.scoring_engine import (
    Criterion,
    Delegation,
    RoleScores,
    Rubric,
    ScoreEntry,
    rank_delegations,
    rank_delegations_by_role,
    weighted_combination,
)

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "scoring"
CHAMPIONSHIP = {"judge": 50, "chair": 15, "delegate": 25, "staff": 10}
MUN_REGULAR = {"chair": 30, "delegate": 50, "staff": 20}

# Rúbrica de un criterio en escala 0-10: la nota de cada rol es su valor × 10.
RUBRIC_10 = Rubric(0, 10, (Criterion("c", Decimal(100), 1),))
S1, S2 = "s1", "s2"
MX = Delegation("MX", ("ana",))
US = Delegation("US", ("john",))


def _account(role_value: dict[str, int], weights: dict[str, int]) -> dict[str, RoleScores]:
    """Una calificación por rol a «ana» (MX) en la sesión 1; delegados votan por MX."""
    roles: dict[str, RoleScores] = {}
    for role, weight in weights.items():
        value = role_value.get(role)
        if role == "delegate":
            scores = () if value is None else (ScoreEntry("voter", "MX", S1, "c", value),)
            roles[role] = RoleScores(Decimal(weight), scores, per_delegation=True)
        else:
            scores = () if value is None else (ScoreEntry(f"{role}-1", "ana", S1, "c", value),)
            roles[role] = RoleScores(Decimal(weight), scores)
    return roles


def test_spec_example_championship_is_8_05() -> None:
    roles = _account({"judge": 9, "chair": 8, "delegate": 7, "staff": 6}, CHAMPIONSHIP)
    (row,) = rank_delegations_by_role(RUBRIC_10, [MX], roles, [S1])
    # 0.50·9 + 0.15·8 + 0.25·7 + 0.10·6 = 8.05 sobre 10 → 80.5 sobre 100.
    assert row.score == Decimal("80.5")
    assert row.role_scores == {
        "judge": Decimal(90),
        "chair": Decimal(80),
        "delegate": Decimal(70),
        "staff": Decimal(60),
    }


def test_role_without_votes_does_not_count_as_zero() -> None:
    roles = _account({"chair": 8, "staff": 6}, MUN_REGULAR)
    (row,) = rank_delegations_by_role(RUBRIC_10, [MX], roles, [S1])
    # Sin votos de delegados, su 50 % se reparte: (30·80 + 20·60) / 50 = 72.
    assert row.score == Decimal(72)
    assert row.role_scores["delegate"] is None


def test_no_votes_at_all() -> None:
    (row,) = rank_delegations_by_role(RUBRIC_10, [MX], _account({}, MUN_REGULAR), [S1])
    assert row.score is None
    assert all(v is None for v in row.role_scores.values())


def test_peer_votes_average_voters_then_sessions() -> None:
    peers = (
        ScoreEntry("v1", "MX", S1, "c", 10),
        ScoreEntry("v2", "MX", S1, "c", 6),  # sesión 1: media 80
        ScoreEntry("v1", "MX", S2, "c", 4),  # sesión 2: 40
    )
    roles = {"delegate": RoleScores(Decimal(100), peers, per_delegation=True)}
    (row,) = rank_delegations_by_role(RUBRIC_10, [MX], roles, [S1, S2])
    assert row.score == Decimal(60)
    # Los delegados no califican a personas: el delegado de MX queda sin nota propia.
    assert row.delegates[0].final_score is None


def test_ranking_and_tiebreak_use_weighted_scores() -> None:
    rubric = Rubric(
        1, 4, (Criterion("oratoria", Decimal(60), 1), Criterion("datos", Decimal(40), 2))
    )

    def chair(delegate: str, oratoria: int, datos: int) -> tuple[ScoreEntry, ...]:
        return (
            ScoreEntry("mesa", delegate, S1, "oratoria", oratoria),
            ScoreEntry("mesa", delegate, S1, "datos", datos),
        )

    def peer(delegation: str, oratoria: int, datos: int) -> tuple[ScoreEntry, ...]:
        return (
            ScoreEntry("voter", delegation, S1, "oratoria", oratoria),
            ScoreEntry("voter", delegation, S1, "datos", datos),
        )

    roles = {
        "chair": RoleScores(Decimal(50), chair("ana", 4, 2) + chair("john", 2, 4)),
        "delegate": RoleScores(Decimal(50), peer("US", 4, 2) + peer("MX", 2, 4), True),
    }
    rows = rank_delegations_by_role(rubric, [MX, US], roles, [S1])
    # MX: mesa 80, pares 70; US: mesa 70, pares 80 → 75 ambas, y la media ponderada
    # de «oratoria» también empata (3): misma posición para que decida el admin.
    assert {r.score for r in rows} == {Decimal(75)}
    assert [(r.position, r.tied) for r in rows] == [(1, True), (1, True)]


def test_single_role_matches_classic_ranking() -> None:
    """Con un solo rol (judges_only) el resultado es exactamente el de siempre."""
    for path in sorted(FIXTURES.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        rubric = Rubric(
            case["rubric"]["scale_min"],
            case["rubric"]["scale_max"],
            tuple(
                Criterion(c["id"], Decimal(str(c["weight"])), c["position"])
                for c in case["rubric"]["criteria"]
            ),
        )
        delegations = [Delegation(d["id"], tuple(d["delegate_ids"])) for d in case["delegations"]]
        scores = tuple(
            ScoreEntry(
                s["judge_id"], s["delegate_id"], s["session_id"], s["criterion_id"], s["value"]
            )
            for s in case["scores"]
        )
        classic = rank_delegations(rubric, delegations, scores, case["sessions"])
        by_role = rank_delegations_by_role(
            rubric, delegations, {"judge": RoleScores(Decimal(100), scores)}, case["sessions"]
        )
        assert [(r.delegation_id, r.position, r.tied, r.score) for r in by_role] == [
            (r.delegation_id, r.position, r.tied, r.score) for r in classic
        ], path.name
        assert [r.delegates for r in by_role] == [r.delegates for r in classic], path.name
        assert [r.criteria_averages for r in by_role] == [r.criteria_averages for r in classic], (
            path.name
        )


def test_weighted_combination() -> None:
    weights = {"a": Decimal(30), "b": Decimal(70)}
    assert weighted_combination({"a": Decimal(10), "b": Decimal(20)}, weights) == Decimal(17)
    assert weighted_combination({"a": None, "b": Decimal(20)}, weights) == Decimal(20)
    assert weighted_combination({"a": None, "b": None}, weights) is None


def test_role_weight_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positivo"):
        RoleScores(Decimal(0), ())
