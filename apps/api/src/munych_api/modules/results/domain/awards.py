"""Reglas de premios (sección 6.4): asignación manual, los cupos solo avisan."""

from collections import Counter
from collections.abc import Iterable
from uuid import UUID

from munych_api.modules.results.domain.models import Award
from munych_api.shared.kernel import DomainError, ErrorCode, NotFoundError
from munych_api.shared.kernel.catalog import AWARD_LABELS, AWARD_TYPES, AwardType


def validate_awards(awards: Iterable[Award], delegation_ids: Iterable[UUID]) -> None:
    items = list(awards)
    known = set(delegation_ids)
    if any(a.delegation_id not in known for a in items):
        raise NotFoundError("Alguna delegación no pertenece a este comité")
    keys = [(a.award_type, a.delegation_id) for a in items]
    if len(keys) != len(set(keys)):
        raise DomainError(
            ErrorCode.VALIDATION_ERROR, "Una delegación no puede recibir dos veces el mismo premio"
        )
    if any(a.position < 1 for a in items):
        raise DomainError(ErrorCode.VALIDATION_ERROR, "La posición del premio debe ser 1 o más")


def quota_warnings(awards: Iterable[Award], quotas: dict[AwardType, int]) -> list[str]:
    """Un aviso por tipo de premio que supera su cupo. No bloquea la asignación."""
    counts = Counter(a.award_type for a in awards)
    warnings = []
    for award_type in AWARD_TYPES:
        quota = quotas.get(award_type, 0)
        if counts[award_type] > quota:
            warnings.append(
                f"{AWARD_LABELS[award_type]}: {counts[award_type]} asignados y el cupo es {quota}"
            )
    return warnings


def sort_awards(awards: Iterable[Award]) -> list[Award]:
    order = {t: i for i, t in enumerate(AWARD_TYPES)}
    return sorted(awards, key=lambda a: (order[a.award_type], a.position, str(a.delegation_id)))
