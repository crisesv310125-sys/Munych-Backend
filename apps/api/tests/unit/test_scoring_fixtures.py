"""Ejecuta los casos compartidos de `fixtures/scoring/*.json` contra el motor."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from munych_api.scoring_engine import (
    Criterion,
    Delegation,
    Flag,
    Rubric,
    ScoreEntry,
    delegate_results,
    present,
    rank_delegations,
)

FIXTURES_DIR = Path(__file__).resolve().parents[4] / "fixtures" / "scoring"
FIXTURES = sorted(FIXTURES_DIR.glob("*.json"))


def _text(value: Decimal | None) -> str | None:
    rounded = present(value)
    return None if rounded is None else f"{rounded:.2f}"


def _flag(flag: Flag) -> dict[str, Any]:
    return {
        "kind": flag.kind.value,
        "delegate_id": flag.delegate_id,
        "session_id": flag.session_id,
        "judge_id": flag.judge_id,
    }


def load_case(path: Path) -> tuple[Rubric, list[Delegation], list[ScoreEntry], list[str], Any]:
    case = json.loads(path.read_text(encoding="utf-8"))
    rubric = Rubric(
        scale_min=case["rubric"]["scale_min"],
        scale_max=case["rubric"]["scale_max"],
        criteria=tuple(
            Criterion(c["id"], Decimal(c["weight"]), c["position"])
            for c in case["rubric"]["criteria"]
        ),
    )
    delegations = [Delegation(d["id"], tuple(d["delegate_ids"])) for d in case["delegations"]]
    scores = [ScoreEntry(**s) for s in case["scores"]]
    return rubric, delegations, scores, case["sessions"], case["expected"]


def test_there_are_at_least_8_fixtures() -> None:
    assert len(FIXTURES) >= 8


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_fixture(path: Path) -> None:
    rubric, delegations, scores, sessions, expected = load_case(path)
    delegate_ids = [d for delegation in delegations for d in delegation.delegate_ids]

    results = delegate_results(rubric, scores, sessions, delegate_ids)
    assert {
        delegate_id: {
            "final_score": _text(r.final_score),
            "session_scores": {s: _text(v) for s, v in r.session_scores.items()},
        }
        for delegate_id, r in results.items()
    } == expected["delegates"]

    ranking = rank_delegations(rubric, delegations, scores, sessions)
    assert [
        {
            "delegation_id": row.delegation_id,
            "position": row.position,
            "tied": row.tied,
            "score": _text(row.score),
            "criteria_averages": {k: _text(v) for k, v in row.criteria_averages.items()},
            "incomplete_flags": [_flag(f) for f in row.flags],
        }
        for row in ranking
    ] == expected["ranking"]
