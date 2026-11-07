"""Exportación a CSV: el ranking de todos los comités en una sola tabla plana.

Pensado para procesarlo fuera (hojas de cálculo, scripts). UTF-8 con BOM para que Excel
respete los acentos, separado por comas y con el punto como separador decimal.
"""

import csv
import io

from munych_api.modules.results.application.ports import ExportData
from munych_api.modules.results.domain.awards import sort_awards
from munych_api.scoring_engine import present
from munych_api.shared.kernel.catalog import AWARD_LABELS, VOTER_ROLE_LABELS, VoterRole

CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_FLAG_LABELS = {
    "incomplete": "juez incompleto",
    "session_without_scores": "sesión sin notas",
    "delegate_without_scores": "delegado sin notas",
}

Cell = str | int | None


def _safe(value: Cell) -> Cell:
    """Evita que un texto se interprete como fórmula al abrir el CSV en Excel."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _score(value: object) -> str:
    rounded = present(value)  # type: ignore[arg-type]
    return "" if rounded is None else str(rounded)


class CsvExporter:
    media_type = CSV_MEDIA_TYPE
    extension = "csv"

    def export(self, data: ExportData) -> bytes:
        include_scores = data.options.include_scores
        # Nota por rol solo si el evento tiene más de un rol (en «solo jueces» es la misma nota).
        roles: list[VoterRole] = [
            role
            for role in VOTER_ROLE_LABELS
            if any(role in e.role_scores for c in data.committees for e in c.ranking)
        ]
        if len(roles) <= 1:
            roles = []

        headers = ["Comité", "Siglas", "Posición", "Empate", "Delegación"]
        headers += ["Institución", "Delegados"]
        if include_scores:
            headers.append("Nota")
            headers += [f"Nota {VOTER_ROLE_LABELS[r]}" for r in roles]
        headers += ["Premios", "Avisos"]

        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(headers)
        for committee in data.committees:
            info = committee.committee
            awards: dict[object, list[str]] = {}
            for award in sort_awards(committee.awards):
                awards.setdefault(award.delegation_id, []).append(AWARD_LABELS[award.award_type])
            for entry in committee.ranking:
                row: list[Cell] = [
                    info.name,
                    info.acronym,
                    entry.position,
                    "Sí" if entry.tied else "",
                    entry.delegation.label,
                    entry.delegation.institution,
                    ", ".join(d.full_name for d in entry.delegates),
                ]
                if include_scores:
                    row.append(_score(entry.score))
                    row += [_score(entry.role_scores.get(r)) for r in roles]
                row += [
                    ", ".join(awards.get(entry.delegation.id, [])),
                    ", ".join(
                        sorted({_FLAG_LABELS.get(f.kind, f.kind) for f in entry.incomplete_flags})
                    ),
                ]
                writer.writerow([_safe(v) for v in row])
        return ("﻿" + buffer.getvalue()).encode("utf-8")
