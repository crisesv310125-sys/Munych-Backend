"""Documento público de resultados (sección 7.5). ÚNICA fuente de la salida pública.

Se construye por **lista blanca** a partir de la instantánea: nunca incluye
jueces, comentarios, IDs internos ni puntajes si `show_scores = false`.
"""

from datetime import datetime
from typing import Any

from munych_api.modules.results.domain.models import NameFormat, PublicationSettings
from munych_api.shared.kernel.catalog import AWARD_TYPES

# Partículas que no se usan como inicial del apellido ("Juan de la Cruz" → "Juan C.").
_PARTICLES = frozenset(
    {"de", "del", "la", "las", "los", "y", "da", "das", "do", "dos", "van", "von"}
)


def format_name(full_name: str, name_format: NameFormat) -> str | None:
    """`full` → tal cual; `first_name_initial` → "Ana P."; `hidden` → None."""
    if name_format == "hidden":
        return None
    words = full_name.split()
    if name_format == "full" or len(words) <= 1:
        return " ".join(words)
    # TODO(cliente): confirmar el formato con nombres compuestos ("María José Pérez" → "María J.").
    surname = next((w for w in words[1:] if w.lower() not in _PARTICLES), words[1])
    return f"{words[0]} {surname[0].upper()}."


def _delegation(delegation: dict[str, Any], settings: PublicationSettings) -> dict[str, Any]:
    return {
        "country_code": delegation.get("country_code"),
        "character_name": delegation.get("character_name"),
        "institution": delegation.get("institution") if settings.show_institution else None,
    }


def _delegates(entry: dict[str, Any], settings: PublicationSettings) -> list[str]:
    names = (format_name(d["full_name"], settings.name_format) for d in entry["delegates"])
    return [n for n in names if n]


def _committee(committee: dict[str, Any], settings: PublicationSettings) -> dict[str, Any]:
    entries = {e["delegation"]["id"]: e for e in committee["ranking"]}
    order = {t: i for i, t in enumerate(AWARD_TYPES)}
    awards = sorted(
        (a for a in committee["awards"] if a["delegation_id"] in entries),
        key=lambda a: (order[a["award_type"]], a["position"]),
    )
    ranking = None
    if settings.show_ranking:
        ranking = [
            {
                "position": e["position"],
                "delegation": _delegation(e["delegation"], settings),
                "delegates": _delegates(e, settings),
                "score": e["score"] if settings.show_scores else None,
            }
            for e in committee["ranking"]
        ]
    return {
        "slug": committee["slug"],
        "name": committee["name"],
        "acronym": committee["acronym"],
        "type": committee["type"],
        "awards": [
            {
                "award_type": a["award_type"],
                "position": a["position"],
                "delegation": _delegation(entries[a["delegation_id"]]["delegation"], settings),
                "delegates": _delegates(entries[a["delegation_id"]], settings),
            }
            for a in awards
        ],
        "ranking": ranking,
    }


def _general_ranking(
    committees: list[dict[str, Any]], settings: PublicationSettings
) -> list[dict[str, Any]] | None:
    """Ranking general del evento: todas las delegaciones con nota, de mayor a menor.

    Pedido en la reunión del 2026-10-28 (ganadores, ranking por comité y ranking general).
    La nota de cada comité ya está en 0-100, así que se comparan directamente. Las notas
    iguales comparten lugar; las delegaciones sin nota no aparecen. Solo con `show_ranking`.
    """
    if not settings.show_ranking:
        return None
    rows = [
        (committee, entry)
        for committee in committees
        for entry in committee["ranking"]
        if entry["score"] is not None
    ]
    rows.sort(key=lambda row: (-row[1]["score"], row[0]["name"], row[1]["position"]))
    result: list[dict[str, Any]] = []
    for i, (committee, entry) in enumerate(rows):
        tied = i > 0 and rows[i - 1][1]["score"] == entry["score"]
        result.append(
            {
                "position": result[-1]["position"] if tied else i + 1,
                "committee": {
                    "slug": committee["slug"],
                    "name": committee["name"],
                    "acronym": committee["acronym"],
                },
                "delegation": _delegation(entry["delegation"], settings),
                "delegates": _delegates(entry, settings),
                "score": entry["score"] if settings.show_scores else None,
            }
        )
    return result


def build_public_view(
    snapshot: dict[str, Any],
    settings: PublicationSettings,
    *,
    version: int,
    published_at: datetime,
) -> dict[str, Any]:
    event = snapshot["event"]
    return {
        "event": {
            "slug": event["slug"],
            "name": event["name"],
            "brand": event["brand"],
            "logo_url": event["logo_url"],
            "venue": event["venue"],
            "starts_on": event["starts_on"],
            "ends_on": event["ends_on"],
            "timezone": event["timezone"],
        },
        "settings": settings.to_dict(),
        "committees": [_committee(c, settings) for c in snapshot["committees"]],
        "general_ranking": _general_ranking(snapshot["committees"], settings),
        "published_at": published_at.isoformat().replace("+00:00", "Z"),
        "version": version,
    }
