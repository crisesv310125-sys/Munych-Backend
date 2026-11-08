"""Catálogo de tipos de evento: coherencia entre el Literal, la configuración y el SQL."""

import re
from decimal import Decimal
from pathlib import Path
from typing import get_args

import pytest

from munych_api.shared.kernel.catalog import (
    DEFAULT_EVENT_TYPE,
    EVENT_TYPES,
    VOTER_ROLE_LABELS,
    EventType,
    JudgeRole,
    VoterRole,
)

MIGRATIONS = Path(__file__).resolve().parents[4] / "supabase" / "migrations"


def _migrations_sql() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(MIGRATIONS.glob("*.sql")))


def _last_check(column: str, constraint: str = "") -> set[str]:
    """Valores del último CHECK `<column> in (...)` de las migraciones.

    Con `constraint`, solo el CHECK con ese nombre (p. ej. `role` también existe en
    `staff_members`, con otros valores).
    """
    prefix = rf"{constraint}\s+check \(" if constraint else ""
    matches = re.findall(rf"{prefix}{column} in \(([^)]*)\)", _migrations_sql())
    assert matches, f"falta el CHECK de {column}"
    return set(re.findall(r"'([a-z_]+)'", matches[-1]))


def test_every_event_type_has_config() -> None:
    assert set(EVENT_TYPES) == set(get_args(EventType))
    assert DEFAULT_EVENT_TYPE in EVENT_TYPES


def test_judges_only_keeps_current_flow() -> None:
    assert EVENT_TYPES["judges_only"].voter_roles == ("judge",)
    # La mesa califica junto con los jueces, como antes de los tipos de evento.
    for role in ("chair", "moderator", "judge", None):
        assert EVENT_TYPES["judges_only"].account_voter_role(role) == "judge"
    assert EVENT_TYPES["judges_only"].account_voter_role("staff") == "judge"


def test_weights_from_hector() -> None:
    assert EVENT_TYPES["mun_regular"].voter_weights == {
        "chair": Decimal(30),
        "delegate": Decimal(50),
        "staff": Decimal(20),
    }
    assert EVENT_TYPES["national_championship"].voter_weights == {
        "judge": Decimal(50),
        "chair": Decimal(15),
        "delegate": Decimal(25),
        "staff": Decimal(10),
    }


@pytest.mark.parametrize(
    ("event_type", "committee_role", "expected"),
    [
        ("mun_regular", "chair", "chair"),
        ("mun_regular", "moderator", "chair"),
        ("mun_regular", "staff", "staff"),
        ("mun_regular", "judge", None),  # en un MUN regular no hay jueces
        ("national_championship", "judge", "judge"),
        ("national_championship", "chair", "chair"),
        ("national_championship", "staff", "staff"),
    ],
)
def test_account_voter_role(event_type: EventType, committee_role: str, expected: str) -> None:
    assert EVENT_TYPES[event_type].account_voter_role(committee_role) == expected


def test_voter_roles_and_weights_are_valid() -> None:
    roles = set(get_args(VoterRole))
    assert set(VOTER_ROLE_LABELS) == roles
    for config in EVENT_TYPES.values():
        assert config.voter_weights, "cada tipo necesita al menos un rol que vote"
        assert set(config.voter_roles) <= roles
        assert all(weight > 0 for weight in config.voter_weights.values())
        assert sum(config.voter_weights.values()) == 100


def test_sql_checks_match_catalog() -> None:
    assert _last_check("event_type") == set(EVENT_TYPES)
    assert _last_check("role", "committee_judges_role_check") == set(get_args(JudgeRole))
