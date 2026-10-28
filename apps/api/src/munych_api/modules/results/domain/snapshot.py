"""Instantánea inmutable de resultados al cerrar el evento (sección 6.5).

Es un documento JSON interno: contiene nombres completos y notas, así que
**nunca** se publica tal cual. La salida pública la genera solo
`build_public_view`.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from munych_api.modules.results.domain.awards import sort_awards
from munych_api.modules.results.domain.models import (
    Award,
    CommitteeInfo,
    EventInfo,
    PublicationSettings,
    RankingEntry,
)
from munych_api.scoring_engine import present

SNAPSHOT_SCHEMA_VERSION = 1


def presented(value: Decimal | None) -> float | None:
    rounded = present(value)
    return None if rounded is None else float(rounded)


def ranking_entry_to_dict(entry: RankingEntry) -> dict[str, Any]:
    delegation = entry.delegation
    return {
        "position": entry.position,
        "tied": entry.tied,
        "delegation": {
            "id": str(delegation.id),
            "country_code": delegation.country_code,
            "character_name": delegation.character_name,
            "institution": delegation.institution,
        },
        "delegates": [
            {
                "id": str(d.delegate_id),
                "full_name": d.full_name,
                "final_score": presented(d.final_score),
            }
            for d in entry.delegates
        ],
        "score": presented(entry.score),
        "criteria_averages": {str(k): presented(v) for k, v in entry.criteria_averages.items()},
        "incomplete_flags": [
            {
                "kind": f.kind,
                "delegate_id": str(f.delegate_id),
                "session_number": f.session_number,
                "judge_id": str(f.judge_id) if f.judge_id else None,
            }
            for f in entry.incomplete_flags
        ],
    }


def build_snapshot(
    event: EventInfo,
    logo_url: str | None,
    committees: Sequence[tuple[CommitteeInfo, Sequence[RankingEntry], Sequence[Award]]],
    settings: PublicationSettings,
    closed_at: datetime,
) -> dict[str, Any]:
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "closed_at": closed_at.isoformat(),
        "publication_settings": settings.to_dict(),
        "event": {
            "id": str(event.id),
            "slug": event.slug,
            "name": event.name,
            "brand": event.brand,
            "logo_url": logo_url,
            "venue": event.venue,
            "starts_on": event.starts_on.isoformat(),
            "ends_on": event.ends_on.isoformat(),
            "timezone": event.timezone,
        },
        "committees": [
            {
                "id": str(committee.id),
                "slug": committee.slug,
                "name": committee.name,
                "acronym": committee.acronym,
                "type": committee.type,
                "award_quotas": dict(committee.award_quotas),
                "ranking": [ranking_entry_to_dict(e) for e in ranking],
                "awards": [
                    {
                        "award_type": a.award_type,
                        "position": a.position,
                        "delegation_id": str(a.delegation_id),
                    }
                    for a in sort_awards(awards)
                ],
            }
            for committee, ranking, awards in committees
        ],
    }
