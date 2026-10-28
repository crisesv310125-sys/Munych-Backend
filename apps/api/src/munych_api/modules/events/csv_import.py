"""Lectura y validación del CSV de delegaciones (sección 7.4). Sin acceso a datos."""

import csv
import io
import re
from dataclasses import dataclass

from munych_api.shared.kernel import DomainError, ErrorCode
from munych_api.shared.kernel.catalog import MAX_DELEGATES, DelegationMode

EXPECTED_COLUMNS = ("country_code", "character_name", "institution", "delegate_1", "delegate_2")
MAX_FILE_BYTES = 1024 * 1024
MAX_ROWS = 500
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_MAX_TEXT = 200


@dataclass(frozen=True, slots=True)
class CsvRow:
    line: int
    country_code: str | None
    character_name: str | None
    institution: str | None
    delegates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CsvRowError:
    line: int
    message: str


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def parse_delegations_csv(
    content: bytes, delegation_mode: DelegationMode
) -> list[CsvRow | CsvRowError]:
    """Devuelve una entrada por fila de datos: la fila válida o su error."""
    if len(content) > MAX_FILE_BYTES:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "El archivo supera 1 MB")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "El archivo debe estar en UTF-8") from exc

    reader = csv.DictReader(io.StringIO(text), delimiter=",")
    header = tuple((name or "").strip() for name in (reader.fieldnames or ()))
    missing = [c for c in EXPECTED_COLUMNS if c not in header]
    if missing:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            "Faltan columnas en la cabecera: " + ", ".join(missing),
        )
    reader.fieldnames = list(header)

    results: list[CsvRow | CsvRowError] = []
    for index, raw in enumerate(reader):
        line = index + 2  # la cabecera es la línea 1
        if index >= MAX_ROWS:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR, f"El archivo supera {MAX_ROWS} filas de datos"
            )
        values = {k: _clean(v) for k, v in raw.items() if isinstance(k, str)}
        if not any(values.values()):
            continue  # fila vacía
        results.append(_validate_row(line, values, delegation_mode))
    return results


def _validate_row(
    line: int, values: dict[str, str | None], delegation_mode: DelegationMode
) -> CsvRow | CsvRowError:
    country = values.get("country_code")
    character = values.get("character_name")
    if country is not None:
        country = country.upper()

    if (country is None) == (character is None):
        return CsvRowError(line, "Indica exactamente uno: country_code o character_name")
    if country is not None and not _COUNTRY.match(country):
        return CsvRowError(line, f"country_code «{country}» no es un código ISO de 2 letras")

    delegates = tuple(
        name for name in (values.get("delegate_1"), values.get("delegate_2")) if name is not None
    )
    if values.get("delegate_2") is not None and delegation_mode == "single":
        return CsvRowError(line, "El comité es de delegación individual y la fila tiene delegate_2")
    if len(delegates) > MAX_DELEGATES[delegation_mode]:  # pragma: no cover — cubierto arriba
        return CsvRowError(line, "Demasiados delegados para el comité")

    too_long = [
        v for v in (character, values.get("institution"), *delegates) if v and len(v) > _MAX_TEXT
    ]
    if too_long:
        return CsvRowError(line, f"Algún valor supera {_MAX_TEXT} caracteres")

    return CsvRow(
        line=line,
        country_code=country,
        character_name=character,
        institution=values.get("institution"),
        delegates=delegates,
    )
