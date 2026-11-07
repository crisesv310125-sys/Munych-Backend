"""Exportación a CSV (2026-11-07)."""

import csv
import io
import uuid
from decimal import Decimal

from munych_api.modules.results.application.ports import ExportOptions
from munych_api.modules.results.domain.models import (
    DelegateScore,
    DelegationInfo,
    RankingEntry,
)
from munych_api.modules.results.infrastructure.csv_exporter import CsvExporter

from .test_excel_export import export_data


def rows(content: bytes) -> list[list[str]]:
    assert content.startswith("﻿".encode())  # BOM: Excel abre bien los acentos
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))


def test_csv_is_a_flat_ranking() -> None:
    table = rows(CsvExporter().export(export_data()))
    assert table[0] == [
        "Comité",
        "Siglas",
        "Posición",
        "Empate",
        "Delegación",
        "Institución",
        "Delegados",
        "Nota",
        "Premios",
        "Avisos",
    ]
    assert table[1] == [
        "Asamblea",
        "AG",
        "1",
        "",
        "MX",
        "Colegio",
        "Ana Pérez",
        "87.46",
        "Mejor delegado",
        "",
    ]


def test_csv_adds_role_scores_and_hides_scores_on_request() -> None:
    data = export_data()
    entry = data.committees[0].ranking[0]
    data.committees[0].ranking[0] = RankingEntry(
        position=entry.position,
        tied=entry.tied,
        delegation=entry.delegation,
        delegates=entry.delegates,
        score=entry.score,
        criteria_averages={},
        role_scores={"chair": Decimal(90), "delegate": None, "staff": Decimal("80.5")},
    )
    table = rows(CsvExporter().export(data))
    assert table[0][7:11] == ["Nota", "Nota Mesa Directiva", "Nota Staff", "Nota Delegados"]
    assert table[1][7:11] == ["87.46", "90.00", "80.50", ""]

    hidden = rows(CsvExporter().export(export_data(ExportOptions(include_scores=False))))
    assert "Nota" not in hidden[0]


def test_csv_neutralizes_formulas() -> None:
    data = export_data()
    evil = DelegationInfo(uuid.uuid4(), None, "=HYPERLINK(1)", "@colegio", ())
    data.committees[0].ranking.append(
        RankingEntry(
            position=2,
            tied=False,
            delegation=evil,
            delegates=(DelegateScore(uuid.uuid4(), "+Luis", None),),
            score=None,
            criteria_averages={},
        )
    )
    table = rows(CsvExporter().export(data))
    assert table[2][4:8] == ["'=HYPERLINK(1)", "'@colegio", "'+Luis", ""]
