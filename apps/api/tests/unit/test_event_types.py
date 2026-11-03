"""Catálogo de tipos de evento: coherencia entre el Literal, la configuración y el SQL."""

import re
from pathlib import Path
from typing import get_args

from munych_api.shared.kernel.catalog import (
    DEFAULT_EVENT_TYPE,
    EVENT_TYPES,
    EventType,
    VoterRole,
)

MIGRATIONS = Path(__file__).resolve().parents[4] / "supabase" / "migrations"


def test_every_event_type_has_config() -> None:
    assert set(EVENT_TYPES) == set(get_args(EventType))
    assert DEFAULT_EVENT_TYPE in EVENT_TYPES


def test_judges_only_keeps_current_flow() -> None:
    assert EVENT_TYPES["judges_only"].voter_roles == ("judge",)


def test_voting_includes_delegates_staff_and_judges_with_equal_weight() -> None:
    config = EVENT_TYPES["voting"]
    assert set(config.voter_roles) == {"delegate", "staff", "judge"}
    assert len(set(config.voter_weights.values())) == 1


def test_voter_roles_and_weights_are_valid() -> None:
    roles = set(get_args(VoterRole))
    for config in EVENT_TYPES.values():
        assert config.voter_weights, "cada tipo necesita al menos un rol que vote"
        assert set(config.voter_roles) <= roles
        assert all(weight > 0 for weight in config.voter_weights.values())


def test_sql_check_matches_catalog() -> None:
    sql = "\n".join(p.read_text(encoding="utf-8") for p in sorted(MIGRATIONS.glob("*.sql")))
    match = re.search(r"event_type in \(([^)]*)\)", sql)
    assert match, "falta el CHECK de app.events.event_type"
    in_sql = set(re.findall(r"'([a-z_]+)'", match.group(1)))
    assert in_sql == set(EVENT_TYPES)
