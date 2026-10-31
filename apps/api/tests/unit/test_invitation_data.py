"""Metadatos del correo de invitación de jueces (plantilla `{{ .Data.* }}` de Supabase)."""

from datetime import date

import pytest

from munych_api.modules.identity.service import format_event_dates, invitation_data


@pytest.mark.parametrize(
    ("starts_on", "ends_on", "expected"),
    [
        (date(2026, 11, 12), date(2026, 11, 12), "12 de noviembre de 2026"),
        (date(2026, 11, 12), date(2026, 11, 14), "12–14 de noviembre de 2026"),
        (date(2026, 10, 30), date(2026, 11, 2), "30 de octubre – 2 de noviembre de 2026"),
        (
            date(2026, 12, 30),
            date(2027, 1, 2),
            "30 de diciembre de 2026 – 2 de enero de 2027",
        ),
    ],
)
def test_format_event_dates(starts_on: date, ends_on: date, expected: str) -> None:
    assert format_event_dates(starts_on, ends_on) == expected


def test_invitation_data_with_event() -> None:
    event = {
        "name": "SD-MUN 2026",
        "venue": "Santo Domingo",
        "starts_on": date(2026, 10, 9),
        "ends_on": date(2026, 10, 11),
    }
    assert invitation_data("Ana Pérez", event) == {
        "full_name": "Ana Pérez",
        "event_name": "SD-MUN 2026",
        "event_dates": "9–11 de octubre de 2026",
        "event_host": "Santo Domingo",
    }


def test_invitation_data_without_venue_or_event() -> None:
    event = {"name": "X", "venue": None, "starts_on": date(2026, 1, 1), "ends_on": date(2026, 1, 1)}
    assert invitation_data("Ana", event)["event_host"] == "Por confirmar"
    assert invitation_data("Ana", None) == {"full_name": "Ana"}
