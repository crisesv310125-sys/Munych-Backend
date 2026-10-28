"""Lectura del CSV de delegaciones (sección 7.4)."""

import pytest

from munych_api.modules.events.csv_import import (
    CsvRow,
    CsvRowError,
    parse_delegations_csv,
)
from munych_api.shared.kernel import DomainError, ErrorCode

HEADER = "country_code,character_name,institution,delegate_1,delegate_2\n"


def _parse(body: str, mode: str = "double") -> list[CsvRow | CsvRowError]:
    return parse_delegations_csv((HEADER + body).encode("utf-8"), mode)  # type: ignore[arg-type]


def test_parses_example_from_spec() -> None:
    rows = _parse(
        "MX,,Colegio Ejemplo,Ana Pérez López,\n"
        "US,,Instituto Norte,John Smith,Mary Jones\n"
        ",Ministro de Defensa,Colegio Sur,Luis Gómez,\n"
    )
    assert rows == [
        CsvRow(2, "MX", None, "Colegio Ejemplo", ("Ana Pérez López",)),
        CsvRow(3, "US", None, "Instituto Norte", ("John Smith", "Mary Jones")),
        CsvRow(4, None, "Ministro de Defensa", "Colegio Sur", ("Luis Gómez",)),
    ]


def test_delegate_2_in_single_committee_is_row_error() -> None:
    rows = _parse("MX,,Colegio,Ana,\nUS,,Instituto,John,Mary\n", mode="single")
    assert isinstance(rows[0], CsvRow)
    assert isinstance(rows[1], CsvRowError)
    assert rows[1].line == 3
    assert "delegate_2" in rows[1].message


@pytest.mark.parametrize(
    ("line", "fragment"),
    [
        (",,Colegio,Ana,", "exactamente uno"),
        ("MX,Ministro,Colegio,Ana,", "exactamente uno"),
        ("MEX,,Colegio,Ana,", "ISO"),
        ("MX,,Colegio," + "a" * 201 + ",", "200"),
    ],
)
def test_invalid_rows(line: str, fragment: str) -> None:
    (row,) = _parse(line + "\n")
    assert isinstance(row, CsvRowError)
    assert fragment in row.message


def test_lowercase_country_is_normalized_and_blank_lines_ignored() -> None:
    rows = _parse("mx,,Colegio,Ana,\n,,,,\n")
    assert rows == [CsvRow(2, "MX", None, "Colegio", ("Ana",))]


def test_utf8_bom_is_accepted() -> None:
    content = ("﻿" + HEADER + "MX,,Colegio,Ana,\n").encode()
    assert len(parse_delegations_csv(content, "single")) == 1


@pytest.mark.parametrize(
    ("content", "fragment"),
    [
        (b"country_code,institution\nMX,x\n", "Faltan columnas"),
        ((HEADER + "MX,,Colegio,Ana,\n").encode("latin-1") + b"\xff", "UTF-8"),
        (b"x" * (1024 * 1024 + 1), "1 MB"),
    ],
    ids=["columnas", "codificacion", "tamano"],
)
def test_invalid_files(content: bytes, fragment: str) -> None:
    with pytest.raises(DomainError) as exc:
        parse_delegations_csv(content, "single")
    assert exc.value.code == ErrorCode.VALIDATION_ERROR
    assert fragment in exc.value.detail


def test_too_many_rows() -> None:
    body = "".join(f",Personaje {i},Colegio,Ana,\n" for i in range(501))
    with pytest.raises(DomainError, match="500 filas"):
        _parse(body)
